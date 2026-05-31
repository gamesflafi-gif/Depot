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

> 🚀 **Du willst es einfach live laufen lassen?** Die komplette
> Schritt-für-Schritt-Anleitung (Server kaufen → installieren → Telegram →
> Automatik) steht in **[ANLEITUNG.md](ANLEITUNG.md)**.

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
├── savings_plan.py        # Sparplan (ETF-Core + beste Aktien)
├── notify.py              # Report (Markdown) + optionaler Webhook
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
  Stochastik, Volumen-z-Score …), **Markt-/Querschnitts-Features** (relative
  Stärke + Perzentil-Ränge von Momentum & Sentiment im Universum – „wohin
  rotiert das Geld") und **News-Sentiment als gelerntes Merkmal**.
- **News fließen ins Lernen ein:** Das Modell wird auf tagesgenauem Sentiment
  mit-trainiert (im Demo-Modus an das Trend-Regime gekoppelt), nicht nur als
  Anzeige. Zusätzlich tiefere News-Features: **Sentiment-Trend**, **News-Mengen-
  Spike** und **Schlagwort-Signal** (Earnings/Upgrade/Lawsuit …) – News gehören
  dadurch zu den einflussreichsten Merkmalen.
- **Expected-Return-Modell:** Neben „steigt ja/nein" schätzt ein Regressor die
  **erwartete Rendite-Höhe** – für ein feineres Ranking der besten Aktien.
- **Wiederkehrende Muster & Saisonalität:** Kalendereffekte (Wochentag/Monat),
  ein **kausales Muster-Gedächtnis** (Folge-Rendite je Kurs-Zustand) und eine
  **Analog-Mustererkennung**: Die KI vergleicht die *Form* der jüngsten
  Kursbewegung mit allen früheren Verläufen und merkt sich, was nach den
  ähnlichsten historischen Mustern im Schnitt passierte.
- **Größeres Universum:** je mehr beobachtete Werte, desto stärker die
  Querschnitts-/relative-Stärke-Features (Standard: 24 Aktien + ETFs).
- **Interaktiver Telegram-Bot:** `bot` startet einen Bot, dem du direkt
  schreiben kannst – `/analyse NVDA`, `/top`, `/sparplan 200`, `/briefing`.
  Reagiert nur auf die eigene Chat-ID. Dauerbetrieb via `deploy/install_bot.sh`
  (systemd-Dienst).
- **Tägliches Briefing & Moves-Alerts:** `briefing` fasst die besten Chancen und
  Verkaufssignale zusammen und meldet gezielt **Veränderungen seit dem letzten
  Lauf** (neue Kauf-/Verkaufssignale, große Wahrscheinlichkeits-Sprünge) – ideal
  als tägliche Telegram-Nachricht.
- **Mehrere Anlageklassen:** Aktien, **ETFs** und **Krypto** werden gemeinsam
  analysiert (alles OHLCV). Krypto wird in der Demo volatiler modelliert und im
  Sparplan als kleiner, risikoreicher Topf behandelt; yfinance (`BTC-USD`) und
  Stooq (`btcusd`) liefern echte Krypto-Kurse.
- **Anbieter-unabhängige Kursdaten:** kein Zwang zu einer einzelnen API – der
  Live-Modus lädt Kurse über yfinance **oder** direkt als CSV von Stooq (ohne
  Key) und fällt automatisch um (`price_source: auto`). News kommen direkt per
  RSS. Damit hängt die KI nicht an einem einzigen Anbieter.
- **Beste Modellwahl:** `type: auto` lässt mehrere Modelle (HistGradientBoosting,
  GradientBoosting, RandomForest, Logistic, Ensemble, **Stacking**) gegeneinander
  antreten und wählt automatisch das mit der besten kreuzvalidierten Güte.
  Das **Stacking-Ensemble** lernt per Meta-Modell, die Basismodelle optimal zu
  kombinieren (`type: stacking`; im `evaluate`-Vergleich enthalten).
- **Risiko- & Sektor-bewusste Allokation:** Portfolio und Sparplan gewichten
  invers zur Volatilität (Risikoparität-Tilt), verstärkt durch die erwartete
  Rendite, und begrenzen den Anteil je **Branche** (Sektor-Diversifikation).
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
- **News-Ablation:** `ablation` misst den tatsächlichen Beitrag der News
  (Technik vs. News vs. kombiniert) – statt zu behaupten, dass News helfen,
  wird es nachgewiesen. (News tragen real meist einen *kleinen* Mehrwert, da
  vieles bereits eingepreist ist.)
- **Parameter-Sweep:** `sweep` testet die Strategie über ein Raster aus
  Kauf-Schwelle × Positionsanzahl und zeigt die robusteste Einstellung.

> 🔬 **Realistische Erwartung:** Aktienmärkte sind nahezu effizient – kein
> seriöses Modell „besiegt" sie zuverlässig. Gute echte Modelle erreichen
> **~52–56 %** Trefferquote (nicht 90 %!); die Demo ist bewusst auf dieses
> realistische Niveau eingestellt. Ziel ist die methodisch sauberste, am
> rigorosesten **validierte** Vorhersage mit kleinem, ehrlich gemessenem
> Mehrwert – kein Versprechen garantierter Gewinne. Die €-Beträge im
> Planspiel sind Demo-Artefakte und keine erzielbare reale Rendite.

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

# 2b2) Beitrag der News messen (Technik vs. News vs. kombiniert)
python -m stockai.cli ablation

# 2b3) Mehr Backtesting: Raster aus Schwelle × Top-K
python -m stockai.cli sweep --period 5y

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

# 5b) Sparplan: ETF-Core + beste Aktien, optional als Report/Benachrichtigung
python -m stockai.cli sparplan --monthly 100 --report sparplan.md --notify

# 5c) Tägliches Briefing mit "Moves"-Alerts (Veränderungen seit letztem Lauf)
python -m stockai.cli briefing --notify

# 6) Signalgüte historisch testen (Edge gegenüber Zufall)
python -m stockai.cli backtest

# 7) P&L-Strategie-Backtest mit Equity-Kurve vs. Buy & Hold
python -m stockai.cli strategy --top-k 3        # erzeugt equity_curve.png

# 7b) Planspiel: 500 € über 10 Jahre durchspielen (Demo)
python -m stockai.cli strategy --capital 500 --period 10y --train-frac 0.15 --retrain-every 5

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
| `price_source` | `auto` (yfinance + direkter Stooq-Fallback), `yfinance` oder `stooq` |
| `tickers` | Liste der beobachteten Aktien |
| `etfs` | ETFs/Fonds (Core des Sparplans) |
| `crypto` | Kryptowährungen (kleiner, risikoreicher Sparplan-Topf) |
| `horizon_days` | Über wie viele Handelstage die Profitabilität vorhergesagt wird |
| `profit_threshold` | Ab welcher Rendite es als „profitabel“ gilt |
| `model.type` | `auto` (CV-Auswahl), `hist_gradient_boosting`, `gradient_boosting`, `random_forest`, `logistic`, `ensemble`, `sgd_online` |
| `model.calibrate` | `true` für kalibrierte, verlässlichere P(Profit)-Wahrscheinlichkeiten |

### Live-Daten aktivieren

Am einfachsten ohne Datei-Edit (z. B. am Handy) per Flag oder Umgebungsvariable:

```bash
python -m stockai.cli --source live doctor     # einmalig umschalten
export STOCKAI_DATA_SOURCE=live                 # dauerhaft für die Session
```

Alternativ in `config.yaml` `data_source: live` setzen. Dafür muss die Umgebung Zugriff auf
`finance.yahoo.com` und `news.google.com` haben. In Claude Code on the Web wird
der Netzwerkzugriff über die **Netzwerk-Policy** der Umgebung gesteuert – falls
die Hosts blockiert sind (Fehler „Host not in allowlist“), muss die Policy
entsprechend angepasst werden. Doku:
<https://code.claude.com/docs/en/claude-code-on-the-web>

> Standard ist `data_source: live` (echte Daten – benötigt Internet). Zum
> Ausprobieren ohne Netzwerk auf `demo` umstellen oder `--source demo` nutzen;
> die Demo-Daten sind synthetisch mit einem eingebauten Lern-Signal.

### Optional: NewsAPI-Key für mehr News

Zusätzlich zu den RSS-Quellen kann NewsAPI.org genutzt werden. Einfach einen
kostenlosen Key als Umgebungsvariable setzen – die Quelle wird dann automatisch
mitgenutzt, andernfalls ohne Fehler übersprungen:

```bash
export STOCKAI_NEWSAPI_KEY="dein_key"
```

> 🔐 **Sicherheit:** Den Key niemals in `config.yaml` oder ins Repo committen.
> Als Umgebungsvariable bzw. (in Claude Code on the Web) als Environment-Secret
> hinterlegen. `newsapi.org` muss zudem von der Netzwerk-Policy erlaubt sein.

### Live-Sparplan, der sich aktualisiert und benachrichtigt

Der `sparplan`-Befehl baut einen **Core-Satellite-Sparplan**: ein fester Anteil
in breite ETFs/Fonds (Core, risikoärmer) plus die aktuell besten Einzelaktien
laut Modell (Satelliten, mit Obergrenze je Position). Bei jeder Ausführung auf
frischen Daten passt sich der Plan an.

**Damit er „live" ist und dich informiert**, lässt du ihn regelmäßig laufen –
das erfordert einen dauerhaft laufenden Rechner/Server (eine kurzlebige
Web-Session reicht dafür nicht):

**Telegram einrichten (empfohlen fürs Handy):**
1. In Telegram **@BotFather** öffnen → `/newbot` → du erhältst einen **Token**.
2. Eigene **Chat-ID** ermitteln (z. B. über **@userinfobot**).
3. Token + Chat-ID hinterlegen – **am einfachsten in einer Datei `.env`** im
   Projekt-Root (wird automatisch geladen, ist per `.gitignore` geschützt):

```ini
# .env  (NICHT committen!)
STOCKAI_TELEGRAM_TOKEN=123456:ABC…
STOCKAI_TELEGRAM_CHAT_ID=987654321
```

Alternativ als echte Umgebungsvariablen (z. B. Environment-Secrets der
Web-Umgebung oder in der Shell):

```bash
export STOCKAI_TELEGRAM_TOKEN="123456:ABC…"
export STOCKAI_TELEGRAM_CHAT_ID="987654321"
# Alternativ Discord/Slack: export STOCKAI_WEBHOOK_URL="https://…"

# täglich 8:00 via cron (crontab -e):
0 8 * * *  cd /pfad/zu/Depot && python -m stockai.cli --source live learn  >/dev/null 2>&1
5 8 * * *  cd /pfad/zu/Depot && python -m stockai.cli --source live sparplan --monthly 100 --report sparplan.md --notify
```

So lernt die KI täglich dazu (`learn`) und schickt dir den aktualisierten
Sparplan als Nachricht (`--notify`). `--report` legt zusätzlich eine
Markdown-Datei ab.

> ⚠️ Eine echte 24/7-Live-Überwachung mit Push aufs Handy braucht einen
> dauerhaft laufenden Host. Aus einer ephemeren Web-Session heraus ist das
> nicht möglich – die obigen Bausteine (Webhook + cron) machen es auf deinem
> eigenen Rechner/Server möglich.

**Komplette Schritt-für-Schritt-Anleitung für einen Mini-Server (≈5 €/Monat):
siehe [DEPLOY.md](DEPLOY.md)** – inkl. fertiger Skripte (`deploy/install.sh`,
`deploy/install_cron.sh`) und optionalem Docker (`docker compose up -d`).

### Diagnose

```bash
python -m stockai.cli doctor
```

Prüft die Konfiguration und ob die Live-Datenquellen (Yahoo, Google, NewsAPI)
erreichbar sind – ideal, um ein Live-Setup zu verifizieren.

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
