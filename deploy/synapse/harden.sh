#!/usr/bin/env bash
# Server-Härtung für Synapse ("sicherer als sicher", Phase 0).
# Idempotent & defensiv (set -u, nicht -e), damit es nie still abbricht.
# Aufruf als root:  bash deploy/synapse/harden.sh
set -u

echo "== Synapse Server-Härtung =="

# 1) System aktuell + automatische Sicherheitsupdates
apt-get update -y || true
apt-get install -y unattended-upgrades fail2ban ufw || true
dpkg-reconfigure -f noninteractive unattended-upgrades || true

# 2) Firewall: nur SSH + HTTP/HTTPS
ufw allow OpenSSH || true
ufw allow 80/tcp || true
ufw allow 443/tcp || true
ufw --force enable || true

# 3) SSH härten (Key-Login, kein Root-Passwort-Login)
SSHD=/etc/ssh/sshd_config
if [ -f "$SSHD" ]; then
  sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' "$SSHD" || true
  sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' "$SSHD" || true
  systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true
  echo "  SSH gehärtet (Key-Login). ACHTUNG: vorher SSH-Key hinterlegen!"
fi

# 4) Fail2ban aktiv
systemctl enable --now fail2ban 2>/dev/null || true

# 5) Docker (für gekapselte Dienste, Phase 1+)
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh || echo "Docker-Installation übersprungen"
fi

echo "== Fertig. Empfehlung: vor SSH-Härtung unbedingt einen SSH-Key hinterlegen. =="
echo "   Status: ufw status ; systemctl status fail2ban --no-pager"
