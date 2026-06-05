#!/usr/bin/env bash
# Synapse – Health-Watchdog. Prüft /health, startet den Dienst bei Ausfall neu
# und schickt (optional) einen Telegram-Alarm.
#
# Telegram-Alarm aktivieren (optional):
#   export TG_TOKEN=123:abc   export TG_CHAT=987654
set -uo pipefail

URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"
TG_TOKEN="${TG_TOKEN:-}"
TG_CHAT="${TG_CHAT:-}"

notify() {
  local msg="$1"
  echo "[watchdog] $msg"
  if [[ -n "$TG_TOKEN" && -n "$TG_CHAT" ]]; then
    curl -fsS --max-time 10 \
      "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
      -d "chat_id=${TG_CHAT}" -d "text=Synapse: ${msg}" >/dev/null 2>&1 || true
  fi
}

if curl -fsS --max-time 8 "$URL" >/dev/null 2>&1; then
  exit 0                                   # alles gesund
fi

notify "Health-Check fehlgeschlagen – versuche Neustart."
systemctl restart synapse-web 2>/dev/null || true
sleep 5

if curl -fsS --max-time 8 "$URL" >/dev/null 2>&1; then
  notify "Dienst nach Neustart wieder erreichbar."
  exit 0
fi
notify "ACHTUNG: Dienst weiterhin nicht erreichbar – bitte prüfen!"
exit 1
