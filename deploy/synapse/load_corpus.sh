#!/usr/bin/env bash
# Synapse – Start-Korpus laden (echte Daten aus OpenAlex) + Index bauen.
# Auf dem VPS ausführen (nicht in der Cloud-Session – die hat keinen Netzzugang).
#
#   SYNAPSE_MAILTO=du@example.de bash deploy/synapse/load_corpus.sh
#
# Speicher-schonend für 8 GB RAM: Embeddings laufen mit parallel=1 + Batch 64.
set -euo pipefail

PY="${PY:-.venv/bin/python}"
[[ -x "$PY" ]] || PY="python3"

PER_THEME="${PER_THEME:-2500}"     # Arbeiten je Themenfeld (~10 Felder)
SINCE="${SINCE:-2015}"             # ab Publikationsjahr
MIN_CIT="${MIN_CIT:-0}"            # Mindest-Zitationen (0 = aus)

if [[ -z "${SYNAPSE_MAILTO:-}" ]]; then
  echo "Tipp: SYNAPSE_MAILTO=deine@mail setzen → stabilere/schnellere OpenAlex-API."
fi

echo "[1/3] Lade kuratierten Korpus (je Feld bis ${PER_THEME}, ab ${SINCE}) …"
"$PY" -m synapse.cli corpus --per-theme "$PER_THEME" --since "$SINCE" \
      --min-citations "$MIN_CIT"

echo "[2/3] Baue semantischen Index (CPU, RAM-schonend) …"
"$PY" -m synapse.cli index --embedder auto --batch 64 --max-chars 1200

echo "[3/3] Bestand:"
"$PY" -m synapse.cli stats

echo
echo "Fertig. Dienst ggf. neu laden:  sudo systemctl restart synapse-web"
echo "Erweitern später: PER_THEME höher setzen oder Themen in synapse/corpus.py ergänzen."
