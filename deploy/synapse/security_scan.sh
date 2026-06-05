#!/usr/bin/env bash
# Synapse – Sicherheits-Scan: bekannte Schwachstellen in Abhängigkeiten
# (pip-audit) + einfacher Geheimnis-Scan im Repo. Vor jedem Release ausführen.
set -uo pipefail

PY="${PY:-.venv/bin/python}"
[[ -x "$PY" ]] || PY="python3"
rc=0

echo "== 1) Abhängigkeits-Scan (pip-audit) =="
if ! "$PY" -m pip_audit --version >/dev/null 2>&1; then
  echo "   pip-audit nicht installiert – installiere in venv …"
  "$PY" -m pip install --quiet pip-audit || { echo "   konnte pip-audit nicht installieren"; }
fi
if "$PY" -m pip_audit --version >/dev/null 2>&1; then
  "$PY" -m pip_audit -r requirements-synapse.txt || rc=1
else
  echo "   übersprungen (kein pip-audit)."
fi

echo
echo "== 2) Geheimnis-Scan (Heuristik) =="
# sucht offensichtliche Schlüssel/Passwörter im Code – data/ und venv ausgenommen
PATTERN='(api[_-]?key|secret|password|passwd|token|BEGIN (RSA|EC|OPENSSH) PRIVATE KEY)[[:space:]]*[:=]'
if command -v grep >/dev/null 2>&1; then
  hits=$(grep -rInE "$PATTERN" \
        --exclude-dir=.git --exclude-dir=.venv --exclude-dir=data \
        --exclude-dir=node_modules --exclude='*.lock' . \
        | grep -viE 'password_hash|passwort|password:.{0,3}(str|\")|placeholder|\[\[' || true)
  if [[ -n "$hits" ]]; then
    echo "   Mögliche Geheimnisse gefunden – bitte prüfen:"
    echo "$hits"
    rc=1
  else
    echo "   keine offensichtlichen Geheimnisse im Code gefunden."
  fi
fi

echo
echo "== 3) Betriebs-Selbstcheck =="
"$PY" -m synapse.cli security || true

echo
[[ $rc -eq 0 ]] && echo "Scan ohne kritische Funde." || echo "Scan meldete Funde (siehe oben)."
exit $rc
