# 📈 Depot – Lernende Aktien- & News-KI

Eine selbstlernende KI, die **Aktienkurse analysiert, mit aktuellen News abgleicht**
und daraus **eigenständige Handlungsempfehlungen** ableitet:

- **Wer wird profitabel?** – Wahrscheinlichkeit, dass eine Aktie über den
  gewählten Horizont im Plus liegt.
- **Wohin fließt das Geld?** – Ranking der Aktien nach dieser Wahrscheinlichkeit.
- **Welche Aktien könnten boomen?** – Kombination aus gelerntem Signal,
  Momentum und positivem News-Sentiment.
- **Wann verkaufen?** – Timing-Signale (überkauft, Kurs am Hoch, abdrehendes
  Momentum, kippendes Sentiment) für Gewinnmitnahme.

Die KI **lernt kontinuierlich dazu**: Bei jedem Lernzyklus sammelt sie neue
Beobachtungen, labelt vergangene Vorhersagen mit der real eingetretenen Rendite,
trainiert neu und protokolliert ihre Güte – so wird ihre Präzision über die Zeit
messbar besser.

> ⚠️ **Keine Anlageberatung.** Dieses Projekt ist ein Lern-/Analysewerkzeug.
> Entscheidungen über echtes Geld triffst du selbst und auf eigenes Risiko.

---

## Architektur

```
stockai/
├── config.py              # Konfiguration laden (config.yaml)
├── data/
│   ├── prices.py          # Kursdaten via yfinance (live)
│   ├── news.py            # News via RSS, geparst mit der Standardbibliothek (live)
│   ├── demo.py            # synthetische Offline-Daten (demo)
│   └── provider.py        # schaltet zwischen live/demo um
├── features/
│   ├── technical.py       # technische Indikatoren (RSI, MACD, Vola, …)
│   └── sentiment.py       # News-Sentiment via VADER
├── model/
│   ├── predictor.py       # lernendes ML-Modell + CV-Bewertung + Kalibrierung
│   ├── selection.py       # automatische Modellwahl (type: auto)
│   ├── tuning.py          # Hyperparameter-Tuning (Zeitreihen-CV)
│   └── store.py           # Feature-Store, Modellspeicher, Lernhistorie
├── advisor.py             # Entscheidungs-Schicht: BOOM/KAUFEN/HALTEN/VERKAUFEN
├── portfolio.py           # Allokations-Engine (wohin wie viel Kapital)
├── pipeline.py            # Orchestrierung (train/analyze/learn/…)
├── backtest.py            # Signalgüte-Backtest (Edge)
├── strategy.py            # P&L-Strategie-Backtest (Equity, Sharpe, Drawdown)
├── scorecard.py           # Treffsicherheit der Empfehlungen + Kalibrierung
└── cli.py                 # Kommandozeilen-Interface
dashboard/app.py           # Streamlit-Dashboard
tests/                     # Offline-Tests (kein Netzwerk nötig)
```

### Wie „lernt“ die KI?

1. **Bootstrap:** Aus 2 Jahren Kurshistorie werden technische Features berechnet
   und mit der realen Folge-Rendite gelabelt (profitabel ja/nein).
2. **Snapshot:** `snapshot` speichert den aktuellen Zustand jeder Aktie –
   inklusive **echtem Live-News-Sentiment** – im Feature-Store (noch ohne Label).
3. **Label:** Sobald der Vorhersage-Horizont verstrichen ist, füllt `label` die
   tatsächlich eingetretene Rendite ein. Aus Snapshots werden echte Lerndaten
   **mit** Sentiment-Information.
4. **Train:** Das Modell wird auf der gewachsenen Datenbasis neu trainiert und
   out-of-sample bewertet; die Güte wird in `learning_history.json` protokolliert.

Mit jedem Zyklus wächst die Erfahrung – das News-Signal gewinnt an Gewicht und
die Vorhersagen werden präziser. Der Verlauf ist über `history` bzw. im
Dashboard-Tab „Lernfortschritt“ sichtbar.

### Wie wird die Präzision maximiert – und ehrlich gemessen?

- **Viele Signale:** 18 technische Indikatoren (Renditen über mehrere Horizonte,
  RSI, MACD inkl. Histogramm, gleitende Durchschnitte, Bollinger %B, ATR,
  Stochastik, Volumen-z-Score …), **Markt-/relative-Stärke-Features** (wohin
  rotiert das Geld) und **News-Sentiment als gelerntes Merkmal**.
- **News fließen ins Lernen ein:** Das Modell wird auf tagesgenauem Sentiment
  mit-trainiert (im Demo-Modus an das Trend-Regime gekoppelt), nicht nur als
  Anzeige – News-Features gehören dadurch zu den einflussreichsten Merkmalen.
- **Beste Modellwahl:** `type: auto` lässt mehrere Modelle (HistGradientBoosting,
  GradientBoosting, RandomForest, Logistic, Ensemble) gegeneinander antreten und
  wählt automatisch das mit der besten kreuzvalidierten Güte.
- **Kalibrierte Wahrscheinlichkeiten:** Mit `calibrate: true` werden die
  P(Profit)-Werte isotonisch kalibriert – „70 %" heißt dann wirklich ~70 %.
- **Ehrliche Validierung:** Bewertung per **zeitlicher Kreuzvalidierung**
  (`TimeSeriesSplit`) – das Modell sieht beim Testen nie die Zukunft. `train`
  zeigt AUC/Accuracy als Mittelwert ± Streuung, `evaluate` vergleicht alle Modelle.
- **Hyperparameter-Tuning:** `tune` optimiert die Modellparameter per CV und
  speichert sie; `train` wendet sie automatisch an.
