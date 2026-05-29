#!/usr/bin/env bash
# Wöchentlicher Überblick: Top 5 Chancen und Top 5 Risiken.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
PY="$PROJECT_DIR/.venv/bin/python"; [ -x "$PY" ] || PY="python3"
mkdir -p logs
{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S') weekly-top ====="
  "$PY" -m stockai.cli top --n 5 --notify || echo "weekly fehlgeschlagen"
} >> "logs/weekly-$(date +%Y-%m-%d).log" 2>&1
