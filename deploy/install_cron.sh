#!/usr/bin/env bash
# Richtet die Cron-Jobs ein:
#   * morgens 07:00 UTC  -> voller Lauf (lernen + Briefing + Sparplan)
#   * 19:30 UTC          -> kurzes Briefing vor US-Börsenschluss
#   * sonntags 17:00 UTC -> wöchentlicher Top-5-Überblick
# Installiert cron bei Bedarf und startet den Dienst.
# Aufruf:  bash deploy/install_cron.sh
set -u  # bewusst KEIN -e/pipefail: leere Crontab/grep dürfen nicht abbrechen

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DAILY="$PROJECT_DIR/deploy/run_daily.sh"
BRIEF="$PROJECT_DIR/deploy/run_briefing.sh"
WEEKLY="$PROJECT_DIR/deploy/run_weekly.sh"
ALERTS="$PROJECT_DIR/deploy/run_alerts.sh"
chmod +x "$PROJECT_DIR"/deploy/*.sh 2>/dev/null || true

# cron sicherstellen (schlanke Images haben es teils nicht)
if ! command -v crontab >/dev/null 2>&1; then
  SUDO="$(command -v sudo || true)"
  $SUDO apt-get update -y; $SUDO apt-get install -y cron
fi
systemctl enable --now cron 2>/dev/null || service cron start 2>/dev/null || true

# bestehende Einträge dieses Projekts entfernen, dann neu setzen
current="$(crontab -l 2>/dev/null | grep -v -F "$PROJECT_DIR/deploy/")"
printf '%s\n%s\n%s\n%s\n%s\n' "$current" \
  "0 7 * * *   $DAILY" \
  "30 19 * * * $BRIEF" \
  "0 17 * * 0  $WEEKLY" \
  "*/15 13-21 * * 1-5 $ALERTS" | grep -v '^$' | crontab -

echo "Cron-Jobs eingerichtet:"
echo "  07:00 UTC  täglich   -> run_daily.sh   (lernen + Briefing + Sparplan)"
echo "  19:30 UTC  täglich   -> run_briefing.sh (Update vor Börsenschluss)"
echo "  17:00 UTC  sonntags  -> run_weekly.sh   (Top-5 in beide Richtungen)"
echo "  alle 15Min Mo-Fr 13-21 UTC -> run_alerts.sh (Live-Alerts z. US-Handel)"
echo ""
echo "Aktuelle Crontab:"
crontab -l
