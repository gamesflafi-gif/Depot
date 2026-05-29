# Aktien-KI – schlankes Image für den Dauerbetrieb auf einem kleinen Server.
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Standard: täglicher Lauf in Endlosschleife (learn + sparplan + notify).
# Secrets via Umgebungsvariablen oder gemountete .env (siehe docker-compose.yml).
CMD ["bash", "deploy/docker_loop.sh"]
