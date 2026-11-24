#!/usr/bin/env python3
"""local-llm-patch.py -- switch the deployed agents' `claude -p` calls to llm-report.

Run as root on the agent box (2026-10-30). The deployed run.sh files are newer than
the copies in the workspace, so only the one model call in each is replaced; the
rest of every script is left exactly as deployed. All or nothing: if any of the
three calls isn't found exactly once, nothing is written. Each file is backed up
to run.sh.pre-local-llm first, and restored if the patched file fails `bash -n`.
Re-running after a successful patch finds no claude calls and changes nothing.

Rollback: cp -p run.sh.pre-local-llm run.sh in each agent folder, or set
LLM_MODE=claude in agent.env to keep the patch but send everything to Claude.
"""
import pathlib
import re
import shutil
import subprocess
import sys

BASE = pathlib.Path("/home/agent/agents")
LLM = "/home/agent/agents/bin/llm-report"

PATCHES = {
    "wazuh-triage": (
        r'claude -p "Triage the alerts.*?--max-turns 6 >> logs/run\.log',
        f'''{LLM} \\
  --input /tmp/alerts.json \\
  --report "$REPORT" \\
  --task "Triage these deduplicated Wazuh alerts (level 7 and up, new or changed since the last run) per CLAUDE.md and write the report." \\
  --ok-verdict "Nothing actionable"'''),
    "mikrotik-audit": (
        r'claude -p "Summarize what changed.*?--max-turns 6 >> logs/run\.log 2>&1',
        f'''{LLM} \\
      --input "$DIFF_FILE" \\
      --report "$REPORT" \\
      --task "Summarize what changed in this MikroTik RouterOS config diff for device ${{DEVICE}} (unified diff, old=${{PREV_DATE}}, new=${{TODAY}}) and flag anything security-relevant -- new/changed firewall rules, user/policy changes, exposed services, DNS or NAT changes." \\
      --ok-verdict "No security-relevant changes" \\
      || echo "$(date -Is): [$DEVICE] no report written for this diff, see logs/run.log" >&2'''),
    "daily-digest": (
        r'claude -p "Write today.s daily digest.*?--max-turns 6 >> logs/run\.log 2>&1',
        f'''{LLM} \\
  --input "$INPUT" \\
  --report "$REPORT" \\
  --task "Write today's daily digest per CLAUDE.md from the collected input." \\
  --ok-verdict "All clear" \\
  --no-escalate-on-flag'''),
}


def main():
    if not pathlib.Path(LLM).is_file():
        sys.exit(f"{LLM} is not installed; install it first")
    planned = {}
    for agent, (pattern, new) in PATCHES.items():
        path = BASE / agent / "run.sh"
        text = path.read_text()
        out, n = re.subn(pattern, lambda m: new, text, flags=re.S)
        if n == 0 and LLM in text:
            print(f"{agent}: already patched, skipping")
            continue
        if n != 1:
            sys.exit(f"{agent}: expected 1 claude -p call, found {n}; nothing changed")
        planned[path] = out
    for path, out in planned.items():
        backup = path.with_name("run.sh.pre-local-llm")
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(out)  # same inode: owner and mode stay as deployed
        if subprocess.run(["bash", "-n", str(path)]).returncode != 0:
            shutil.copy2(backup, path)
            sys.exit(f"{path}: patched file failed bash -n, restored the backup")
        print(f"patched {path} (backup {backup.name})")


if __name__ == "__main__":
    main()
