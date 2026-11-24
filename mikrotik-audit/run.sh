#!/bin/bash
# mikrotik-audit/run.sh
# Pulls each day's RouterOS config export (<prefix>-<date>.rsc) from the
# router and all three CRS305 switches via SFTP (agent-ro group, key auth)
# and diffs each against its own last successfully pulled snapshot. Only
# calls Claude for devices whose config actually changed. One device's
# failure doesn't stop the others from being checked.
#
# Deploy as /home/agent/agents/mikrotik-audit/run.sh (chmod +x, owned by agent).
# Expects one HOST var per device in /home/agent/.config/agent.env:
#   MIKROTIK_HOST   - rtr-homelab (main router)
#   AG01_HOST       - ag01-homelab (192.168.99.4)
#   AG02_HOST       - ag02-homelab (192.168.99.5)
#   AG03_HOST       - ag03-homelab (192.168.99.6)
# and ANTHROPIC_API_KEY already set up via `claude` login.
# Reports are written by the local model on the LLM container through
# /home/agent/agents/bin/llm-report, escalating flagged diffs to Claude
# (2026-10-30). LLM_MODE=claude in agent.env restores Claude-only.
# Reuses the agent's existing SSH key (/home/agent/.ssh/id_ed25519) and the
# `agent` account (agent-ro group, ftp policy allowed) on all four devices.

set -uo pipefail
source /home/agent/.config/agent.env
# Uptime Kuma heartbeat: on every exit, report up (exit 0) or down (anything
# else) to this agent's push monitor. The URL comes from agent.env, named after
# the agent's folder, e.g. KUMA_PUSH_WAZUH_TRIAGE. A failed push never changes
# the agent's own exit status.
KUMA_VAR="KUMA_PUSH_$(basename "$(dirname "$(readlink -f "$0")")" | tr 'a-z-' 'A-Z_')"
kuma_push() {
    local rc=$?
    local url="${!KUMA_VAR:-}"
    [ -n "$url" ] || return 0
    local status=up
    [ "$rc" -eq 0 ] || status=down
    curl -fsS -m 10 -o /dev/null "${url}?status=${status}&msg=exit%20${rc}" || true
}
trap kuma_push EXIT
cd "$(dirname "$0")"

SSH_USER="agent"
KEY="/home/agent/.ssh/id_ed25519"
TODAY=$(date +%Y-%m-%d)

# device_name  host_env_var  remote_file_prefix
DEVICES=(
    "rtr-homelab MIKROTIK_HOST rtr-backup-"
    "ag01-homelab AG01_HOST ag01-backup-"
    "ag02-homelab AG02_HOST ag02-backup-"
    "ag03-homelab AG03_HOST ag03-backup-"
)

process_device() {
    local DEVICE="$1" HOST_VAR="$2" PREFIX="$3"
    local HOST="${!HOST_VAR:-}"

    if [ -z "$HOST" ]; then
        echo "$(date -Is): [$DEVICE] skipped, $HOST_VAR not set in agent.env" >&2
        return 1
    fi

    mkdir -p "snapshots/${DEVICE}" reports logs state
    local STATE_FILE="state/${DEVICE}-last-pulled.txt"
    local REMOTE_FILE="${PREFIX}${TODAY}.rsc"
    local LOCAL_FILE="snapshots/${DEVICE}/${REMOTE_FILE}"

    if ! scp -i "$KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 \
          "${SSH_USER}@${HOST}:${REMOTE_FILE}" "$LOCAL_FILE" \
          2>"/tmp/mikrotik-audit-${DEVICE}-error.txt"; then
        echo "$(date -Is): [$DEVICE] failed to pull ${REMOTE_FILE} from ${HOST}, see /tmp/mikrotik-audit-${DEVICE}-error.txt" >&2
        return 1
    fi

    if [ ! -s "$STATE_FILE" ]; then
        echo "$TODAY" > "$STATE_FILE"
        echo "$(date -Is): [$DEVICE] first run, nothing to diff against yet"
        return 0
    fi

    local PREV_DATE
    PREV_DATE=$(cat "$STATE_FILE")
    local PREV_FILE="snapshots/${DEVICE}/${PREFIX}${PREV_DATE}.rsc"

    if [ ! -f "$PREV_FILE" ]; then
        echo "$(date -Is): [$DEVICE] previous snapshot ${PREV_FILE} missing locally, resetting baseline to today"
        echo "$TODAY" > "$STATE_FILE"
        return 0
    fi

    local DIFF_FILE="/tmp/mikrotik-diff-${DEVICE}.txt"
    if diff -u --label "$PREV_FILE" --label "$LOCAL_FILE" \
          <(sed -E '1,3s/^# [0-9-]+ [0-9:]+ by RouterOS/# by RouterOS/' "$PREV_FILE") \
          <(sed -E '1,3s/^# [0-9-]+ [0-9:]+ by RouterOS/# by RouterOS/' "$LOCAL_FILE") > "$DIFF_FILE"; then
        echo "$(date -Is): [$DEVICE] no config changes since ${PREV_DATE}"
        echo "$TODAY" > "$STATE_FILE"
        return 0
    fi

    local TS REPORT
    TS=$(date -u +%Y-%m-%dT%H%MZ)
    REPORT="reports/${DEVICE}-${TS}.md"

    echo "$(date -Is): [$DEVICE] config changed since ${PREV_DATE}, running triage -> ${REPORT}"
    # Local model first; anything not "No security-relevant changes", or a local
    # failure, is escalated to Claude (see llm-report). The diff is still marked
    # processed if both fail, as before: the snapshots keep the evidence.
    /home/agent/agents/bin/llm-report \
      --input "$DIFF_FILE" \
      --report "$REPORT" \
      --task "Summarize what changed in this MikroTik RouterOS config diff for device ${DEVICE} (unified diff, old=${PREV_DATE}, new=${TODAY}) and flag anything security-relevant -- new/changed firewall rules, user/policy changes, exposed services, DNS or NAT changes." \
      --ok-verdict "No security-relevant changes" \
      || echo "$(date -Is): [$DEVICE] no report written for this diff, see logs/run.log" >&2

    echo "$TODAY" > "$STATE_FILE"
}

OVERALL_STATUS=0
for entry in "${DEVICES[@]}"; do
    read -r DEVICE HOST_VAR PREFIX <<< "$entry"
    process_device "$DEVICE" "$HOST_VAR" "$PREFIX" || OVERALL_STATUS=1
done

exit $OVERALL_STATUS
