# Synapse — Wissenschafts-Entdeckungsmaschine

Selbst lernende Such- & Entdeckungs-Maschine über offene Forschungsdaten
(OpenAlex u.a.). Findet ähnliche Arbeiten, den Stand der Forschung und
**Verbindungen zwischen Feldern** – mit **Quellen belegt**. Läuft lokal auf dem
eigenen Server, keine teure Fremd-API, Daten bleiben bei dir.

➡️ Gesamtplan & Architektur: **`PROJECT_PLAN_SYNAPSE.md`**

## Status: Fundament ✅ · Suche ✅ · Web ✅ · Gehirn ✅ · Verbindungen ✅ · Assistent ✅ · Kollab-Forschung ✅
Reproduzierbare, idempotente, wiederanlauffähige Datenpipeline in einen lokalen
Daten-Lake (DuckDB + Parquet). Offline testbar (Sample-Modus).

## Schnellstart (Ubuntu 24.04 / Server)
Ubuntu blockiert `pip` systemweit (PEP 668) und kennt nur `python3`. Darum eine
**virtuelle Umgebung** nutzen – das Setup-Skript erledigt das:
```bash
bash deploy/synapse/setup.sh        # legt .venv an + installiert alles

# Offline-Demo (ohne Netzwerk):
SYNAPSE_SOURCE=sample .venv/bin/python -m synapse.cli ingest --limit 100 --export
.venv/bin/python -m synapse.cli stats

# Echte Daten von OpenAlex (CC0). mailto = stabilere API:
export SYNAPSE_MAILTO="du@example.org"
.venv/bin/python -m synapse.cli ingest --filter 'from_publication_date:2024-01-01' --limit 5000
.venv/bin/python -m synapse.cli stats
```
> Hinweis: immer `.venv/bin/python` (nicht `python`/`pip` direkt) verwenden.

### Echter Start-Korpus (Fokusfelder) — ein Befehl
Lädt kuratiert hochwertige Arbeiten aus ~10 Themenfeldern (passend zu den
Startseiten-Beispielen) und baut den Index — RAM-schonend für 8 GB:
```bash
SYNAPSE_MAILTO="du@example.org" bash deploy/synapse/load_corpus.sh
# Stellschrauben: PER_THEME=2500  SINCE=2015  MIN_CIT=0
```
Manuell/feiner steuerbar:
```bash
.venv/bin/python -m synapse.cli corpus --per-theme 2500 --since 2015 --build-index
```
Themenfelder erweitern: `synapse/corpus.py` → `THEMES`. Der Lauf ist **idempotent**
(keine Duplikate) und **robust** (ein Feld mit Fehler stoppt den Rest nicht).

**Aktuell halten (automatisch):** wöchentlicher Refresh (Korpus + Index + Gehirn):
```bash
sudo cp deploy/synapse/refresh.{service,timer} /etc/systemd/system/
sudo systemctl enable --now synapse-refresh.timer
```

## Semantische Suche (Phase 1)
```bash
# Index bauen (lokale Embeddings; echtes Modell via fastembed, sonst Offline-Hash):
.venv/bin/python -m synapse.cli index                 # --embedder auto|fastembed|hash
# Suchen – Idee in Worten beschreiben:
.venv/bin/python -m synapse.cli search "neural network for protein folding" --k 10
```

## Befehle
- `doctor` – Umgebung & Bestand prüfen
- `ingest [--filter F] [--limit N] [--export]` – Werke laden (idempotent)
- `stats` – Bestand im Daten-Lake
- `index [--embedder auto|fastembed|hash]` – semantischen Index bauen
- `search "FRAGE" [--k N]` – semantische Suche (hybrid: Vektor + Stichwort)
- `serve [--host H] [--port P]` – Web-Oberfläche im Browser starten
- `brain` – Ranking-Gehirn aus Klick-Feedback trainieren (Phase 2)
- `connections WORK_ID` – verwandte Arbeiten + **Feld-Brücken** zu einem Werk
- `ask "FRAGE"` – Forschungs-Assistent: Einordnung mit Quellen
- `submit DOI` – eigene **belegte** Arbeit per DOI beitragen (wird geprüft)
- `project list|new|show` – Forschungs-Projekte verwalten

