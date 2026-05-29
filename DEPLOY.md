# 🚀 Dauerbetrieb auf einem Mini-Server (≈3–6 €/Monat)

So läuft die Aktien-KI rund um die Uhr, lädt **echte** Kurse + News, lernt täglich
dazu und schickt dir den aktualisierten Sparplan per **Telegram**. Auf einem
eigenen Server gibt es **keine Netzwerk-Sperre** – Yahoo Finance, News und
Telegram funktionieren direkt.

## 1. Server mieten
Ein kleiner Linux-VPS reicht völlig (1 vCPU, 1–2 GB RAM, Ubuntu 24.04). Beispiele:
- **Hetzner** CX22 / CAX11 (ARM) – ca. 3–5 €/Monat
- **Netcup**, **Contabo**, **DigitalOcean**, **Hetzner** … – je ~4–6 €/Monat

Beim Erstellen **Ubuntu 24.04** wählen und deinen SSH-Schlüssel (oder Passwort)
hinterlegen. Du bekommst eine IP-Adresse.

## 2. Verbinden
Vom PC:  `ssh root@DEINE-SERVER-IP`
Vom Handy: App wie **Termius** (iOS/Android) installieren und dort verbinden.

## 3. Projekt holen und einrichten
```bash
apt update && apt install -y git
git clone https://github.com/gamesflafi-gif/Depot.git
cd Depot
bash deploy/install.sh
```
Das Skript installiert Python, eine virtuelle Umgebung, alle Abhängigkeiten und
legt eine `.env` aus der Vorlage an.

## 4. Telegram-Zugang eintragen
```bash
nano .env
```
Dort eintragen (Token von **@BotFather**, Chat-ID von **@userinfobot**):
```ini
STOCKAI_TELEGRAM_TOKEN=123456:ABC…
STOCKAI_TELEGRAM_CHAT_ID=987654321
```
Speichern mit `Strg+O`, `Enter`, `Strg+X`.

Optional in `config.yaml` echte ETFs/Aktien eintragen (z. B. `VWCE.DE`,
`EUNL.DE`, `SXR8.DE`) und `data_source: live` setzen.

## 5. Testlauf
```bash
.venv/bin/python -m stockai.cli doctor          # Datenquellen & Telegram prüfen
.venv/bin/python -m stockai.cli --source live train
.venv/bin/python -m stockai.cli --source live sparplan --monthly 100 --notify
```
Wenn die Telegram-Nachricht ankommt: 🎉 alles läuft.

## 6. Automatisch täglich laufen lassen
```bash
bash deploy/install_cron.sh
```
Richtet einen Cron-Job ein (täglich 08:15): erst `learn` (dazulernen), dann
`sparplan --notify`. Logs liegen in `logs/`.

---

## Alternative: Docker (ein Befehl)
```bash
# .env mit Telegram-Token/Chat-ID anlegen, dann:
docker compose up -d --build
```
Der Container lernt + benachrichtigt einmal pro Tag von selbst (Intervall via
`STOCKAI_INTERVAL_SECONDS`). Daten/Modelle bleiben in `./data` erhalten.

---

## Updates einspielen
```bash
cd Depot && git pull && .venv/bin/pip install -r requirements.txt
```

## Sicherheit
- `.env` enthält Geheimnisse – niemals committen/teilen (ist per `.gitignore`
  geschützt). Token bei Verdacht im **@BotFather** mit `/revoke` neu erzeugen.
- Server aktuell halten: `apt update && apt upgrade -y`.

> ⚠️ Keine Anlageberatung. Die KI liefert einen kleinen, ehrlich gemessenen
> Vorteil – keine garantierten Gewinne. Investiere nur Geld, dessen Verlust du
> verkraften kannst.
