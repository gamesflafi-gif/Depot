#!/usr/bin/env bash
# Kurzes Update (nur Briefing mit Moves-Alerts) – z.B. vor Börsenschluss.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
PY="$PROJECT_DIR/.venv/bin/python"; [ -x "$PY" ] || PY="python3"
mkdir -p logs
{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S') briefing ====="
  "$PY" -m stockai.cli briefing --notify || echo "briefing fehlgeschlagen"
} >> "logs/briefing-$(date +%Y-%m-%d).log" 2>&1
