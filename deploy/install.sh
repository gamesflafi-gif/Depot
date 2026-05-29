#!/usr/bin/env bash
# Einmalige Einrichtung der Aktien-KI auf einem frischen Linux-Server (Ubuntu/Debian).
# Aufruf:  bash deploy/install.sh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

echo "[1/4] System-Pakete (python venv) installieren …"
# sudo nur verwenden, wenn vorhanden (als root nicht nötig)
SUDO="$(command -v sudo || true)"
if command -v apt-get >/dev/null 2>&1; then
  $SUDO apt-get update -y
  $SUDO apt-get install -y python3 python3-venv python3-pip
fi

echo "[2/4] Virtuelle Umgebung anlegen …"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

echo "[3/4] Abhängigkeiten installieren …"
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

echo "[4/4] .env vorbereiten …"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "    -> .env aus Vorlage erstellt. Bitte Telegram-Token & Chat-ID eintragen:"
  echo "       nano $PROJECT_DIR/.env"
fi

echo ""
echo "Fertig. Schnelltest:"
echo "  cd $PROJECT_DIR && .venv/bin/python -m stockai.cli doctor"
echo ""
echo "Für echten Live-Betrieb in config.yaml 'data_source: live' setzen"
echo "(oder im Cron-Job --source live nutzen) und den Cron einrichten:"
echo "  bash deploy/install_cron.sh"
