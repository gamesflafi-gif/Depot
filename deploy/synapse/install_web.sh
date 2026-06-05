#!/usr/bin/env bash
# Synapse-Web als 24/7-Dienst einrichten (läuft auch nach Terminal-Schluss/Reboot).
# Aufruf als root:  bash deploy/synapse/install_web.sh
set -u

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PY="$PROJECT_DIR/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
SUDO="$(command -v sudo || true)"
UNIT="/etc/systemd/system/synapse-web.service"

$SUDO tee "$UNIT" >/dev/null <<EOF
[Unit]
Description=Synapse Web (Wissenschafts-Suche)
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$PROJECT_DIR
ExecStart=$PY -m synapse.cli serve --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Firewall (falls aktiv) für Port 8000 öffnen
command -v ufw >/dev/null 2>&1 && $SUDO ufw allow 8000/tcp >/dev/null 2>&1 || true

$SUDO systemctl daemon-reload || true
$SUDO systemctl enable --now synapse-web.service || true

echo "Synapse-Web läuft jetzt dauerhaft."
echo "  Status:  systemctl status synapse-web --no-pager"
echo "  Logs:    journalctl -u synapse-web -f"
echo "  Seite:   http://<SERVER-IP>:8000"
