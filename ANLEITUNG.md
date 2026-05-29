# 📘 Komplette Anleitung: Server kaufen & die Aktien‑KI laufen lassen

Diese Anleitung führt dich **von Null** (kein Server, kein Vorwissen) bis zu einer
KI, die täglich von selbst läuft, echte Kurse + News analysiert und dir den
Sparplan **per Telegram** schickt. Schritt für Schritt, alles zum Kopieren.

> ⏱️ Dauer: ca. 30–45 Minuten · 💶 Kosten: ca. 4–6 €/Monat
> ⚠️ Keine Anlageberatung. Investiere nur Geld, dessen Verlust du verkraftest.

---

## Übersicht – was du tun wirst
1. Telegram‑Bot erstellen (Benachrichtigungen)
2. Server mieten (kleiner Linux‑VPS)
3. Mit dem Server verbinden (Handy oder PC)
4. Projekt installieren (ein Skript)
5. Zugangsdaten eintragen (`.env`)
6. Aktien/ETFs auswählen
7. Testlauf
8. Automatik einschalten (täglich)
9. Pflege, Kosten, Sicherheit, Problemlösung

---

## Schritt 1 – Telegram‑Bot erstellen (5 Min)
Damit dir die KI Nachrichten schicken kann.

1. Öffne **Telegram** und suche den Kontakt **@BotFather**.
2. Schreibe `/newbot`, vergib einen Namen und einen Benutzernamen (endet auf `bot`).
3. Du bekommst einen **Token** wie `123456789:AAH...` → **notieren**.
4. Suche **@userinfobot**, starte ihn → er zeigt dir deine **Chat‑ID** (eine Zahl)
   → **notieren**.

Diese zwei Werte (Token + Chat‑ID) brauchst du in Schritt 5.

---

## Schritt 2 – Server mieten (10 Min)
Ein kleiner Linux‑Server (VPS) genügt völlig.

**Empfehlung (günstig & einfach): Hetzner Cloud**
1. Konto erstellen auf <https://console.hetzner.com> ( E‑Mail bestätigen).
2. **New Project** → Name z. B. „AktienKI" → **Add Server**.
3. Auswählen:
   - **Location:** Nürnberg/Falkenstein (Deutschland)
   - **Image:** **Ubuntu 24.04**
   - **Type:** kleinster Shared‑vCPU (z. B. **CX22** oder ARM **CAX11**) – reicht
   - **Authentifizierung:** Passwort (einfacher) **oder** SSH‑Key (sicherer)
4. **Create & Buy now.** Du bekommst eine **IP‑Adresse** (z. B. `203.0.113.45`)
   und – bei Passwort – ein **root‑Passwort** per Mail/Konsole.

Andere günstige Anbieter gehen genauso: Netcup, Contabo, DigitalOcean, Ionos …

---

## Schritt 3 – Mit dem Server verbinden (5 Min)

**Vom Handy (empfohlen): App „Termius"** (kostenlos, iOS/Android)
1. Termius installieren → **New Host**.
2. **Hostname/IP:** deine Server‑IP · **Username:** `root` · **Password:** dein
   root‑Passwort (oder SSH‑Key).
3. Auf den Host tippen → du bist auf dem Server (schwarzes Terminal).

**Vom PC:** Terminal öffnen und `ssh root@DEINE-SERVER-IP` eingeben.

> Beim ersten Verbinden „yes" bestätigen.

---

## Schritt 4 – Projekt installieren (5 Min)
Tippe (oder kopiere) auf dem Server **Zeile für Zeile**:

```bash
apt update && apt install -y git
git clone https://github.com/gamesflafi-gif/Depot.git
cd Depot
bash deploy/install.sh
```

Das Skript installiert Python und alle Bausteine und legt eine Datei `.env` an.
Warte, bis „Fertig" erscheint.

---

## Schritt 5 – Zugangsdaten eintragen (3 Min)
Jetzt Telegram‑Token + Chat‑ID aus Schritt 1 eintragen:

```bash
nano .env
```
Ersetze die Platzhalter:
```ini
STOCKAI_TELEGRAM_TOKEN=123456789:AAH...      # dein Token
STOCKAI_TELEGRAM_CHAT_ID=987654321           # deine Chat-ID
```
Speichern: **Strg+O**, **Enter**, dann **Strg+X**.

> Optional mehr News: kostenlosen Key auf <https://newsapi.org> holen und als
> `STOCKAI_NEWSAPI_KEY=...` ebenfalls in die `.env` schreiben.

