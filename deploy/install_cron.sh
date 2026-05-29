#!/usr/bin/env bash
# Richtet einen täglichen Cron-Job (08:15 Uhr) für run_daily.sh ein.
# Installiert cron bei Bedarf und startet den Dienst.
# Aufruf:  bash deploy/install_cron.sh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$PROJECT_DIR/deploy/run_daily.sh"
chmod +x "$RUN"

# cron sicherstellen (schlanke Images haben es teils nicht)
if ! command -v crontab >/dev/null 2>&1; then
  SUDO="$(command -v sudo || true)"
  $SUDO apt-get update -y && $SUDO apt-get install -y cron
fi
# Dienst starten (in Containern ohne systemd Fehler ignorieren)
(systemctl enable --now cron 2>/dev/null || service cron start 2>/dev/null || true)

LINE="15 8 * * * $RUN"
# bestehende Einträge für dieses Skript entfernen, dann neu setzen
( crontab -l 2>/dev/null | grep -v -F "$RUN" ; echo "$LINE" ) | crontab -

echo "Cron-Job eingerichtet:"
echo "  $LINE"
echo "Aktuelle Crontab:"
crontab -l
