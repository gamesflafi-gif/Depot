#!/usr/bin/env bash
# Richtet den interaktiven Telegram-Bot als dauerhaften systemd-Dienst ein,
# damit du jederzeit /Befehle in den Chat schreiben kannst.
# Aufruf:  bash deploy/install_bot.sh
set -u

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="$PROJECT_DIR/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
SUDO="$(command -v sudo || true)"

# .env (Token/Chat-ID) in den Dienst durchreichen, falls vorhanden
ENV_LINE=""
[ -f "$PROJECT_DIR/.env" ] && ENV_LINE="EnvironmentFile=$PROJECT_DIR/.env"

UNIT="/etc/systemd/system/stockai-bot.service"
$SUDO tee "$UNIT" >/dev/null <<EOF
[Unit]
Description=Aktien-KI Telegram Bot
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$PROJECT_DIR
$ENV_LINE
ExecStart=$PY -m stockai.cli bot
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

$SUDO systemctl daemon-reload || true
$SUDO systemctl enable --now stockai-bot.service || true

echo "Telegram-Bot-Dienst eingerichtet & gestartet."
echo "Status:   systemctl status stockai-bot --no-pager"
echo "Logs:     journalctl -u stockai-bot -f"
echo ""
echo "Schreib deinem Bot jetzt in Telegram z.B.:  /help   oder  /analyse NVDA"
