# Gridiron — Masterplan (große Plattform)

Vision: die **professionelle Football-Analyse- & Simulationsplattform** für
Coaches, Analysten und ambitionierte Fans. Nicht ein Tool, sondern ein Haus mit
vielen Räumen — Scouting, **Play-Simulator (Konzept vs. Coverage)**, Gameplan-
Builder, Self-Scout, Entscheidungshilfen, Spielerprofile, Lernzentrum. Lokal auf
dem Server, CPU-tauglich, freie Daten, **keine bezahlte API**. Ziel: echter
Nutzen → zahlende Kunden → kompoundierender Gewinn.

> Dieses Dokument ist die Dachvision. Technischer Detailplan: `GRIDIRON_PLAN.md`.

---

## 1. Bereiche der Plattform (Räume im Haus)

### A. Scouting (✅ vorhanden)
Gegner-Tendenzen, Tells, Down&Distanz, Feldzonen, Richtungen, Liga-Vergleich,
Live-Pass/Lauf-Vorhersage, Druck-Report.

### B. Play-Simulator (🚀 Kern dieses Ausbaus)
„Was passiert, wenn ich **Konzept X** gegen **Coverage Y** in **Situation Z**
laufe?" Monte-Carlo-Simulation → Ertragsverteilung (Yards), Erfolgsrate,
Big-Play-, TD-, Turnover-, Sack-Wahrscheinlichkeit, erwartetes EPA, Urteil.
- **Offense-Konzepte**: Pass (Four Verts, Mesh, Smash, Flood, Slant-Flat, Stick,
  Y-Cross, Dagger, Drive, Spacing, Screens) & Lauf (Inside/Outside Zone, Power,
  Counter, Draw, Toss, Trap).
- **Defense-Coverages**: Cover 0/1/2/3/4 (Quarters)/6, Cover 2-Man, Tampa 2.
- **Individualität**: Down, Distanz, Feldposition, Personnel (11/12/21), Box-Count,
  Hash, Spielstand/Zeit → alles fließt in die Simulation ein.
- **Matchup-Matrix**: ganze Heatmap „jedes Konzept × jede Coverage" (erwartetes
  EPA) → sofort sehen, was wogegen funktioniert.
- **Berater**: „Beste Antwort auf Cover 3" / „Welche Coverage stoppt Mesh?".

### H. Team-Manager / Franchise (✅ neu)
Ein vollwertiger Spielmodus (Madden-Franchise-Stil): eigene Franchise gründen,
Team über Budget aufbauen (7 Einheiten), Playbook wählen, Liga-Saison gegen
KI-Teams spielen, Playoffs, Titel, mehrere Saisons mit sich entwickelnder Liga.
Spiele aus Team-Stärke × Simulator-Matchup-Logik. Bindet Nutzer langfristig
(Spiel-Schleife) und ist ein eigener, breiter Markt (Football-Manager-Fans).

### C. Gameplan-Builder (geplant)
Call-Sheet je Situation (1st&10, 3rd&short, Red Zone, 2-Minute …) aus
Simulator + Gegner-Scouting automatisch vorgeschlagen; als PDF exportierbar.

### D. Self-Scout (geplant)
Dieselbe Engine aufs eigene Team: „Wo bin ich vorhersehbar? Welche meiner
Konzepte verpuffen gegen die Coverages, die der nächste Gegner spielt?"

### E. Entscheidungshilfen (geplant)
4th-Down (Go/Punt/FG-EV aus EPA/Win-Prob), 2-Punkt-Konversion, Uhren-/Timeout-
Management, Field-Goal-Reichweite.

### F. Spieler- & Matchup-Profile (geplant, datenabhängig)
QB/RB/WR-Tendenzen, Pass-Tiefe-Verteilung, Ziel-Anteile; WR-vs-CB-Matchups.

### G. Lern- & Erklärzentrum (geplant)
Jedes Konzept/Coverage erklärt (Stärken, Schwächen, Reads) — macht das Produkt
auch für Aufsteiger/Fans wertvoll und senkt Support-Aufwand.