## Kollaborative Forschung (Projekte) — `/projekte`
Nutzer legen einen **Forschungsbereich** an (z.B. „Schlafstörungen") und teilen
**Ergebnisse & Zwischenstände**; andere bauen darauf auf. Jeder Beitrag trägt
eine **Vertrauens-Stufe**: geprüft (DOI), preprint (Daten-Link) oder community
(unbestätigt). Ungeprüftes wird **nie** mit der geprüften Literatur vermischt.
Mit Melde-/Moderationsfunktion (Owner-Token), sensiblen-Themen-Hinweis und
Disclaimer. Vollständiges Konzept inkl. aller Eventualitäten:
**`SYNAPSE_COLLAB_DESIGN.md`**.

## Eigene Forschung beitragen (nur belegt)
Über die DOI lässt sich eine **offiziell registrierte** Arbeit aufnehmen: Synapse
prüft sie bei **OpenAlex/Crossref** und nimmt sie nur auf, wenn sie dort existiert
(sonst Ablehnung). So kommt **nichts Ungeprüftes** in den Bestand. Im Web unter
„＋ Eigene Forschung beitragen". Der Eintrag wird **inkrementell** indiziert.

## Forschungs-Assistent (Phase 3)
Im Web ist die Suche jetzt ein **Assistent**: Du stellst eine Frage und bekommst
**direkt eine faktenbasierte Einordnung** statt nur einer Liste:
- *Gibt es das?* – Anzahl weltweit (live von OpenAlex) + im Bestand
- *Was gibt es?* – Hauptthemen, einflussreichste & neueste Arbeiten
- *Aktiv oder reif?* – Trend
- *Brücken* in andere Felder

Bewusst **ohne großes Sprachmodell** (schnell, kostenlos, **keine Halluzination** –
alles aus echten Daten + Quellen). CLI: `ask "Gibt es Forschung zu Schlaf und Gedächtnis?"`

## Verbindungs-Entdeckung (das Alleinstellungsmerkmal)
Im Web hat jeder Treffer einen **„↔ Verbindungen"**-Button: er zeigt verwandte
Arbeiten und markiert **Brücken** (semantisch nah, aber aus einem **anderen
Forschungsfeld**) – so findet man interdisziplinäre Anknüpfungspunkte, die eine
normale Suche nicht zeigt. Ohne Neu-Indizieren (nutzt vorhandene Vektoren).

## Themen-Bestand & Mehrsprachigkeit (wichtig für gute Treffer)
- Das Embedding-Modell ist **mehrsprachig** (Deutsch/Englisch …).
- Gute Treffer brauchen einen **themenrelevanten Bestand**. Ein breiter „meist-
  zitiert"-Pull liefert vor allem Methodik-Klassiker. Besser **gezielt** laden:
  ```bash
  .venv/bin/python -m synapse.cli ingest --filter 'default.search:malaria' --limit 5000
  .venv/bin/python -m synapse.cli ingest --filter 'default.search:cancer immunotherapy' --limit 5000
  .venv/bin/python -m synapse.cli index
  ```
- Bei wenig RAM den Index in kleineren Häppchen bauen: `index --batch 32`.

## Lernendes Ranking-Gehirn (Phase 2)
Das Ranking kombiniert mehrere Signale (semantische Nähe, Stichwort, Zitationen,
Aktualität). Anfangs mit sinnvollen Cold-Start-Gewichten; sobald genug Klicks
gesammelt sind, lernt das Gehirn die Gewichte aus echtem Feedback neu:
```bash
.venv/bin/python -m synapse.cli brain     # justiert Gewichte aus Klicks (ab ~15 Klicks)
```
Je mehr genutzt wird, desto besser das Ranking – der eigentliche Burggraben.
Sinnvoll wöchentlich per Cron aufrufen.

## Web-Oberfläche (Phase 1.5)
```bash
.venv/bin/python -m synapse.cli serve --host 0.0.0.0 --port 8000
# Browser: http://DEINE-SERVER-IP:8000
```
Suchfeld + Trefferliste mit Quellen (DOI-Links). **Klicks werden protokolliert** –
das ist die Datengrundlage fürs lernende Ranking-„Gehirn" (Phase 2).
Dauerbetrieb als Dienst: `deploy/synapse/web.service` (siehe Datei).

## Server-Härtung (Sicherheit)
```bash
bash deploy/synapse/harden.sh   # Firewall, fail2ban, Auto-Updates, SSH-Härtung
```
**Wichtig:** Vor der SSH-Härtung einen SSH-Key hinterlegen (sonst Aussperr-Gefahr).

### Konten-Sicherheit (eingebaut)
- **Passwörter**: scrypt-Hash + Salt (nie im Klartext); Richtlinie min. 10 Zeichen,
  keine Allerwelts-Passwörter, nicht = Nutzername.
- **Brute-Force-Schutz**: Login-Fehlversuche werden je Konto **und** je IP gezählt;
  nach zu vielen folgt eine kurze Sperre (Lockout).
- **Timing-sicher**: Login verrät über die Antwortzeit nicht, ob ein Konto existiert.
- **Sitzungen**: in der DB liegt nur der Token-*Hash*; Passwortwechsel meldet alle
  anderen Geräte ab.
- **Security-Header** auf jeder Antwort (CSP, X-Frame-Options, nosniff, Referrer-Policy).
- **HTTPS**: sobald hinter TLS betrieben, `SYNAPSE_HTTPS=1` setzen → `Secure`-Cookies
  + HSTS. Empfohlen: Reverse-Proxy (Caddy/Nginx) mit Let's-Encrypt vor `127.0.0.1:8000`.

### Launch-Härtung (Betrieb)
```bash
# 1) HTTPS + Domain (Caddy, automatisch Let's Encrypt; setzt SYNAPSE_HTTPS=1)
sudo bash deploy/synapse/install_https.sh DEINE-DOMAIN.de

# 2) Backups (täglich 03:30) + Restore jederzeit testbar
sudo cp deploy/synapse/backup.{service,timer} /etc/systemd/system/
sudo systemctl enable --now synapse-backup.timer
bash deploy/synapse/restore.sh <snapshot>        # Restore (regelmäßig testen!)

# 3) Watchdog (Health alle 5 Min, optional Telegram-Alarm) + Wartung (04:00)
sudo cp deploy/synapse/watchdog.{service,timer} /etc/systemd/system/
sudo cp deploy/synapse/maintenance.{service,timer} /etc/systemd/system/
sudo systemctl enable --now synapse-watchdog.timer synapse-maintenance.timer

# 4) Vor jedem Release: Schwachstellen-/Geheimnis-Scan + Selbstcheck
bash deploy/synapse/security_scan.sh
python -m synapse.cli security
```
- **Rate-Limiting**: schreibende Anfragen sind je IP gedrosselt (Spam-/Missbrauchs-Schutz),
  Anfragegröße begrenzt.
- **Rechtliches**: `/impressum`, `/datenschutz`, `/nutzungsbedingungen` sind eingebaut
  (Vorlagen — Platzhalter `[[…]]` vor Launch füllen und fachkundig prüfen lassen).
- **Status/Monitoring**: `GET /api/status` liefert Bestand/Index/HTTPS-Status für den Watchdog.

## Nächste Phasen (siehe Plan)
- **Phase 1:** vorberechnete Embeddings (SPECTER2) → Qdrant-Index → semantische
  Hybrid-Suche + API + Mini-Frontend.
- **Phase 2:** lernendes Ranking-„Gehirn" (Feedback-Loop, Learning-to-Rank).
- **Phase 3:** Verbindungs-Entdeckung + belegte Zusammenfassungen (lokales LLM, strenges RAG).
- **Phase 4:** Konten, Tarife, Public API, Launch.

_Keine medizinische/rechtliche Beratung – nur Information mit Quellen._
