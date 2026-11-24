# lab-agents

The LLM agents that watch the home lab, all running unprivileged as `agent` in one LXC on a locked-down management VLAN. They default to a local model (Gemma on an Ollama container) and fall back to Claude only when the local model fails.

| Folder | What it is |
|---|---|
| `supervisor/` | HTTPS chat console (Python `http.server`, password + session token, CSP) that can read the agents' reports and logs, run an agent on request, and fetch web pages only when a message starts with `/web`. Changes to existing files, deletes and protected paths wait in an approvals panel; secrets are on a hard deny list. |
| `wazuh-triage/` | every 30 min: deduplicated level ≥ 7 Wazuh alerts → "does a human need to look at this now?" report |
| `mikrotik-audit/` | daily RouterOS / CRS305 / OPNsense config exports diffed against the last snapshot; `redact-opnsense` hashes secret-bearing XML values so diffs show *that* a secret changed, never the secret |
| `llm-report/` | shared helper that calls the local model (Anthropic Messages API on Ollama) with thinking-budget support |
| `setup/` | `setup-agent-lxc.sh` – container bootstrap |
| `homepage/` | `agents-tiles.py` – status tiles for the Homepage dashboard |
| `docs/agent-box-setup.md` | the full build plan and change log for the agent box |

Prompt-injection stance: every agent prompt states that log, alert and config content is data, not instructions.

---

*Published from a home lab. Site identifiers are sanitized: public IPv4 uses the documentation ranges (203.0.113.0/24, 198.51.100.0/24), the delegated IPv6 prefix is `2001:db8::/32`, the ULA prefix is `fd12:3456:789a::/48`, domains are `example.com` / `home.arpa`, MAC addresses, Wi-Fi SSIDs, serials, keys and names are replaced. RFC 1918 addresses are left as they are so the layouts still read. Credentials are never in these files; scripts read them from `agent.env` or similar files that are not published.*

## Disclaimer

This repository is shared **as is**, for reference and learning. It is a personal home-lab project, not a product, and it comes with no support.

- **No warranty.** Everything here (code, configurations, scripts, rules and documentation) is provided without warranty of any kind, express or implied, including fitness for a particular purpose. It may contain bugs, errors or omissions.
- **No commitment to maintain.** The author makes no commitment to fix bugs, answer questions, upgrade or update this repository beyond what is provided here. Any future updates are made purely on a voluntary basis, at the author's sole discretion, and may stop at any time.
- **You are solely responsible.** Any review, adaptation, configuration, testing, deployment or operation of this material is solely the responsibility of the person using it. Bugs, fixes and updates in your environment are yours to handle.
- **No liability.** To the fullest extent permitted by law, the author is not liable for any damages or losses of any kind arising from the use or misuse of this material, including but not limited to outages, data loss, security incidents, lost revenue, damage to hardware or other property, and any physical or digital harm.
- **Test before you trust.** Several scripts change firewalls, routers, DNS, authentication or system services. Read them, adapt them to your network, test them in a lab, and keep backups and a rollback path before running anything in production.

## License

The code and documentation in this repository are released under the [MIT License](LICENSE), an open-source license, unless a file or folder states otherwise.
