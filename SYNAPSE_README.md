# Synapse — Wissenschafts-Entdeckungsmaschine

Selbst lernende Such- & Entdeckungs-Maschine über offene Forschungsdaten
(OpenAlex u.a.). Findet ähnliche Arbeiten, den Stand der Forschung und
**Verbindungen zwischen Feldern** – mit **Quellen belegt**. Läuft lokal auf dem
eigenen Server, keine teure Fremd-API, Daten bleiben bei dir.

➡️ Gesamtplan & Architektur: **`PROJECT_PLAN_SYNAPSE.md`**

## Status: Phase 0 ✅ · Suche ✅ · Web ✅ · Gehirn ✅ · Verbindungs-Entdeckung ✅
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

## Nächste Phasen (siehe Plan)
- **Phase 1:** vorberechnete Embeddings (SPECTER2) → Qdrant-Index → semantische
  Hybrid-Suche + API + Mini-Frontend.
- **Phase 2:** lernendes Ranking-„Gehirn" (Feedback-Loop, Learning-to-Rank).
- **Phase 3:** Verbindungs-Entdeckung + belegte Zusammenfassungen (lokales LLM, strenges RAG).
- **Phase 4:** Konten, Tarife, Public API, Launch.

_Keine medizinische/rechtliche Beratung – nur Information mit Quellen._
