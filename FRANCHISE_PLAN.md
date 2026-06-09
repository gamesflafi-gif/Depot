# Franchise-Bauplan (entschieden)

Alle Entscheidungen final (deine Vorgaben + meine Empfehlungen). Wir bauen in
**2 Etappen**; jede bleibt testbar und lauffähig.

## Festlegungen
- Generierter Kader mit positionsgerechten Namen. **Start: jedes Team-Mitglied ~60 OVR**
  (60er-Schnitt mit leichter Attribut-Streuung).
- **Individuelle Attribute pro Position** (4 je Position), daraus positionsgewichtetes OVR.
- **Potenzial pro Attribut** (Cap), nur durch Verbesserung erreichbar.
- **EXP → Skillpunkte**: 100 EXP = 1 Skillpunkt; Punkte selbst auf Attribute verteilen
  (bis zum Cap), plus „Auto-verteilen". Nur EXP als Spieler-Währung.
- **EXP-Quellen**: wöchentliches Training (Equipment erhöht), **Trainings-Fokus** je Woche
  (eine Positionsgruppe bekommt mehr EXP), Spiele (Starter mehr, Sieg-Bonus).
  *(Etappe 2: positionsbezogene Leistung im Box-Score, besondere Events.)*
- **Depth-Chart**: Starter pro Position wählbar; Unit-Rating gewichtet Starter stärker.
- **Alterung**: ab 30 Abbau möglich, junge Spieler wachsen.
- KI-Teams bleiben vorerst aggregiert (nur Team-Rating), Architektur für Voll-Kader offen.

## Attributmodell (Position → Attribute, Gewichte)
- QB: Genauigkeit .35, Wurfkraft .25, Übersicht .25, Mobilität .15
- RB: Speed .30, Agilität .25, Power .25, Hände .20
- WR: Speed .30, Route .30, Hände .30, Sprungkraft .10
- OL: Pass-Schutz .35, Run-Block .35, Stärke .20, Übersicht .10
- DL: Pass-Rush .35, Run-Stop .35, Stärke .20, Mobilität .10
- LB: Tackling .30, Coverage .30, Speed .25, Übersicht .15
- DB: Coverage .40, Speed .30, Ball-Skills .20, Tackling .10

OVR = gewichteter Schnitt der Attribute (gerundet). Unit-Rating = gewichteter Schnitt
der Gruppe (Starter ×2, Bank ×1).

## Etappe 1 (dieser Schritt)
Spieler-Attribute + Potenzial · EXP/Skillpunkte + Verteilung · wöchentliches Training
mit Fokus · Depth-Chart (Starter setzen) · Alterung/Entwicklung · Spielerkarte
(Attribut-Balken + Radar) im Bereich „Kader & Training".

## Etappe 2 (danach)
Trainer-Profile mit individuellen Stärken/Schwächen (EXP-Boost + Spiel-Bonus, Markt) ·
besondere Events (Breakout/Verletzung/Camp/Mentor/Formtief) · Verletzungen mit Ausfall
und Backup-Einsatz · **Box-Scores je Spieler** (Sim auf Spielerebene → echte Statistiken
und leistungsbasierte EXP) · animierter interaktiver Spielmodus.
