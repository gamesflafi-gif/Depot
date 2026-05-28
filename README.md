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
│   ├── predictor.py       # lernendes ML-Modell + Bewertung
│   └── store.py           # Feature-Store, Modellspeicher, Lernhistorie
├── advisor.py             # Entscheidungs-Schicht: BOOM/KAUFEN/HALTEN/VERKAUFEN
├── pipeline.py            # Orchestrierung (train/analyze/learn/…)
├── backtest.py            # Walk-Forward-Backtest
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

# 3) Einen kompletten Lernzyklus laufen lassen (labeln + snapshot + neu trainieren)
python -m stockai.cli learn

# 4) Strategie historisch testen
python -m stockai.cli backtest

# 5) Lernfortschritt ansehen
python -m stockai.cli history
```

## Dashboard

```bash
streamlit run dashboard/app.py
```

Tabs: **Empfehlungen** (Ranking + Chart), **Detail & News** (Begründungen,
Schlagzeilen, Timing) und **Lernfortschritt** (Güte über die Trainingsläufe).

---

## Konfiguration (`config.yaml`)

Wichtigste Stellschrauben:

| Schlüssel | Bedeutung |
|-----------|-----------|
| `data_source` | `demo` (offline, synthetisch) oder `live` (echte Daten) |
| `tickers` | Liste der beobachteten Aktien |
| `horizon_days` | Über wie viele Handelstage die Profitabilität vorhergesagt wird |
| `profit_threshold` | Ab welcher Rendite es als „profitabel“ gilt |
| `model.type` | `gradient_boosting`, `logistic` oder `sgd_online` (inkrementelles Lernen) |

### Live-Daten aktivieren

In `config.yaml` `data_source: live` setzen. Dafür muss die Umgebung Zugriff auf
`finance.yahoo.com` und `news.google.com` haben. In Claude Code on the Web wird
der Netzwerkzugriff über die **Netzwerk-Policy** der Umgebung gesteuert – falls
die Hosts blockiert sind (Fehler „Host not in allowlist“), muss die Policy
entsprechend angepasst werden. Doku:
<https://code.claude.com/docs/en/claude-code-on-the-web>

> Im aktuellen Standard ist `demo` aktiv, damit das Projekt überall sofort
> lauffähig ist. Die Demo-Daten sind synthetisch (Random-Walk) und enthalten
> bewusst kein „echtes“ Marktsignal – die Kennzahlen liegen daher nahe 0,5.
> Mit echten Live-Daten zeigt das Modell reale Muster.

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
