# Applied 2026-11-01 on the agents box (as root, then py_compile as agent).
# Adds an opt-in --think N flag to /home/agent/agents/bin/llm-report (thinking-token budget for the
# local model). Default 0 sends exactly the old request ("thinking": disabled, max_tokens 2048), so
# wazuh-triage, mikrotik-audit and daily-digest are unchanged. Backup: llm-report.pre-think.
# Note: gemma4 does not honor budget_tokens; max_tokens (2048 + N) is the real cap.
import re,shutil,sys
p='/home/agent/agents/bin/llm-report'
s=open(p).read()
shutil.copy2(p,p+'.pre-think')
def sub(old,new):
    global s
    assert s.count(old)==1, ('not unique/missing', old)
    s=s.replace(old,new)
sub('def call_local(cfg, system, user):','def call_local(cfg, system, user, think=0):')
sub('        "max_tokens": 2048,\n','        "max_tokens": 2048 + think,\n')
sub('        "thinking": {"type": "disabled"},\n','        "thinking": ({"type": "enabled", "budget_tokens": think} if think\n                     else {"type": "disabled"}),\n')
sub("    ap.add_argument('--max-turns'","    ap.add_argument('--think', type=int, default=0,\n                    help='thinking-token budget for the local model (0 = off, the default)')\n    ap.add_argument('--max-turns'") if "ap.add_argument('--max-turns'" in s else sub('    ap.add_argument("--max-turns"','    ap.add_argument("--think", type=int, default=0,\n                    help="thinking-token budget for the local model (0 = off, the default)")\n    ap.add_argument("--max-turns"')
sub('call_local(cfg, system, user)\n','call_local(cfg, system, user, args.think)\n')
sub('     local model on the LLM container, Anthropic Messages API, thinking off.','     local model on the LLM container, Anthropic Messages API, thinking off\n     unless --think N gives it a thinking-token budget.')
open(p,'w').write(s)
print('PATCHED')
