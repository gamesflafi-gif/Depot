#!/usr/bin/env bash
# Synapse – periodische Aktualisierung: neue Arbeiten nachladen, Index neu
# bauen und das Ranking-„Gehirn" aus gesammelten Klicks nachtrainieren.
# Wird von refresh.timer (wöchentlich) ausgelöst.
set -uo pipefail

PY="${PY:-.venv/bin/python}"
[[ -x "$PY" ]] || PY="python3"

PER_THEME="${PER_THEME:-2500}"
SINCE="${SINCE:-2015}"

echo "[refresh] Korpus aktualisieren (idempotent – keine Duplikate) …"
"$PY" -m synapse.cli corpus --per-theme "$PER_THEME" --since "$SINCE" || true

echo "[refresh] Index neu bauen …"
"$PY" -m synapse.cli index --embedder auto --batch 64 --max-chars 1200 || true

echo "[refresh] Ranking-Gehirn aus Klick-Feedback nachtrainieren …"
"$PY" -m synapse.cli brain || true

echo "[refresh] Dienst neu starten, damit der neue Index geladen wird …"
systemctl restart synapse-web 2>/dev/null || true
echo "[refresh] fertig."
