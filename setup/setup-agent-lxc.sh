#!/bin/bash
# setup-agent-lxc.sh
# Base install for the Claude monitoring agent LXC (Debian 12 / TurnKey Core,
# 192.168.99.3 on VLAN 99). Run as root, inside the container.
#
# Covers claude-noc-agent-setup.md steps 2 (install) and 4 (layout), plus
# generating the SSH keypair the `agent` user will need for the RouterOS
# agent-ro login (step 3's RouterOS side is done separately, in Winbox).

set -euo pipefail

echo "== 1. Base packages =="
apt update
apt install -y curl git jq ca-certificates

echo "== 2. Node.js 22.x =="
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt install -y nodejs

echo "== 3. agent user =="
if ! id agent &>/dev/null; then
    useradd -m -s /bin/bash agent
fi

echo "== 4. Claude Code CLI (global) =="
npm install -g @anthropic-ai/claude-code

echo "== 5. Directory layout =="
sudo -u agent mkdir -p /home/agent/agents/wazuh-triage/state
sudo -u agent mkdir -p /home/agent/agents/wazuh-triage/reports
sudo -u agent mkdir -p /home/agent/agents/mikrotik-audit/snapshots
sudo -u agent mkdir -p /home/agent/agents/mikrotik-audit/reports
sudo -u agent mkdir -p /home/agent/agents/daily-digest/reports
sudo -u agent mkdir -p /home/agent/.config
sudo -u agent touch /home/agent/.config/agent.env
chmod 600 /home/agent/.config/agent.env
chown agent:agent /home/agent/.config/agent.env

echo "== 6. SSH keypair for RouterOS (and other read-only) auth =="
if [ ! -f /home/agent/.ssh/id_ed25519 ]; then
    sudo -u agent mkdir -p /home/agent/.ssh
    sudo -u agent ssh-keygen -t ed25519 -f /home/agent/.ssh/id_ed25519 -N "" -C "agent@claude-noc-lxc"
    chmod 700 /home/agent/.ssh
fi

echo
echo "== Done. Remaining manual steps: =="
echo "1. su - agent -c 'claude'   # first run: log in / set ANTHROPIC_API_KEY"
echo "   (use a dedicated key with a spend limit; it lands in /home/agent/.config/agent.env, chmod 600)"
echo "2. Copy this public key -- it's what goes into the RouterOS agent-ro user as the authorized key:"
cat /home/agent/.ssh/id_ed25519.pub
echo
echo "3. Hand that key back so the RouterOS agent-ro group/user can be created with it."
