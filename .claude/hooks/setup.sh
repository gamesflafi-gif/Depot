#!/usr/bin/env bash
# SessionStart-Hook: richtet die Umgebung für Gridiron (NFL-Scouting) ein.
# Installiert die Abhängigkeiten in den aktiven Python-Interpreter, damit
# Tests und CLI in Web-Sessions sofort lauffähig sind.
set -euo pipefail

cd "$(dirname "$0")/../.."

echo "[gridiron setup] Installiere Abhängigkeiten …"
python -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
python -m pip install --quiet -r requirements.txt pytest >/dev/null 2>&1 || {
  echo "[gridiron setup] Warnung: Installation teilweise fehlgeschlagen."
}
echo "[gridiron setup] Fertig. Schnellstart: GRIDIRON_SOURCE=sample python -m gridiron.cli ingest"
