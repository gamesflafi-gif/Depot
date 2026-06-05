#!/usr/bin/env bash
# Synapse – HTTPS einrichten (Caddy + automatisches Let's Encrypt).
# Voraussetzung: Domain-A-Record zeigt auf diese Server-IP; Ports 80+443 frei.
set -euo pipefail

DOMAIN="${1:-}"
if [[ -z "$DOMAIN" ]]; then
  echo "Aufruf: sudo bash deploy/synapse/install_https.sh DEINE-DOMAIN.de"
  exit 1
fi

echo "[1/5] Caddy installieren (offizielles Repo) …"
if ! command -v caddy >/dev/null 2>&1; then
  apt-get update
  apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  apt-get update
  apt-get install -y caddy
fi

echo "[2/5] Caddyfile übernehmen (Domain = $DOMAIN) …"
mkdir -p /var/log/caddy
sed "s/DEINE-DOMAIN.de/${DOMAIN}/g" "$(dirname "$0")/Caddyfile" > /etc/caddy/Caddyfile

echo "[3/5] Synapse-Dienst auf HTTPS-Modus setzen (Secure-Cookies + HSTS) …"
mkdir -p /etc/systemd/system/synapse-web.service.d
cat > /etc/systemd/system/synapse-web.service.d/https.conf <<'EOF'
[Service]
Environment=SYNAPSE_HTTPS=1
EOF
systemctl daemon-reload
systemctl restart synapse-web 2>/dev/null || true

echo "[4/5] Firewall: nur 80/443/SSH öffnen …"
if command -v ufw >/dev/null 2>&1; then
  ufw allow 80/tcp  || true
  ufw allow 443/tcp || true
fi

echo "[5/5] Caddy starten/neu laden …"
systemctl enable --now caddy
systemctl reload caddy || systemctl restart caddy

echo
echo "Fertig. Synapse ist jetzt unter https://${DOMAIN} erreichbar."
echo "Synapse selbst lauscht nur lokal (127.0.0.1:8000) – nicht direkt aus dem Netz."
