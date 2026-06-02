#!/usr/bin/env bash
# Täglicher Lauf: lernt dazu, erstellt den Sparplan und schickt ihn per Telegram.
# Wird vom Cron aufgerufen. Nutzt die venv und Live-Daten.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

PY="$PROJECT_DIR/.venv/bin/python"
[ -x "$PY" ] || PY="python3"

LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"
STAMP="$(date +%Y-%m-%d)"

{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S') ====="
  # 1) Aus echten Daten dazulernen (sammelt Sentiment + Ergebnis)
  "$PY" -m stockai.cli --source live learn || echo "learn fehlgeschlagen"
  # 2) Briefing mit Moves-Alerts per Telegram senden
  "$PY" -m stockai.cli --source live briefing --notify || echo "briefing fehlgeschlagen"
  # 3) Sparplan erstellen + per Telegram/Webhook benachrichtigen
  "$PY" -m stockai.cli --source live sparplan \
        --monthly "${STOCKAI_MONTHLY:-100}" \
        --report "$PROJECT_DIR/sparplan.md" --notify || echo "sparplan fehlgeschlagen"
  # 4) Depot prüfen – pro Nutzer, nur melden wenn die KI eine Position kritisch sieht
  "$PY" -m stockai.cli --source live depot --alert-only --all-users \
        || echo "depot-check fehlgeschlagen"
  # 5) Whale-Radar – nur bei starkem, auffälligem Volumen melden
  "$PY" -m stockai.cli --source live whales --alert-only || echo "whales fehlgeschlagen"
} >> "$LOG_DIR/daily-$STAMP.log" 2>&1
