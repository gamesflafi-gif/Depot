#!/usr/bin/env bash
# Wöchentlicher Überblick: Top 5 Chancen und Top 5 Risiken.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
PY="$PROJECT_DIR/.venv/bin/python"; [ -x "$PY" ] || PY="python3"
mkdir -p logs
{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S') weekly ====="
  # Selbst-Weiterentwicklung: bestes Modell neu wählen & tunen
  "$PY" -m stockai.cli evolve || echo "evolve fehlgeschlagen"
  # Live-Track-Record (echte Prognosen vs. Ergebnis) per Telegram
  "$PY" -m stockai.cli track --notify || echo "track fehlgeschlagen"
  # Selbstcheck: meldet automatisch, wenn die KI schlechter wird
  "$PY" -m stockai.cli health --notify || echo "health fehlgeschlagen"
  # Wochen-Top-5 in beide Richtungen
  "$PY" -m stockai.cli top --n 5 --notify || echo "weekly fehlgeschlagen"
} >> "logs/weekly-$(date +%Y-%m-%d).log" 2>&1