- **Recommendation-Scorecard:** `scorecard` bewertet per Walk-Forward, wie
  treffsicher die Empfehlungen je Aktion (BOOM/KAUFEN/VERKAUFEN …) waren und ob
  die Wahrscheinlichkeiten gut **kalibriert** sind (vorhergesagt ≈ tatsächlich).

> 🔬 **Realistische Erwartung:** Aktienmärkte sind nahezu effizient – kein
> seriöses Modell „besiegt" sie zuverlässig. Ziel dieses Projekts ist die
> methodisch sauberste, am rigorosesten **validierte** Vorhersage, die einen
> kleinen, ehrlich gemessenen Mehrwert anstrebt – nicht das Versprechen
> garantierter Gewinne.

---

## Installation

```bash
pip install -r requirements.txt
```

(Python 3.11+. Hinweis: ggf. `python -m pip` verwenden, damit die Pakete in den
aktiven Interpreter installiert werden.)

## Schnellstart (CLI)

```bash
# 1) Modell erstmals trainieren
python -m stockai.cli train

# 2) Aktien analysieren + Empfehlungen erhalten
python -m stockai.cli analyze --headlines

# 2b) Modelltypen per Kreuzvalidierung vergleichen
python -m stockai.cli evaluate

# 2c) Hyperparameter optimieren (werden beim nächsten train angewandt)
python -m stockai.cli tune

# 2d) Treffsicherheit der Empfehlungen bewerten (Scorecard)
python -m stockai.cli scorecard

# 3) Einen kompletten Lernzyklus laufen lassen (labeln + snapshot + neu trainieren)
python -m stockai.cli learn

# 4) Lernkurve: belegt, dass mehr Daten zu höherer Präzision führen
python -m stockai.cli simulate

# 5) Konkreter Allokationsvorschlag (wohin wie viel Kapital)
python -m stockai.cli portfolio --capital 10000

# 6) Signalgüte historisch testen (Edge gegenüber Zufall)
python -m stockai.cli backtest

# 7) P&L-Strategie-Backtest mit Equity-Kurve vs. Buy & Hold
python -m stockai.cli strategy --top-k 3        # erzeugt equity_curve.png

# 8) Lernfortschritt ansehen
python -m stockai.cli history
```

Nach `pip install -e .` steht der Befehl auch direkt als `stockai` zur Verfügung
(z. B. `stockai analyze`, `stockai portfolio`).

## Dashboard

```bash
streamlit run dashboard/app.py
```

Tabs: **Empfehlungen** (Ranking + Chart), **Detail & News** (Begründungen,
Schlagzeilen, Timing), **Portfolio** (Allokation + Kapital-Pie),
**Strategie-Backtest** (Equity-Kurve vs. Buy & Hold, Sharpe, Drawdown),
**Scorecard** (Treffsicherheit + Kalibrierung) und **Lernfortschritt**
(Güte über die Trainingsläufe).

---

## Konfiguration (`config.yaml`)

Wichtigste Stellschrauben:

| Schlüssel | Bedeutung |
|-----------|-----------|
| `data_source` | `demo` (offline, synthetisch) oder `live` (echte Daten) |
| `tickers` | Liste der beobachteten Aktien |
| `horizon_days` | Über wie viele Handelstage die Profitabilität vorhergesagt wird |
| `profit_threshold` | Ab welcher Rendite es als „profitabel“ gilt |
| `model.type` | `auto` (CV-Auswahl), `hist_gradient_boosting`, `gradient_boosting`, `random_forest`, `logistic`, `ensemble`, `sgd_online` |
| `model.calibrate` | `true` für kalibrierte, verlässlichere P(Profit)-Wahrscheinlichkeiten |

### Live-Daten aktivieren

In `config.yaml` `data_source: live` setzen. Dafür muss die Umgebung Zugriff auf
`finance.yahoo.com` und `news.google.com` haben. In Claude Code on the Web wird
der Netzwerkzugriff über die **Netzwerk-Policy** der Umgebung gesteuert – falls
die Hosts blockiert sind (Fehler „Host not in allowlist“), muss die Policy
entsprechend angepasst werden. Doku:
<https://code.claude.com/docs/en/claude-code-on-the-web>

> Im aktuellen Standard ist `demo` aktiv, damit das Projekt überall sofort
> lauffähig ist. Die Demo-Daten sind synthetisch, enthalten aber ein bewusst
> eingebautes, lernbares Trend-/News-Signal – so ist die Selbstverbesserung
> messbar (`simulate` / `backtest` zeigen einen positiven Mehrwert).

### Optional: NewsAPI-Key für mehr News

Zusätzlich zu den RSS-Quellen kann NewsAPI.org genutzt werden. Einfach einen
kostenlosen Key als Umgebungsvariable setzen – die Quelle wird dann automatisch
mitgenutzt, andernfalls ohne Fehler übersprungen:

```bash
export STOCKAI_NEWSAPI_KEY="dein_key"
```

### Automatische Einrichtung (Claude Code on the Web)

Ein SessionStart-Hook (`.claude/settings.json` → `.claude/hooks/setup.sh`)
installiert die Abhängigkeiten beim Start einer Web-Session automatisch, sodass
Tests, CLI und Dashboard sofort lauffähig sind.

---

## Tests

```bash
python -m pytest tests/ -q
```

## Roadmap / mögliche Erweiterungen

- News-API mit Key (z. B. NewsAPI.org) als zusätzliche Quelle
- Backfill historischer News für stärkeres Sentiment-Lernen
- Portfolio-Optimierung & Positionsgrößen
- Automatisches Scheduling der Lernzyklen (z. B. täglich)
- Mehr Modelltypen / Hyperparameter-Tuning
