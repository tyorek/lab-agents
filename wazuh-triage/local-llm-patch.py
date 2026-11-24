#!/usr/bin/env python3
# wazuh-triage-local-llm-patch.py -- swap the deployed wazuh-triage claude -p call for llm-report.
# The deployed run.sh is newer than the old workspace copy (state-file dedupe, now-12h-30m,
# error handling, Kuma), so it is patched in place instead of replaced. Run on the agent box:
#   cp run.sh run.sh.pre-local-llm && python3 /tmp/wazuh-triage-local-llm-patch.py /home/agent/agents/wazuh-triage/run.sh
# Refuses (exit 1, file unchanged) unless it finds exactly one matching claude -p call.
import re, pathlib, sys
p = pathlib.Path(sys.argv[1]); s = p.read_text()
new = '''/home/agent/agents/bin/llm-report \\
  --input /tmp/alerts.json \\
  --report "$REPORT" \\
  --task "Triage these deduplicated Wazuh alerts (level 7 and up, new or changed since the last run) per CLAUDE.md and write the report." \\
  --ok-verdict "Nothing actionable"'''
s2, n = re.subn(r'claude -p "Triage the alerts.*?>> logs/run\.log', lambda m: new, s, flags=re.S)
if n != 1: sys.exit(f"expected 1 claude call, found {n}; not patched")
p.write_text(s2); print("patched", p)
