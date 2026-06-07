# Gridiron — Projekt- & Architekturplan

NFL-Scouting & Tendenz-Analyse für **Coaches/Analysten**. Lokal auf dem Server
(4 Kerne, 8 GB, kein GPU), **keine bezahlte API**, Daten bleiben lokal.
Ziel: echter Mehrwert für Footballteams → zahlende Kunden, Gewinn über Zeit.

## 0. Leitprinzipien
1. **Transparenz vor Black Box.** Coaches vertrauen nachvollziehbaren Zählungen.
   Tendenzen sind deskriptiv belegt; Modelle ergänzen, ersetzen nicht.
2. **Ehrliche Grenzen.** Wir versprechen keine Spielausgänge. „Tendenzen &
   Wahrscheinlichkeiten", keine Garantien. Kein Glücksspiel-Fokus.
3. **Server-tauglich.** Tabellarische Daten + Gradient-Boosting auf CPU – schnell.
4. **Frei & lizenzkonform.** Nur öffentlich verfügbare Daten (nflverse, Big Data Bowl).

## 1. Zielgruppe & Wert
- **Primär: Coaches/Analysten** (High-School-, College-, Amateur-/Semi-Pro-Staffs,
  freie Analysten). Sie brauchen schnelle, lesbare **Gegner-Scouting-Reports**
  und **Self-Scout** (wo bin ich selbst vorhersehbar?).
- Sekundär später: Fantasy, Content/Fans, ggf. Wett-Analyse (separat, sensibel).

### Was es IST
- Tendenz-Engine je Situation (Down/Distanz/Feldzone/Spielstand/Personnel).
- „Tells": Situationen, in denen ein Team sehr vorhersehbar ist.
- Self-Scout: dieselbe Analyse fürs eigene Team.
- Pass/Lauf-Vorhersagemodell für konkrete Live-Situationen + Vorhersehbarkeits-Wert.
- 4th-Down-/2-Punkt-Entscheidungshilfe (EV aus EPA/Win-Prob) — geplant.
- Play-/Routen-Bibliothek (aus Big Data Bowl) — geplant.

### Was es NICHT ist
- Keine Glücksspiel-/Tipp-Plattform (kann später separates, reguliertes Produkt sein).
- Keine Garantie auf Spielausgänge.

## 2. Datenlage (ehrlich)
| Quelle | Inhalt | Verfügbarkeit |
|---|---|---|
| **nflverse Play-by-Play** | jeder Spielzug 1999+ (Down, Distanz, Position, Play-Typ, EPA, WP, air_yards, Pass-/Lauf-Richtung, Play-Action) | ✅ frei & vollständig (Parquet) |
| **nfl participation** | Personnel/Formation (Offense/Defense) | ✅ frei, 2016+ |
| **NFL Big Data Bowl** | Spieler-Tracking (x/y, 10 Hz) → **Routen** | ⚠️ nur Teilmengen (Kaggle, ausgew. Saisons/Plays) |
| **CFBD** | College-PBP | ✅ frei (API-Key), spätere Erweiterung |

→ „Alle Routen aller Plays" ist öffentlich **nicht** verfügbar (NGS proprietär).
Routen lernen wir auf dem Big-Data-Bowl-Subset; PBP-Tendenzen sind vollständig.

## 3. Architektur
- **Daten-Lake:** DuckDB (Tabelle `plays`) + Parquet-Export. RAM-arm, SQL-Aggregation.
- **Tendenzen:** reine SQL-Aggregation (transparent, schnell) + Liga-Vergleich.
- **Modell:** `HistGradientBoostingClassifier` (scikit-learn) Pass/Lauf, Team als
  Merkmal. CPU, < Sekunden Inferenz. Später: Pass-Tiefe, Lauf-Gap, 4th-Down-EV.
- **Routen (Phase 2):** Trajektorien-Features aus Tracking → Routen-Klassifikator
  (slant/go/out/post/curl…) + Routenkombinationen je Team/Situation.
- **Web/Report (Phase 1.5):** FastAPI-Oberfläche + druckbarer PDF-Report
  (der verkaufbare Wochen-Scouting-Report).
- **Konten/Sicherheit/Recht/Deploy:** bewährte Muster (DuckDB, scrypt-Konten,
  Security-Header, Backups, HTTPS/Caddy) aus dem Vorprojekt übertragbar.

## 4. Modell-Roadmap (CPU)
1. **Pass/Lauf** je Situation (✅ erste Version) + Vorhersehbarkeit.
2. Pass-Tiefe (kurz/tief) & Lauf-Gap-Vorhersage.
3. 4th-Down/2-Punkt-EV-Entscheidung (aus EPA/WP).
4. Erfolg/EPA-Erwartung je Play-Call (Matchup-abhängig).
5. Routen-Erkennung & -Kombinationen (Big Data Bowl).

## 5. Monetarisierung (kompoundierend)
| Tier | Preis (Idee) | Inhalt |
|---|---|---|
| Free | 0 € | Liga-Stats, ein Team-Vorschau-Report, Demo |
| Pro (Analyst) | 19–39 €/Monat | volle Gegner-Reports, Self-Scout, Live-Predict, Export |
| Team/Staff | 99–299 €/Monat | mehrere Sitze, Wochen-Auto-Reports, Personnel/Routen |
| Daten/API | nutzungsbasiert | Integrationen, Ligen, Analysten |

- **Grenzkosten ≈ 0** (eigener Server, freie Daten). Hauptarbeit: Reichweite in
  Coaching-/Analyst-Communities (Content, Demos, Twitter/YouTube-Breakdowns).
- Saisonalität: Footballsaison treibt Nachfrage (Aug–Feb) → Jahres-/Saisonpläne.

## 6. Risiken & Antworten
- **Tracking-Daten limitiert** → Routen als Zusatzmodul, Kerngeschäft ist PBP-Scouting.
- **Datenquelle ändert sich** (nflverse) → robustes Laden, Fehler sauber melden, Parquet-Snapshots.
- **„Nur Statistik"** → Differenzierung über lesbare Reports, Tells, Self-Scout,
  Live-Predict, später Routen — das spart Coaches echte Stunden Film-Arbeit.
- **Recht/Lizenz** → nur freie Daten, klare Nutzungsbedingungen, keine Wett-Garantien.

## 7. Roadmap (Phasen)
| Phase | Inhalt | Abnahme |
|---|---|---|
| **0 Fundament** ✅ | DuckDB-Lake, nflverse-Ingest, Tendenzen, Pass/Lauf-Modell, CLI, Tests | offline reproduzierbar, Tests grün |
| **1 Daten live** | echte Saisons laden, Modell trainieren | Reports/Predict auf echten Daten |
| **1.5 Web + Report** | FastAPI-UI + druckbarer Scouting-Report (PDF) | Coach erzeugt Report in <1 Min |
| **2 Tiefe** | Personnel/Formation, 4th-Down-EV, Pass-Tiefe/Gap | mehr Entscheidungswert |
| **3 Routen** | Big-Data-Bowl-Tracking, Routen-Klassifikation | Routenkombinationen je Team |
| **4 Produkt** | Konten, Tiers, Recht, Launch, Reichweite | zahlende Coaches/Analysten |
