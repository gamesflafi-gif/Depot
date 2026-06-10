# Franchise-Roadmap (vereinbart)

Reihenfolge nach deiner Priorität. Jede Etappe bleibt einzeln testbar &
lauffähig (node-check der ausgewerteten Seite + pytest + Live-Sweep).

## Priorität 1 — Spielansicht-Realismus (Richtung Madden)
Ziel: Plays sehen unterschiedlich & echt aus, Bewegungen flüssig.

- **1.1 Formations-Vielfalt** ✅ — pro Play eine echte Aufstellung
  (Shotgun, Singleback, I-Form, Trips, Empty) statt immer gleich.
- **1.2 Smoothere Bewegung** ✅ — Beschleunigung/Trägheit (Momentum) statt
  abruptem Start/Stopp, Ball mit Spin/Laces, weicheres Auslaufen.
- **1.3 Routen-Varianten** ✅ (via Formationen + offener Receiver) — mehr Routenbäume je Konzept, Option-/Sight-
  Adjustments je Coverage; Receiver-Stemmen & Breaks sichtbarer.
- **1.4 Blocks & Tackles verfeinern** ✅ (Gang-Tackle) — Pancakes, gebrochene Tackles
  (Power/Agilität), Gang-Tackle, realistischere Verfolgungswinkel.
- **1.5 Defense-Reaktionen** ✅ (Verfolgungswinkel) — Pursuit, Zonen-Passing-off, Safety-Hilfe.

## Priorität 2 — Anlagen-Hub „Stadion & Trainingsgelände" (FIFA-11-Wii-Stil)
Ziel: Du gehst in dein **Stadion/Gelände** und upgradest dort anklickbar.

- **2.1 Visueller Hub** ✅ (Stadion/Trainingsgelände/Kicker als anklickbare Gebäude) — ein Gelände-Screen mit anklickbaren Gebäuden
  statt Listen: Stadion, Trainingsplatz, Medizin, Athletik, Scouting-
  Akademie, Jugend/Akademie. Jedes Gebäude zeigt Stufe + Effekt + Upgrade.
- **2.2 Echte Effekte je Anlage/Stufe** ✅
  - Stadion → Wocheneinnahmen
  - Trainingsplatz → mehr Trainings-EXP (ersetzt/ergänzt Equipment)
  - Medizin → kürzere Verletzungen + geringeres Verletzungsrisiko
  - Athletik → schnellere Regeneration / Form
  - Scouting-Akademie → mehr Scouting-Punkte/Woche, bessere Aufdeckung
  - Jugend/Akademie → jede Saison eigene Talente (Free Draft-Pick)
- **2.3 Trainingsplatz-Bereich** — Drills sichtbar wählbar mit Fortschritt.

## Priorität 3 — Saison-Tiefe
- **3.1 Award-Show** ✅ am Saisonende: MVP, Offensiv-/Defensiv-Spieler,
  Rookie of the Year, Top-Scorer (aus Box-Score-Statistik).
- **3.2 Hall of Fame / Historie** ✅ — Meister, Award-Gewinner, Rekorde
  über alle Saisons.
- **3.3 Power-Ranking & Liga-News** pro Woche.
- **3.4 Mehrsaison-Statistik** je Spieler/Team (Karriere-Verlauf).

## Arbeitsweise (gegen „läuft nicht")
- Vor jedem Push: `node --check` auf der **von Python ausgewerteten** Seite,
  `pytest`, Live-Funktions-Sweep aller Bereiche.
- Sichtbarer Build-Marker (Footer + Header `X-Gridiron-Build`) zur Versionsprüfung.
