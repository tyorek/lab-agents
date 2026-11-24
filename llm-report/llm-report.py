#!/usr/bin/env python3
"""llm-report -- write an agent report with the local model, escalating to Claude.

Deploy as /home/agent/agents/bin/llm-report (owner agent, chmod 755). Called from
each agent's run.sh in place of the old `claude -p` line, from inside the agent's
own folder (so ./CLAUDE.md is that agent's instructions):

    llm-report --input /tmp/alerts.json --report reports/x.md \
               --task "Triage the alerts per CLAUDE.md." \
               --ok-verdict "Nothing actionable"

What it does:
  1. Sends CLAUDE.md (as the system prompt) and the input file (inline) to the
     local model on the LLM container, Anthropic Messages API, thinking off.
  2. Reads the report's verdict line (the first line that isn't a heading).
     If it contains one of the --ok-verdict phrases, the local report is final.
  3. Otherwise -- the verdict flags something, or the local call failed, or the
     input is too big for the model's context -- it runs the original
     `claude -p` command so Claude writes the report instead. A flagged local
     draft is kept in reports/.local/ for comparison; if Claude fails too, that
     draft becomes the report so the run still produces something.
  --no-escalate-on-flag: only escalate on failure (used by daily-digest, whose
  flags come from fixed thresholds, not judgment).

Settings, from the environment or /home/agent/.config/agent.env (only these
keys are read from that file):
  LLM_MODE                  auto (default) | local (never call Claude) |
                            claude (skip the local model: the old behaviour)
  LOCAL_LLM_URL             default http://192.168.99.9:11434
  LOCAL_LLM_MODEL           default gemma4:12b-it-qat
  LOCAL_LLM_TIMEOUT         seconds per request, default 300
  LOCAL_LLM_MAX_INPUT_CHARS default 60000 (roughly what fits a 32K context
                            next to CLAUDE.md and the answer)

Stdlib only. Log lines go to stdout, which run.sh sends to logs/cron.log.
Exit 0 when a report was written, 1 when nothing was.
"""
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

AGENT_ENV = "/home/agent/.config/agent.env"
KEYS = ("LLM_MODE", "LOCAL_LLM_URL", "LOCAL_LLM_MODEL", "LOCAL_LLM_TIMEOUT",
        "LOCAL_LLM_MAX_INPUT_CHARS")
DEFAULTS = {
    "LLM_MODE": "auto",
    "LOCAL_LLM_URL": "http://192.168.99.9:11434",
    "LOCAL_LLM_MODEL": "gemma4:12b-it-qat",
    "LOCAL_LLM_TIMEOUT": "300",
    "LOCAL_LLM_MAX_INPUT_CHARS": "60000",
}

LOCAL_RULES = """

## How this run works (overrides the Tools section above)
You have no tools and cannot read or write files. The complete input file is
included in the user message between <input> and </input>. Reply with only the
report itself, in Markdown: it is saved verbatim as the report file. No
preamble, no closing remarks, no code fence around the whole report. The
verdict line the instructions above ask for must be the first line of the
report (after the title, if the instructions ask for one).
"""


def log(msg):
    print(f"{datetime.datetime.now().astimezone().isoformat(timespec='seconds')}: "
          f"[llm-report] {msg}", flush=True)


def load_settings():
    cfg = dict(DEFAULTS)
    try:
        with open(AGENT_ENV) as f:
            for line in f:
                line = line.strip()
                if line.startswith("export "):
                    line = line[7:].lstrip()
                key, sep, val = line.partition("=")
                if sep and key in KEYS:
                    cfg[key] = val.strip().strip("'\"")
    except OSError:
        pass
    for key in KEYS:
        if os.environ.get(key):
            cfg[key] = os.environ[key]
    return cfg


