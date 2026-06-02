#!/usr/bin/env bash
# Prüft Live-Kurse auf starke Bewegungen und meldet sie per Telegram.
# Für häufige Ausführung (z.B. alle 15 Min via Cron) gedacht.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
PY="$PROJECT_DIR/.venv/bin/python"; [ -x "$PY" ] || PY="python3"
mkdir -p logs
LOG="logs/alerts-$(date +%Y-%m-%d).log"
# 1) allgemeine starke Bewegungen
"$PY" -m stockai.cli alerts --notify >> "$LOG" 2>&1
# 2) eigene bedingte Alerts (Crossing-Logik, nur bei frisch erreichtem Trigger)
"$PY" -m stockai.cli watch check --notify >> "$LOG" 2>&1
