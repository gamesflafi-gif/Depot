# Synapse — Wissenschafts-Entdeckungsmaschine

Selbst lernende Such- & Entdeckungs-Maschine über offene Forschungsdaten
(OpenAlex u.a.). Findet ähnliche Arbeiten, den Stand der Forschung und
**Verbindungen zwischen Feldern** – mit **Quellen belegt**. Läuft lokal auf dem
eigenen Server, keine teure Fremd-API, Daten bleiben bei dir.

➡️ Gesamtplan & Architektur: **`PROJECT_PLAN_SYNAPSE.md`**

## Status: Phase 0 (Fundament) ✅
Reproduzierbare, idempotente, wiederanlauffähige Datenpipeline in einen lokalen
Daten-Lake (DuckDB + Parquet). Offline testbar (Sample-Modus).

## Schnellstart (lokal/Server)
```bash
pip install -r requirements-synapse.txt

# Offline-Demo (ohne Netzwerk):
SYNAPSE_SOURCE=sample python -m synapse.cli ingest --limit 100 --export
python -m synapse.cli stats

# Echte Daten von OpenAlex (CC0). mailto = stabilere API:
export SYNAPSE_MAILTO="du@example.org"
python -m synapse.cli ingest --filter 'from_publication_date:2024-01-01' --limit 5000
python -m synapse.cli stats
```

## Befehle
- `doctor` – Umgebung & Bestand prüfen
- `ingest [--filter F] [--limit N] [--export]` – Werke laden (idempotent)
- `stats` – Bestand im Daten-Lake

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
