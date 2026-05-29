#!/usr/bin/env bash
# Richtet einen täglichen Cron-Job (08:15 Uhr) für run_daily.sh ein.
# Aufruf:  bash deploy/install_cron.sh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$PROJECT_DIR/deploy/run_daily.sh"
chmod +x "$RUN"

LINE="15 8 * * * $RUN"
# bestehende Einträge für dieses Skript entfernen, dann neu setzen
( crontab -l 2>/dev/null | grep -v -F "$RUN" ; echo "$LINE" ) | crontab -

echo "Cron-Job eingerichtet:"
echo "  $LINE"
echo "Aktuelle Crontab:"
crontab -l
