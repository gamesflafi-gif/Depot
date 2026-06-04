#!/usr/bin/env bash
# Synapse-Setup für Ubuntu 24.04: virtuelle Umgebung anlegen + Abhängigkeiten.
# Umgeht den PEP-668-Block ("externally-managed") sauber per venv.
# Aufruf:  bash deploy/synapse/setup.sh
set -u

cd "$(dirname "$0")/../.." || exit 1     # ins Repo-Wurzelverzeichnis
echo "== Synapse Setup (venv) =="

# python3-venv sicherstellen (falls root)
if ! python3 -c "import venv" >/dev/null 2>&1; then
  (sudo apt-get update -y && sudo apt-get install -y python3-venv) \
    || apt-get install -y python3-venv || true
fi

# venv anlegen (falls noch nicht vorhanden) und Abhängigkeiten installieren
if [ ! -d .venv ]; then
  python3 -m venv .venv || { echo "venv-Erstellung fehlgeschlagen"; exit 1; }
fi
.venv/bin/pip install --upgrade pip -q || true
.venv/bin/pip install -r requirements-synapse.txt

echo
echo "Fertig. So nutzt du Synapse (immer .venv/bin/python):"
echo "  SYNAPSE_SOURCE=sample .venv/bin/python -m synapse.cli ingest --limit 100 --export"
echo "  .venv/bin/python -m synapse.cli stats"
echo "  .venv/bin/python -m synapse.cli doctor"
