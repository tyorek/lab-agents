#!/bin/bash
# wazuh-triage/run.sh
# Pulls level>=7 Wazuh alerts from the last 30 min, dedupes them
# deterministically, and only calls Claude if there's anything new.
#
# Deploy as /home/agent/agents/wazuh-triage/run.sh (chmod +x, owned by agent).
# Expects WAZUH_INDEXER_URL / _USER / _PASS in /home/agent/.config/agent.env
# (see wazuh-indexer-readonly-setup.md) and ANTHROPIC_API_KEY already set up
# via `claude` login.

set -euo pipefail
source /home/agent/.config/agent.env
cd "$(dirname "$0")"

QUERY='{
  "size": 500,
  "sort": [{"@timestamp": "desc"}],
  "query": {
    "bool": {
      "filter": [
        {"range": {"@timestamp": {"gte": "now-30m"}}},
        {"range": {"rule.level": {"gte": 7}}}
      ]
    }
  }
}'

RAW=$(curl -sS -k -u "${WAZUH_INDEXER_USER}:${WAZUH_INDEXER_PASS}" \
  -H 'Content-Type: application/json' \
  -X GET "${WAZUH_INDEXER_URL}/wazuh-alerts-*/_search" -d "$QUERY")

# Dedupe by rule id + agent name: count, latest timestamp, keep one description.
echo "$RAW" | jq '
  [.hits.hits[]._source | {
    timestamp: ."@timestamp",
    rule_id: .rule.id,
    level: .rule.level,
    description: .rule.description,
    agent: .agent.name,
    agent_ip: (.agent.ip // "n/a")
  }]
  | group_by([.rule_id, .agent])
  | map({
      rule_id: .[0].rule_id,
      level: .[0].level,
      description: .[0].description,
      agent: .[0].agent,
      agent_ip: .[0].agent_ip,
      count: length,
      latest: (map(.timestamp) | max)
    })
  | sort_by(-.level)
' > /tmp/alerts.json

COUNT=$(jq 'length' /tmp/alerts.json)
if [ "$COUNT" -eq 0 ]; then
    echo "$(date -Is): no new level>=7 alerts, skipping Claude call"
    exit 0
fi

echo "$(date -Is): $COUNT distinct alert group(s), running triage"
mkdir -p reports
claude -p "Triage the alerts in /tmp/alerts.json per CLAUDE.md. Write a report." \
  --allowedTools "Read" "Write(reports/*)" \
  --max-turns 6 > "reports/$(date +%F-%H%M).md"

# TODO: once a notification channel is decided (push/email/Slack/etc), add a
# check here that greps the report for a "flag" and only then notifies --
# per the rollout plan, report-only for the first 1-2 weeks while tuning.