---

## Schritt 6 – Aktien & ETFs auswählen (optional, 5 Min)
Standardmäßig sind 24 US‑Aktien + Platzhalter‑ETFs hinterlegt. Für echte ETFs
(z. B. an Xetra) die Datei anpassen:

```bash
nano config.yaml
```
Beispiel für `etfs:` (echte Symbole):
```yaml
etfs:
  - VWCE.DE   # FTSE All-World
  - EUNL.DE   # MSCI World
  - SXR8.DE   # S&P 500
```
Aktien unter `tickers:` kannst du nach Belieben ergänzen/streichen
(Yahoo‑Finance‑Symbole, z. B. `SAP.DE`, `ASML`, `AAPL`). Speichern wie oben.

> `data_source` musst du **nicht** ändern – der tägliche Lauf nutzt automatisch
> Live‑Daten (`--source live`).

---

## Schritt 7 – Testlauf (2 Min)
```bash
.venv/bin/python -m stockai.cli doctor
```
Zeigt, ob Datenquellen erreichbar sind und Telegram erkannt wurde (auf einem
echten Server ist das Internet offen – sollte „erreichbar" und „Telegram" zeigen).

Dann ein echter Lauf:
```bash
.venv/bin/python -m stockai.cli --source live train
.venv/bin/python -m stockai.cli --source live sparplan --monthly 100 --notify
```
Kommt die **Telegram‑Nachricht** mit dem Sparplan an? 🎉 Dann läuft alles.

---

## Schritt 8 – Automatik einschalten (2 Min)
Damit es **täglich von selbst** läuft:
```bash
bash deploy/install_cron.sh
```
Das richtet einen Cron‑Job (täglich 08:15 Uhr) ein: erst dazulernen (`learn`),
dann Sparplan erstellen und per Telegram senden. Logs landen im Ordner `logs/`.

Prüfen, dass der Job steht:
```bash
crontab -l
```

**Fertig!** Der Server läuft jetzt rund um die Uhr und meldet sich täglich.

---

## Alternative: Docker (für Fortgeschrittene)
Statt Schritt 4–8:
```bash
apt update && apt install -y git docker.io docker-compose-v2
git clone https://github.com/gamesflafi-gif/Depot.git && cd Depot
cp .env.example .env && nano .env      # Telegram-Daten eintragen
docker compose up -d --build
```
Der Container lernt + benachrichtigt einmal pro Tag von selbst.

---

## Pflege & Betrieb
- **Updates holen:**
  ```bash
  cd Depot && git pull && .venv/bin/pip install -r requirements.txt
  ```
- **Letzten Lauf ansehen:** `cat logs/daily-*.log | tail -40`
- **Sparbetrag ändern:** in `deploy/run_daily.sh` die Zahl bei `--monthly` anpassen,
  oder `export STOCKAI_MONTHLY=200` in die `.env`.
- **Manuell jederzeit:** `.venv/bin/python -m stockai.cli --source live analyze`

## Kosten
- Server: ~4–6 €/Monat · Telegram/NewsAPI(Basis): kostenlos.
- Kündbar monatlich – Server im Anbieter‑Panel löschen.

## Sicherheit
- `.env` enthält Geheimnisse → niemals teilen/committen (ist geschützt).
  Token bei Verdacht im **@BotFather** mit `/revoke` neu erzeugen.
- Server aktuell halten: `apt update && apt upgrade -y`.
- Optional eine Firewall: `ufw allow OpenSSH && ufw enable`.

## Problemlösung
| Problem | Lösung |
|---|---|
| „command not found: python" | `.venv/bin/python` statt `python` nutzen |
| Keine Telegram‑Nachricht | `.venv/bin/python -m stockai.cli doctor` → Token/Chat‑ID prüfen |
| „Keine Trainingsdaten" | Internet/Netzwerk prüfen; Ticker‑Symbole korrekt? |
| Cron läuft nicht | `crontab -l` prüfen; Logs in `logs/` ansehen |
| SSH‑Verbindung bricht ab | Server‑IP korrekt? Anbieter‑Konsole nutzen |

---

> 📌 **Erinnerung:** Die KI liefert einen kleinen, ehrlich gemessenen Vorteil –
> keine garantierten Gewinne. ~55 % Trefferquote ist realistisch und gut.
> Triff Geld‑Entscheidungen selbst und auf eigenes Risiko.