def call_local(cfg, system, user):
    body = json.dumps({
        "model": cfg["LOCAL_LLM_MODEL"],
        "max_tokens": 2048,
        "temperature": 0.2,
        "thinking": {"type": "disabled"},
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(
        cfg["LOCAL_LLM_URL"].rstrip("/") + "/v1/messages", data=body, method="POST",
        headers={"Content-Type": "application/json", "x-api-key": "ollama",
                 "anthropic-version": "2023-06-01"})
    last = None
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=float(cfg["LOCAL_LLM_TIMEOUT"])) as r:
                data = json.load(r)
            text = "".join(b.get("text", "") for b in data.get("content", [])
                           if b.get("type") == "text").strip()
            if data.get("stop_reason") == "max_tokens":
                raise RuntimeError("answer cut off at max_tokens")
            if not text:
                raise RuntimeError("empty answer")
            return text, data.get("usage", {})
        except (urllib.error.URLError, TimeoutError, OSError, ValueError,
                RuntimeError) as e:
            last = e
            if attempt == 1 and not isinstance(e, RuntimeError):
                time.sleep(10)
                continue
            break
    raise RuntimeError(f"local model failed: {last}")


def clean(text):
    m = re.fullmatch(r"```(?:markdown|md)?\s*\n(.*?)\n```", text.strip(), re.S)
    return (m.group(1) if m else text).strip() + "\n"


def verdict_line(text):
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or set(s) <= set("-=*_ "):
            continue
        s = re.sub(r"[*_>`]", "", s).strip()
        return re.sub(r"^verdict\s*:\s*", "", s, flags=re.I)
    return ""


def is_ok(verdict, phrases):
    v = verdict.casefold()
    return any(p.casefold() in v for p in phrases)


def run_claude(args):
    prompt = (f"{args.task} The input is in {args.input}. "
              f"Write the report to {args.report} and only that file.")
    cmd = ["claude", "-p", prompt,
           "--allowedTools", "Read", f"Write({args.reports_glob})", f"Edit({args.reports_glob})",
           "--max-turns", str(args.max_turns)]
    if not shutil.which("claude"):
        log("claude CLI not found, cannot escalate")
        return False
    before = os.path.getmtime(args.report) if os.path.exists(args.report) else None
    os.makedirs("logs", exist_ok=True)
    os.makedirs(os.path.dirname(args.report) or ".", exist_ok=True)
    with open("logs/run.log", "a") as out:
        rc = subprocess.run(cmd, stdout=out, stderr=subprocess.STDOUT).returncode
    wrote = (os.path.exists(args.report) and os.path.getsize(args.report) > 0
             and os.path.getmtime(args.report) != before)
    if rc != 0 or not wrote:
        log(f"claude exited {rc}, report {'written' if wrote else 'not written'} (see logs/run.log)")
    return wrote


def write(path, text, footer):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        f.write(text.rstrip("\n") + f"\n\n---\n_{footer}_\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--input", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--task", required=True, help="the job, without file paths")
    ap.add_argument("--ok-verdict", action="append", default=[],
                    help="verdict phrase meaning nothing to flag (repeatable)")
    ap.add_argument("--no-escalate-on-flag", action="store_true")
    ap.add_argument("--claude-md", default="CLAUDE.md")
    ap.add_argument("--reports-glob", default="reports/*")
    ap.add_argument("--max-turns", type=int, default=6)
    args = ap.parse_args()
    cfg = load_settings()
    mode = cfg["LLM_MODE"].lower()
    name = os.path.basename(args.report)

    def escalate(reason, draft=None):
        if mode == "local":
            if draft is None:
                log(f"{name}: {reason}; LLM_MODE=local, not escalating, no report")
                return 1
            write(args.report, draft, f"Written by {cfg['LOCAL_LLM_MODEL']} (local); "
                  f"{reason}, not escalated (LLM_MODE=local)")
            log(f"{name}: {reason}; kept local report (LLM_MODE=local)")
            return 0
        log(f"{name}: {reason}; escalating to Claude")
        if run_claude(args):
            with open(args.report, "a") as f:
                f.write(f"\n---\n_Written by Claude ({reason})._\n")
            log(f"{name}: written by Claude")
            return 0
        if draft is not None:
            write(args.report, draft, f"Written by {cfg['LOCAL_LLM_MODEL']} (local); "
                  f"{reason}, and the Claude escalation failed")
            log(f"{name}: Claude failed, kept the local draft as the report")
            return 0
        log(f"{name}: no report written")
        return 1

    if mode == "claude":
        return escalate("LLM_MODE=claude")

    try:
        with open(args.input, errors="replace") as f:
            data = f.read()
        with open(args.claude_md) as f:
            system = f.read() + LOCAL_RULES
    except OSError as e:
        log(f"{name}: cannot read input or CLAUDE.md: {e}")
        return 1
    if not data.strip():
        data = "(the input file is empty)"
    limit = int(cfg["LOCAL_LLM_MAX_INPUT_CHARS"])
    if len(data) > limit:
        return escalate(f"input is {len(data)} chars, over the local limit of {limit}")

    user = f"{args.task}\n\n<input>\n{data}\n</input>"
    t0 = time.monotonic()
    try:
        text, usage = call_local(cfg, system, user)
    except RuntimeError as e:
        return escalate(str(e))
    text = clean(text)
    secs = time.monotonic() - t0
    stats = (f"{usage.get('input_tokens', '?')} in / {usage.get('output_tokens', '?')} "
             f"out tokens, {secs:.0f} s")
    verdict = verdict_line(text)

    if not args.ok_verdict or is_ok(verdict, args.ok_verdict):
        write(args.report, text, f"Written by {cfg['LOCAL_LLM_MODEL']} (local, {stats})")
        log(f"{name}: written locally ({stats}), verdict: {verdict[:80]}")
        return 0

    if args.no_escalate_on_flag:
        write(args.report, text, f"Written by {cfg['LOCAL_LLM_MODEL']} (local, {stats})")
        log(f"{name}: written locally ({stats}), flagged, not escalated by design: {verdict[:80]}")
        return 0

    draft_dir = os.path.join(os.path.dirname(args.report) or ".", ".local")
    os.makedirs(draft_dir, exist_ok=True)
    write(os.path.join(draft_dir, name), text,
          f"Local draft by {cfg['LOCAL_LLM_MODEL']} ({stats}); escalated to Claude")
    return escalate(f"local model flagged: {verdict[:80]}", draft=text)


if __name__ == "__main__":
    sys.exit(main())