---

## 2. Architektur (skaliert)
```
Browser (Multi-Bereich-SPA: Scouting · Simulator · Matrix · …)
      │  REST/JSON
FastAPI (gridiron/web.py)
      ├── tendencies.py    Scouting (DuckDB-Aggregation)
      ├── model.py         Pass/Lauf-ML (HistGBT)
      ├── simulator.py     Konzept×Coverage Monte-Carlo  ← NEU
      ├── knowledge.py     Konzept-/Coverage-Wissensbasis ← (in simulator integriert)
      └── storage.py       DuckDB Daten-Lake (Play-by-Play)
```
- **Daten-Lake**: DuckDB, idempotent, Parquet-Export. Anchor-Statistiken (Liga-
  Basisraten) speisen den Simulator → datengetrieben, nicht erfunden.
- **Simulation**: NumPy-vektorisiert (tausende Sims in Millisekunden, CPU).
- **Transparenz**: jede Zahl ist erklärbar (Basisrate × Matchup-Faktor),
  Football-Logik offengelegt — kein Black-Box-Orakel.

## 3. Modell-/Engine-Ehrlichkeit
- Coverage-Labels sind in frei verfügbaren PBP-Daten **nicht** flächendeckend
  enthalten (NGS/Charting proprietär). Der Simulator kombiniert daher **echte
  Liga-Basisraten** (Yards-, Erfolgs-, Big-Play-Verteilungen) mit einer
  **kalibrierten Football-Wissensmatrix** (Konzept-Stärken/-Schwächen je
  Coverage-Familie). Das ist seriös, nachvollziehbar und sofort nützlich; mit
  Charting-Daten (Phase 3) wird die Matrix datengelernt verfeinert.
- Keine Garantie auf Spielausgänge — Wahrscheinlichkeiten & Tendenzen.

## 4. Monetarisierung (kompoundierend)
| Tier | Idee | Inhalt |
|---|---|---|
| Free | 0 € | Liga-Stats, 1 Scouting-Vorschau, Simulator-Demo (begrenzte Sims) |
| Pro (Analyst) | 19–39 €/Mo | volle Reports, voller Simulator, Matchup-Matrix, Export |
| Team/Staff | 99–299 €/Mo | Sitze, Gameplan-Builder, Self-Scout, Auto-Wochenreports |
| Daten/API | nutzungsbasiert | Integrationen, Ligen, Verbände |

Grenzkosten ≈ 0 (eigener Server, freie Daten). Wachstum über Football-Content
(Konzept-/Coverage-Breakdowns), Demos, Saisonpläne (Aug–Feb Hochsaison).

## 5. Roadmap (groß gedacht, schrittweise gebaut)
| Phase | Inhalt | Status |
|---|---|---|
| 0 Fundament | Lake, Ingest, Scouting, Pass/Lauf-ML, CLI, Web, Druck-Report | ✅ |
| **1 Simulator** | Konzept×Coverage Monte-Carlo, Matchup-Matrix, Berater, Web-Bereich | ✅ |
| **1b Franchise** | Team-Manager-Spielmodus (Liga, Playoffs, Kaderaufbau, Saisons) | ✅ |
| 2 Gameplan | Call-Sheet-Builder, Situations-Empfehlungen, PDF | geplant |
| 3 Tiefe/Daten | echte Saisons, Personnel/Formation, Charting-Kalibrierung, Spielerprofile | geplant |
| 4 Entscheidungen | 4th-Down/2-Pt-EV, Uhrenmanagement | geplant |
| 5 Produkt | Konten, Tiers, HTTPS, Recht, Launch, Reichweite | geplant |

## 6. Qualität & Betrieb
- Tests für jede Engine (Simulator deterministisch via Seed).
- systemd-Autostart + Reverse-Proxy (HTTPS) für Dauerbetrieb.
- Backups des Lake (Parquet-Snapshots).
- Mobile-first UI (Coaches am Spielfeldrand / Tablet).
