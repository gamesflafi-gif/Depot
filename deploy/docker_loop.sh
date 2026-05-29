#!/usr/bin/env bash
# Einfache Tages-Schleife für den Docker-Betrieb: einmal pro Tag ausführen.
set -euo pipefail
cd /app

INTERVAL="${STOCKAI_INTERVAL_SECONDS:-86400}"  # Standard: 24h
while true; do
  echo "===== $(date '+%Y-%m-%d %H:%M:%S') Lauf ====="
  python -m stockai.cli --source live learn || echo "learn fehlgeschlagen"
  python -m stockai.cli --source live sparplan \
      --monthly "${STOCKAI_MONTHLY:-100}" --notify || echo "sparplan fehlgeschlagen"
  echo "Schlafe ${INTERVAL}s …"
  sleep "$INTERVAL"
done
