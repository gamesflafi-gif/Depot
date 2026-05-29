#!/usr/bin/env bash
# SessionStart-Hook: richtet die Umgebung für die Aktien-KI ein.
# Installiert die Abhängigkeiten in den aktiven Python-Interpreter, damit
# Tests, CLI und Dashboard in Web-Sessions sofort lauffähig sind.
set -euo pipefail

cd "$(dirname "$0")/../.."

echo "[stockai setup] Installiere Abhängigkeiten …"
python -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
python -m pip install --quiet -r requirements.txt pytest >/dev/null 2>&1 || {
  echo "[stockai setup] Warnung: Installation teilweise fehlgeschlagen."
}
echo "[stockai setup] Fertig. Schnellstart: python -m stockai.cli analyze"
