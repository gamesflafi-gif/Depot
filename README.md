# Gridiron — NFL-Scouting & Tendenz-Analyse

Lokales Analyse-System für **American Football (NFL)**, gebaut für **Coaches &
Analysten**. Aus echten Play-by-Play-Daten (frei, nflverse, 1999–heute)
entstehen **Scouting-Reports, Self-Scout, Tendenz-Analysen** und ein
trainiertes **Pass/Lauf-Vorhersagemodell** — alles lokal auf dem Server,
**kein GPU, keine bezahlte API**.

➡️ Gesamtplan, Datenlage & Monetarisierung: **`GRIDIRON_PLAN.md`**

## Status: Fundament ✅ · Daten-Lake ✅ · Tendenzen/Scouting ✅ · Modell ✅
Reproduzierbare, idempotente Pipeline in einen lokalen Daten-Lake (DuckDB).
Offline testbar (Sample-Modus, synthetische Plays).

## Schnellstart
```bash
python -m pip install -r requirements.txt        # duckdb, scikit-learn, …

# Offline-Demo (ohne Netzwerk, synthetische Plays):
GRIDIRON_SOURCE=sample python -m gridiron.cli ingest
python -m gridiron.cli stats

# Echte Daten (nflverse, läuft auf dem Server mit Internet):
python -m gridiron.cli ingest --seasons 2022 2023 2024
python -m gridiron.cli stats
```

## Scouting & Vorhersage
```bash
# Scouting-Report für ein Team (Tendenzen, Tells, Abweichung zur Liga):
python -m gridiron.cli scout KC --season 2024

# Pass/Lauf-Modell trainieren (CPU):
python -m gridiron.cli train

# Live-Vorhersage für eine konkrete Situation:
python -m gridiron.cli predict --team KC --down 3 --ydstogo 8 --yardline 65 --shotgun
```
Der Report zeigt u.a.: Pass/Run-Split vs. Liga, **Tells** (vorhersehbare
Situationen), Aufschlüsselung nach Down & Distanz und Feldzone, Lauf-/Pass-
Richtungen und Play-Action-Rate.

## Web-Oberfläche
```bash
python -m gridiron.cli serve --host 0.0.0.0 --port 8000
# Browser: http://SERVER-IP:8000
```
- **Scouting-Seite**: Team + Saison wählen → Report mit KPI-Karten, Tells,
  Down&Distanz-Balken (Team vs. Liga), Feldzonen, Richtungen.
- **Live-Vorhersage**: Situation eingeben → Pass/Lauf-Wahrscheinlichkeit +
  Vorhersehbarkeit.
- **Druck-Report** (`/report`): aufgeräumte, druck-/PDF-fertige Variante für die
  Coaching-Mappe (Browser → Drucken/„Als PDF speichern").

## Play-Simulator (Konzept × Coverage)
Eigener Plattform-Bereich: spiel ein **Offense-Konzept** (Four Verts, Mesh,
Smash, Screens, Inside/Outside Zone, Power …) gegen eine **Defensiv-Coverage**
(Cover 0–6, Tampa 2, Cover 2-Man) in einer konkreten Situation durch. Tausende
Monte-Carlo-Simulationen → Ertragsverteilung, Erfolgs-, Big-Play-, TD-,
Turnover-, Sack-Wahrscheinlichkeit und erwartetes EPA.
- **Berater**: „Beste Antwort auf Cover 3" und „Was stoppt dieses Konzept?".
- **Matchup-Matrix**: Heatmap jedes Konzept × jede Coverage (erwartetes EPA).
- Engine = echte Liga-Basisraten × kalibrierte Football-Matchup-Logik
  (`gridiron/simulator.py`), transparent und nachvollziehbar.

## Datenquelle
- **nflverse** Play-by-Play (Parquet je Saison) — frei, vollständig ab 1999.
  Enthält Down, Distanz, Feldposition, Play-Typ, EPA, Win-Probability,
  air_yards, Pass-/Lauf-Richtung u.v.m.
- Granulare Tracking-/Routen-Daten (Spielerpositionen) sind öffentlich nur als
  **NFL Big Data Bowl**-Teilmengen verfügbar → Routen-Modul ist als Phase 2
  geplant (siehe Plan), nicht flächendeckend für jeden Spielzug.

## Architektur (kurz)
- `gridiron/config.py` — Konfiguration (Datenpfad, Saisons, Quelle).
- `gridiron/storage.py` — DuckDB-Lake (Tabelle `plays`), idempotenter Upsert.
- `gridiron/sources/nflverse.py` — Saison-Parquet laden + normalisieren.
- `gridiron/features.py` — Situations-Eimer (Down/Distanz/Zone), Modell-Eingabe.
- `gridiron/tendencies.py` — Scouting-Report (DuckDB-Aggregation) + Render.
- `gridiron/model.py` — Pass/Lauf-Modell (HistGradientBoosting, scikit-learn).
- `gridiron/cli.py` — `doctor · ingest · stats · train · scout · predict`.

_Deskriptive/prognostische Analyse echter Daten – keine Garantie auf Ausgänge._
