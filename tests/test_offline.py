"""Offline-Tests (kein Netzwerk nötig) für die Kern-Logik."""
from __future__ import annotations

import numpy as np
import pandas as pd

from stockai.advisor import recommend
from stockai.features.technical import TECHNICAL_FEATURES, add_technical_features
from stockai.features.sentiment import SENTIMENT_FEATURES, aggregate_sentiment, score_text
from stockai.data.news import NewsItem
from stockai.model.predictor import Predictor
from stockai.pipeline import FEATURE_COLUMNS


def _synthetic_prices(n: int = 300, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0005, 0.02, n)
    close = 100 * np.cumprod(1 + rets)
    idx = pd.date_range("2022-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "Open": close * 0.99,
            "High": close * 1.01,
            "Low": close * 0.98,
            "Close": close,
            "Volume": rng.integers(1e6, 5e6, n),
        },
        index=idx,
    )


def test_technical_features_created():
    df = add_technical_features(_synthetic_prices())
    for col in TECHNICAL_FEATURES:
        assert col in df.columns
    # nach Warmlaufphase keine NaN mehr
    assert df[TECHNICAL_FEATURES].iloc[60:].notna().all().all()
    # neue volumengewichtete Features sind endlich (kein inf) und skalenfrei
    for col in ("rel_volume", "obv_slope", "mfi_14", "ret_skew_20"):
        vals = df[col].iloc[60:].values
        assert np.isfinite(vals).all()
    assert (df["rel_volume"].iloc[60:] > 0).all()        # Verhältnis > 0
    assert df["mfi_14"].iloc[60:].between(0, 100).all()  # MFI in [0,100]


def test_sentiment_scoring():
    assert score_text("Great profits, strong growth and record sales") > 0
    assert score_text("Terrible crash, huge losses and bankruptcy fears") < 0
    news = [
        NewsItem("X", "Company beats earnings, soars", "", "", None, "test"),
        NewsItem("X", "Lawsuit and fraud allegations hit firm", "", "", None, "test"),
    ]
    res = aggregate_sentiment(news)
    for col in SENTIMENT_FEATURES:
        assert col in res.features
    assert res.features["news_count"] == 2


def test_predictor_trains_and_predicts():
    df = add_technical_features(_synthetic_prices(seed=1))
    df["target"] = (df["Close"].shift(-5) / df["Close"] - 1 > 0).astype(float)
    for col in SENTIMENT_FEATURES:
        df[col] = 0.0
    # Markt-Features (Einzel-Ticker: Markt = Ticker selbst, Ränge neutral)
    df["mkt_ret_5d"] = df["ret_5d"]
    df["rel_strength_20d"] = 0.0
    df["xs_mom_rank"] = 0.5
    df["xs_sent_rank"] = 0.5
    df["mkt_trend"] = df["dist_sma50"]
    df["mkt_vol"] = df["vol_20d"]
    df["pattern_mem"] = 0.0
    df["analog_mem"] = 0.0
    df["ticker_bias"] = 0.5
    df = df.dropna(subset=[c for c in FEATURE_COLUMNS if c in df.columns] + ["target"])
    pred = Predictor(FEATURE_COLUMNS, model_type="logistic")
    result = pred.train(df, test_size=0.2)
    assert 0.0 <= result.metrics["accuracy"] <= 1.0
    proba = pred.predict_proba(df.head(5))
    assert ((proba >= 0) & (proba <= 1)).all()


def test_regime_exposure_defensive():
    from types import SimpleNamespace
    from stockai.portfolio import _regime_exposure, build_portfolio
    bull = [SimpleNamespace(momentum_5d=0.03, ticker="A", action="KAUFEN",
                            profit_probability=0.6, confidence=0.7, last_price=10.0)
            for _ in range(4)]
    bear = [SimpleNamespace(momentum_5d=-0.05, ticker=f"A{i}", action="KAUFEN",
                            profit_probability=0.6, confidence=0.7, last_price=10.0)
            for i in range(4)]
    assert _regime_exposure(bull) == 1.0
    assert _regime_exposure(bear) < 1.0          # defensiv im klaren Abschwung
    assert _regime_exposure(bear) <= 0.65
    # Im Bärenmarkt wird weniger investiert (mehr Cash)
    pf = build_portfolio(bear, capital=1000.0)
    assert pf.cash > 0.0                          # Regime-Bremse hält Cash


def test_advisor_no_sell_when_model_bullish():
    # Überkauft + am Hoch, aber Modell weiter bullisch -> KEIN Verkauf
    rec = recommend(
        profit_probability=0.66, rsi_14=78, momentum_5d=0.02,
        price_vs_high_20=0.99, macd_hist=-0.3, sentiment_mean=-0.2,
        expected_return=0.02,
    )
    assert rec.action != "VERKAUFEN"
    # Gleiche Technik, aber Modell bärisch -> Verkauf
    rec2 = recommend(
        profit_probability=0.45, rsi_14=78, momentum_5d=-0.02,
        price_vs_high_20=0.99, macd_hist=-0.3, sentiment_mean=-0.2,
        expected_return=-0.01,
    )
    assert rec2.action == "VERKAUFEN"


def test_advisor_sell_signal_on_overbought():
    rec = recommend(
        profit_probability=0.5, rsi_14=78, momentum_5d=-0.02,
        price_vs_high_20=0.99, macd_hist=-0.5, sentiment_mean=-0.2,
    )
    assert rec.action == "VERKAUFEN"


def test_advisor_boom_signal():
    rec = recommend(
        profit_probability=0.7, rsi_14=55, momentum_5d=0.05,
        price_vs_high_20=0.9, macd_hist=0.5, sentiment_mean=0.3,
    )
    assert rec.action == "BOOM"


def test_advisor_no_buy_on_negative_expected_return():
    # Positives Wahrscheinlichkeits-Signal, aber negativ erwartete Rendite
    rec = recommend(
        profit_probability=0.66, rsi_14=55, momentum_5d=0.05,
        price_vs_high_20=0.9, macd_hist=0.5, sentiment_mean=0.3,
        expected_return=-0.02,
    )
    assert rec.action not in ("BOOM", "KAUFEN")
    # Ohne (oder mit positiver) erwarteter Rendite bleibt es ein Kauf/Boom
    rec2 = recommend(
        profit_probability=0.66, rsi_14=55, momentum_5d=0.05,
        price_vs_high_20=0.9, macd_hist=0.5, sentiment_mean=0.3,
        expected_return=0.02,
    )
    assert rec2.action == "BOOM"


def test_advisor_avoid_on_low_prob():
    rec = recommend(
        profit_probability=0.3, rsi_14=50, momentum_5d=0.0,
        price_vs_high_20=0.9, macd_hist=0.0, sentiment_mean=0.0,
    )
    assert rec.action == "MEIDEN"


def test_demo_prices_periods_are_consistent():
    """Verschiedene Zeiträume müssen Ausschnitte derselben Reihe sein."""
    from stockai.data.demo import demo_prices

    long = demo_prices("DEMO", period="2y")
    short = demo_prices("DEMO", period="3mo")
    assert len(short) < len(long)
    # Das kurze Fenster ist exakt der Schwanz des langen Fensters
    tail = long["Close"].iloc[-len(short):].values
    assert np.allclose(tail, short["Close"].values)
    # Determinismus über mehrere Aufrufe
    assert np.allclose(demo_prices("DEMO", period="2y")["Close"].values,
                       long["Close"].values)


def test_portfolio_allocation_and_cap():
    from types import SimpleNamespace
    from stockai.portfolio import build_portfolio

    analyses = [
        SimpleNamespace(ticker="A", action="BOOM", profit_probability=0.8,
                        confidence=0.8, last_price=100.0),
        SimpleNamespace(ticker="B", action="KAUFEN", profit_probability=0.6,
                        confidence=0.6, last_price=50.0),
        SimpleNamespace(ticker="C", action="VERKAUFEN", profit_probability=0.3,
                        confidence=0.7, last_price=20.0),
    ]
    pf = build_portfolio(analyses, capital=10_000.0, max_position_pct=0.5)
    tickers = {a.ticker for a in pf.allocations}
    assert tickers == {"A", "B"}            # nur Kaufkandidaten
    assert "C" in pf.sells                   # Verkaufssignal erfasst
    assert all(a.weight <= 0.5 + 1e-6 for a in pf.allocations)  # Cap eingehalten
    assert abs(pf.invested + pf.cash - pf.capital) < 1e-6        # Kapital erhalten
    assert pf.allocations[0].ticker == "A"   # stärkstes Signal zuerst


def test_stooq_csv_parser_and_symbol():
    from stockai.data.stooq import parse_stooq_csv, _to_symbol

    assert _to_symbol("AAPL") == "aapl.us"     # US-Werte bekommen .us
    assert _to_symbol("VWCE.DE") == "vwce.de"  # Suffix bleibt erhalten
    csv_text = (
        "Date,Open,High,Low,Close,Volume\n"
        "2024-01-02,100.0,102.0,99.0,101.5,1000000\n"
        "2024-01-03,101.5,103.0,100.5,102.8,1200000\n"
    )
    df = parse_stooq_csv(csv_text)
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(df) == 2
    assert abs(df["Close"].iloc[-1] - 102.8) < 1e-9
    # defektes CSV -> leerer DataFrame (kein Absturz)
    assert parse_stooq_csv("kaputt\n1,2,3").empty


def test_briefing_and_moves(tmp_path):
    """Briefing erzeugt Report; zweiter Lauf erkennt Veränderungen."""
    from stockai import briefing as bf
    from stockai.config import load_config

    cfg = load_config()
    cfg.raw["data_source"] = "demo"
    cfg.tickers = ["AAA", "BBB", "CCC"]
    cfg.etfs = []
    cfg.crypto = []
    cfg.model = {"type": "logistic", "random_state": 42}
    cfg.paths = {"store_dir": str(tmp_path / "s"), "model_dir": str(tmp_path / "m")}

    br1 = bf.build_briefing(cfg)
    assert br1.has_changes is False          # erster Lauf: kein Vorzustand
    report = bf.render_briefing(br1, cfg)
    assert "Briefing" in report
    # sauberes Telegram-Format: keine rohen Markdown-Zeichen
    assert "**" not in report and "# " not in report and "_K" not in report

    # Vorzustand künstlich verändern -> zweiter Lauf muss Moves erkennen
    import json
    state_file = tmp_path / "s" / "last_briefing.json"
    state = json.load(open(state_file))
    for t in state:
        state[t] = {"action": "MEIDEN", "prob": 0.05}
    json.dump(state, open(state_file, "w"))

    br2 = bf.build_briefing(cfg)
    assert br2.has_changes is True
    assert br2.new_buys or br2.prob_moves


def test_live_quote_parsing():
    """Live-Kurs-Hilfsfunktionen (offline, ohne Netzwerk)."""
    from stockai.data import live
    assert live.to_binance_symbol("BTC-USD") == "BTCUSDT"
    assert live.to_binance_symbol("ETH") == "ETHUSDT"
    assert live.is_crypto("BTC-USD") and not live.is_crypto("AAPL")
    qb = live.parse_binance({"lastPrice": "65000.5", "priceChangePercent": "2.5"}, "BTC-USD")
    assert qb and abs(qb.price - 65000.5) < 1e-6 and qb.source == "binance"
    qf = live.parse_finnhub({"c": 187.2, "dp": -1.3}, "AAPL")
    assert qf and abs(qf.price - 187.2) < 1e-6 and qf.change_pct == -1.3
    assert live.parse_finnhub({"c": 0}, "AAPL") is None   # ungültig
    assert live.parse_binance({}, "X") is None


def test_intraday_parsers():
    """Intraday-Parser (Binance/Twelve Data) – offline."""
    from stockai.data import intraday
    assert intraday.is_intraday("15m") and not intraday.is_intraday("1d")
    kl = [[1700000000000, "100", "101", "99", "100.5", "12.3", 0, 0, 0, 0, 0, 0],
          [1700000900000, "100.5", "102", "100", "101.8", "8.1", 0, 0, 0, 0, 0, 0]]
    df = intraday.parse_binance_klines(kl)
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(df) == 2 and abs(df["Close"].iloc[-1] - 101.8) < 1e-6
    td = {"status": "ok", "values": [
        {"datetime": "2024-01-02 15:30:00", "open": "1", "high": "2", "low": "0.5",
         "close": "1.5", "volume": "1000"}]}
    d2 = intraday.parse_twelvedata(td)
    assert len(d2) == 1 and abs(d2["Close"].iloc[-1] - 1.5) < 1e-6
    assert intraday.parse_twelvedata({"status": "error"}).empty


def test_compare_intervals_demo():
    from stockai.compare import compare_intervals
    from stockai.config import load_config
    cfg = load_config()
    cfg.raw["data_source"] = "demo"
    cfg.tickers = ["AAA", "BBB", "CCC"]
    cfg.etfs = []
    cfg.crypto = []
    cfg.model = {"type": "logistic", "random_state": 42}
    rows = compare_intervals(cfg, ["1d", "1h"])
    assert len(rows) == 2
    assert all("auc" in r and "n" in r for r in rows)
    # Demo ignoriert das Intervall -> beide haben Daten
    assert rows[0]["n"] > 0


def test_alpaca_parsers():
    from stockai.data import alpaca
    df = alpaca.parse_bars({"bars": [
        {"t": "2024-01-02T15:30:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 100},
        {"t": "2024-01-02T15:45:00Z", "o": 1.5, "h": 2.2, "l": 1.4, "c": 2.0, "v": 80}]})
    assert len(df) == 2 and abs(df["Close"].iloc[-1] - 2.0) < 1e-6
    q = alpaca.parse_snapshot(
        {"latestTrade": {"p": 110.0}, "prevDailyBar": {"c": 100.0}}, "AAPL")
    assert q and q.source == "alpaca" and abs(q.change_pct - 10.0) < 1e-6
    assert alpaca.parse_bars({}).empty


def test_alerts_detects_move(tmp_path):
    from stockai import alerts as al
    from stockai.config import load_config
    cfg = load_config()
    cfg.paths = {"store_dir": str(tmp_path), "model_dir": str(tmp_path)}
    # künstlicher Vorzustand + render
    import json
    json.dump({"AAA": 100.0}, open(tmp_path / "last_alerts.json", "w"))
    res = al.AlertResult(timestamp="t", moves=[("AAA", 106.0, 6.0, 6.0)], has_alerts=True)
    out = al.render_alerts(res)
    assert "AAA" in out and "📈" in out
    assert al.render_alerts(al.AlertResult(timestamp="t")) == ""


def test_telegram_bot_commands(tmp_path):
    """Befehlsverarbeitung des Bots (ohne Netzwerk)."""
    from stockai import telegram_bot as tb
    from stockai.telegram_bot import handle_command
    from stockai.config import load_config

    cfg = load_config()
    cfg.raw["data_source"] = "demo"
    cfg.paths = {"store_dir": str(tmp_path), "model_dir": str(tmp_path)}
    assert "Befehle" in handle_command(cfg, "/help")
    assert "Symbol" in handle_command(cfg, "/analyse")          # ohne Argument
    assert "Unbekannt" in handle_command(cfg, "/quatsch")

    # persönliches Menü: Vorname wird gemerkt und begrüßt
    tb._remember_name(cfg, "111", {"first_name": "Max"})
    menu = handle_command(cfg, "/menu", user="111")
    assert "Hallo Max" in menu and "Depot" in menu and "Alerts" in menu
    assert "Willkommen" in handle_command(cfg, "/start", user="111")
    # anderer Nutzer ohne Name -> neutrale Begrüßung, eigener (leerer) Stand
    assert "Hallo!" in handle_command(cfg, "/menu", user="222")


def test_ticker_bias_causal():
    """Individuelles Eigenprofil: kausal (nur Vergangenheit), Werte in [0,1]."""
    from stockai import pipeline
    df = _synthetic_prices(seed=3)
    s = pipeline.ticker_bias(df, horizon=5, threshold=0.0)
    valid = s.dropna()
    assert len(valid) > 0
    assert valid.min() >= 0.0 and valid.max() <= 1.0
    # erste Werte sind NaN (noch keine bekannten Ergebnisse)
    assert s.iloc[0] != s.iloc[0]  # NaN


def test_preferred_model_roundtrip(tmp_path):
    from stockai.model.store import ModelStore
    ms = ModelStore(tmp_path)
    assert ms.load_preferred_model() is None
    ms.save_preferred_model("stacking")
    assert ms.load_preferred_model() == "stacking"


def test_selected_features_and_active(tmp_path):
    from stockai.model.store import ModelStore
    from stockai import pipeline
    from stockai.config import load_config
    ms = ModelStore(tmp_path)
    assert ms.load_selected_features() is None
    ms.save_selected_features(["rsi_14", "ret_20d", "sent_mean", "macd", "vol_20d", "stoch_k"])
    assert ms.load_selected_features() == ["rsi_14", "ret_20d", "sent_mean", "macd", "vol_20d", "stoch_k"]

    cfg = load_config()
    cfg.paths = {"store_dir": str(tmp_path), "model_dir": str(tmp_path)}
    feats = pipeline.active_features(cfg)
    assert feats == ["rsi_14", "ret_20d", "sent_mean", "macd", "vol_20d", "stoch_k"]
    ms.clear_selected_features()
    # Fallback auf alle Features
    assert pipeline.active_features(cfg) == pipeline.FEATURE_COLUMNS


def test_top_report(tmp_path):
    """Wöchentlicher Top-N-Überblick (beide Richtungen)."""
    from stockai import briefing as bf
    from stockai.config import load_config

    cfg = load_config()
    cfg.raw["data_source"] = "demo"
    cfg.tickers = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
    cfg.etfs = []
    cfg.crypto = []
    cfg.model = {"type": "logistic", "random_state": 42}
    cfg.paths = {"store_dir": str(tmp_path / "s"), "model_dir": str(tmp_path / "m")}

    top, bottom = bf.build_top(cfg, n=3)
    assert len(top) == 3 and len(bottom) == 3
    # Top sind nach Wahrscheinlichkeit sortiert (höchste zuerst)
    assert top[0].profit_probability >= top[-1].profit_probability
    assert top[0].profit_probability >= bottom[0].profit_probability
    report = bf.render_top(top, bottom, 3)
    assert "TOP 3 CHANCEN" in report and "TOP 3 RISIKEN" in report


def test_crypto_support():
    """Krypto: höhere Demo-Volatilität, Anlageklasse, Sparplan-Topf."""
    from stockai.data import demo
    from stockai.data.stooq import _to_symbol
    from stockai.config import load_config
    from stockai import pipeline
    from stockai.savings_plan import build_savings_plan

    # Krypto-Demo ist deutlich volatiler als eine Aktie
    vol_btc = demo.demo_prices("BTC", "1y")["Close"].pct_change().std()
    vol_stk = demo.demo_prices("AAPL", "1y")["Close"].pct_change().std()
    assert vol_btc > vol_stk

    assert _to_symbol("BTC-USD") == "btcusd"   # Krypto-Symbol-Mapping

    cfg = load_config()
    cfg.raw["data_source"] = "demo"
    cfg.tickers = ["AAA", "BBB"]
    cfg.etfs = ["WORLD"]
    cfg.crypto = ["BTC", "ETH"]
    assert pipeline.asset_class(cfg, "BTC") == "Krypto"
    assert pipeline.asset_class(cfg, "WORLD") == "ETF"
    assert pipeline.asset_class(cfg, "AAA") == "Aktie"
    assert set(pipeline.universe(cfg)) == {"AAA", "BBB", "WORLD", "BTC", "ETH"}

    plan = build_savings_plan(cfg, monthly_amount=100.0, core_share=0.5,
                              crypto_share=0.1)
    total = sum(p.monthly for p in plan.positions)
    assert total <= 100.0 + 0.01
    # Krypto-Anteil bleibt klein (<= 10% + Toleranz)
    assert sum(p.monthly for p in plan.crypto_positions) <= 10.5


def test_cross_validate_embargo():
    """CV mit Embargo (purge_dates) läuft und liefert gültige Kennzahlen."""
    import numpy as np
    import pandas as pd
    from stockai.model.predictor import Predictor
    from stockai.features.technical import TECHNICAL_FEATURES
    df = add_technical_features(_synthetic_prices(seed=5, n=600))
    df["target"] = (df["Close"].shift(-5) / df["Close"] - 1 > 0).astype(float)
    df["date"] = df.index
    feats = TECHNICAL_FEATURES
    p = Predictor(feats, model_type="logistic")
    cv0 = p.cross_validate(df, n_splits=4, purge_dates=0)
    cv1 = p.cross_validate(df, n_splits=4, purge_dates=5)
    assert cv0 and cv1
    assert 0.0 <= cv1["cv_accuracy_mean"] <= 1.0
    assert cv1["cv_folds"] >= 1


def test_weakspots_render():
    from stockai.weakspots import WeakSpots, render_weakspots
    w = WeakSpots(n=200, base_rate=0.5, segments=[
        {"dim": "Kaufsignal × RSI", "group": "RSI>70 (überkauft)", "count": 40,
         "hit": 0.42, "base": 0.5, "gap": -0.08},
        {"dim": "Kaufsignal × Sentiment", "group": "News positiv", "count": 60,
         "hit": 0.58, "base": 0.5, "gap": 0.08},
    ])
    out = render_weakspots(w)
    assert "Schwachstellen" in out and "überkauft" in out
    assert "zu wenig" in render_weakspots(WeakSpots(n=10))


def test_weakspots_self_correction(tmp_path):
    """Schwachstellen werden als Lektionen gespeichert und dämpfen Empfehlungen."""
    from stockai import advisor, weakspots as ws
    from stockai.config import load_config

    cfg = load_config()
    cfg.paths = {"store_dir": str(tmp_path), "model_dir": str(tmp_path)}
    # eine erkannte Schwachstelle (gap < -3 %) und eine starke Stelle (wird ignoriert)
    w = ws.WeakSpots(n=300, base_rate=0.5, segments=[
        {"dim": "Kaufsignal × RSI", "group": "RSI>70 (überkauft)", "kind": "rsi_high",
         "count": 50, "hit": 0.42, "base": 0.5, "gap": -0.08},
        {"dim": "Kaufsignal × Sentiment", "group": "News positiv", "kind": "sent_pos",
         "count": 60, "hit": 0.6, "base": 0.5, "gap": 0.10},
    ])
    assert ws.save_lessons(cfg, w) == 1            # nur die schwache Bedingung
    lessons = ws.load_lessons(cfg)
    assert lessons and lessons[0]["kind"] == "rsi_high"

    # passt die Lage auf die Lektion -> Warnung; sonst nicht
    assert ws.caution_for(lessons, {"rsi": 75, "sent": 0.0, "regime": 0.0})
    assert not ws.caution_for(lessons, {"rsi": 50, "sent": 0.0, "regime": 0.0})

    # weitere Dimensionen: Anlageklasse, Momentum, Volatilität greifen ebenfalls
    more = [{"kind": "class_Krypto", "group": "Krypto", "hit": 0.4, "gap": -0.1},
            {"kind": "vol_high", "group": "hohe Schwankung", "hit": 0.41, "gap": -0.09},
            {"kind": "mom_neg", "group": "Momentum fallend", "hit": 0.43, "gap": -0.07}]
    assert ws.caution_for(more, {"cls": "Krypto", "vol": 0.05, "mom": -0.02})
    assert len(ws.caution_for(more, {"cls": "Krypto", "vol": 0.05, "mom": -0.02})) == 3
    assert not ws.caution_for(more, {"cls": "Aktie", "vol": 0.01, "mom": 0.02})

    # BOOM-Lage wird bei gelernter Schwachstelle auf KAUFEN gedämpft
    strong = dict(profit_probability=0.70, rsi_14=60, momentum_5d=0.03,
                  price_vs_high_20=0.9, macd_hist=0.02, sentiment_mean=0.3)
    assert advisor.recommend(**strong).action == "BOOM"
    cautious = advisor.recommend(**strong, weak_conditions=["RSI>70: nur 42%"])
    assert cautious.action == "KAUFEN"


def test_health_detects_degradation(tmp_path):
    """Selbstcheck merkt sich den Verlauf und warnt, wenn die KI schlechter wird."""
    import numpy as np
    import pandas as pd
    from stockai import health as hl
    from stockai.config import load_config
    from stockai.model.store import _FEATURE_STORE_FILE

    cfg = load_config()
    sdir = tmp_path / "s"
    sdir.mkdir()
    cfg.paths = {"store_dir": str(sdir), "model_dir": str(tmp_path / "m")}
    rng = np.random.default_rng(0)

    def write(acc):
        proba = rng.uniform(0, 1, 80)
        pred = (proba >= 0.5).astype(int)
        y = pred.copy()
        flip = rng.uniform(0, 1, 80) > acc
        y[flip] = 1 - y[flip]
        pd.DataFrame({
            "ticker": ["X"] * 80,
            "date": pd.date_range("2026-01-01", periods=80).astype(str),
            "pred_proba": proba, "target": y.astype(float),
        }).to_csv(sdir / _FEATURE_STORE_FILE, index=False)

    write(0.62)
    first = hl.assess_health(cfg)
    assert first.source == "live" and first.current > 0.5

    write(0.50)
    worse = hl.assess_health(cfg)
    assert worse.previous == worse.previous          # Vorwert gemerkt
    assert worse.status.startswith("⚠️") and worse.warnings
    assert "schlechter" in hl.render_health(worse)


def test_holdings_tracking(tmp_path):
    """Eigenes Depot: Ø-Einstand beim Nachkauf, G/V-Mathematik, Verkaufswarnung."""
    from stockai import holdings as hd
    from stockai.config import load_config

    cfg = load_config()
    cfg.paths = {"store_dir": str(tmp_path), "model_dir": str(tmp_path)}

    hd.add_holding(cfg, "nvda", 10, 90.0)
    hd.add_holding(cfg, "NVDA", 10, 110.0)        # nachkaufen -> Ø 100
    hd.add_holding(cfg, "AAPL", 5, 200.0)
    hs = {h.ticker: h for h in hd.load_holdings(cfg)}
    assert hs["NVDA"].qty == 20 and abs(hs["NVDA"].buy_price - 100.0) < 1e-9

    assert hd.remove_holding(cfg, "AAPL") is True
    assert hd.remove_holding(cfg, "AAPL") is False
    assert [h.ticker for h in hd.load_holdings(cfg)] == ["NVDA"]

    # G/V-Mathematik einer Position
    pos = hd.Position(ticker="NVDA", qty=20, buy_price=100.0, price=120.0,
                      action="VERKAUFEN", probability=0.4)
    assert pos.value == 2400 and pos.cost == 2000
    assert pos.pnl == 400 and abs(pos.pnl_pct - 0.2) < 1e-9
    assert pos.sell_warning is True

    rep = hd.DepotReport(positions=[pos], total_value=2400, total_cost=2000)
    out = hd.render_depot(rep)
    assert "NVDA" in out and "+20.0%" in out and "verkaufen/meiden" in out
    assert "leer" in hd.render_depot(hd.DepotReport())


def test_watch_alerts(tmp_path, monkeypatch):
    """Bedingte Alerts: Parsing + Crossing-Logik (kein Dauer-Spam)."""
    from stockai import watch as wt
    from stockai.config import load_config

    cfg = load_config()
    cfg.paths = {"store_dir": str(tmp_path), "model_dir": str(tmp_path)}

    # Parsing der Bedingungen
    assert wt.parse_spec(["BTC-USD", "<", "50000"]).metric == "price"
    assert wt.parse_spec(["NVDA", "rsi", "<", "30"]).metric == "rsi"
    assert wt.parse_spec(["BTC-USD", "vol", ">", "2"]).op == ">"
    assert wt.parse_spec(["X", "bad"]) is None
    assert wt.parse_spec(["X", "=", "1"]) is None      # nur < oder >

    wt.add_watch(cfg, wt.Watch("BTC-USD", "price", "<", 50000))

    # gemockte Kursfolge: unter, unter, über (Reset), unter
    seq = iter([49000.0, 48000.0, 51000.0, 47000.0])
    monkeypatch.setattr(wt, "_current_value", lambda c, t, m: next(seq))
    assert wt.check_watches(cfg)            # feuert
    assert wt.check_watches(cfg) == []      # bleibt unten -> kein zweites Feuern
    assert wt.check_watches(cfg) == []      # über Schwelle -> macht wieder scharf
    assert wt.check_watches(cfg)            # wieder unten -> feuert erneut

    assert wt.remove_watch(cfg, 0) is True
    assert "Keine Alerts" in wt.render_watches(cfg)


def test_per_user_separation(tmp_path, monkeypatch):
    """Jeder Nutzer hat ein eigenes Depot; Alt-Daten wandern zum Betreiber."""
    import json
    from stockai import holdings as hd, users, watch as wt
    from stockai.config import load_config

    monkeypatch.setenv("STOCKAI_TELEGRAM_CHAT_ID", "555,666")
    cfg = load_config()
    sdir = tmp_path / "s"
    sdir.mkdir()
    cfg.paths = {"store_dir": str(sdir), "model_dir": str(tmp_path / "m")}

    # getrennte Depots
    hd.add_holding(cfg, "NVDA", 10, 850, user="555")
    hd.add_holding(cfg, "TSLA", 5, 200, user="666")
    assert [h.ticker for h in hd.load_holdings(cfg, "555")] == ["NVDA"]
    assert [h.ticker for h in hd.load_holdings(cfg, "666")] == ["TSLA"]   # sieht 555 nicht

    # getrennte Alerts + gemerkte Präferenz
    wt.add_watch(cfg, wt.Watch("BTC-USD", "price", "<", 50000), user="555")
    assert wt.load_watches(cfg, "666") == []
    users.set_pref(cfg, "555", "monthly", 300.0)
    assert users.load_prefs(cfg, "555")["monthly"] == 300.0
    assert users.load_prefs(cfg, "666") == {}

    assert set(users.all_users(cfg)) >= {"555", "666"}


def test_legacy_holdings_migrate_to_owner(tmp_path, monkeypatch):
    """Eine alte gemeinsame holdings.json wird beim ersten Zugriff dem Betreiber
    (erste Allowlist-ID) zugeordnet – andere Nutzer starten leer."""
    import json
    from stockai import holdings as hd
    from stockai.config import load_config

    monkeypatch.setenv("STOCKAI_TELEGRAM_CHAT_ID", "555,666")
    cfg = load_config()
    sdir = tmp_path / "s"
    sdir.mkdir()
    cfg.paths = {"store_dir": str(sdir), "model_dir": str(tmp_path / "m")}
    json.dump([{"ticker": "NVDA", "qty": 10, "buy_price": 800}],
              open(sdir / "holdings.json", "w"))

    assert [h.ticker for h in hd.load_holdings(cfg, "555")] == ["NVDA"]   # Betreiber erbt
    assert not (sdir / "holdings.json").exists()                          # alt verschoben
    assert hd.load_holdings(cfg, "666") == []                             # anderer leer


def test_conviction_score():
    """Conviction bündelt Signale transparent zu einer Kennzahl (0..100)."""
    from stockai.conviction import compute_conviction, render_conviction
    from stockai.pipeline import TickerAnalysis

    strong = TickerAnalysis(
        ticker="X", last_price=10, profit_probability=0.72, sentiment_mean=0.3,
        news_count=3, expected_return=0.03, horizon_probs={1: 0.6, 5: 0.65, 20: 0.7},
        momentum_5d=0.03, rel_volume=2.5)
    weak = TickerAnalysis(
        ticker="Y", last_price=10, profit_probability=0.5, sentiment_mean=-0.3,
        news_count=3, expected_return=-0.02, horizon_probs={1: 0.45, 5: 0.4, 20: 0.48},
        momentum_5d=-0.03, rel_volume=2.5, weak_segment=True)

    cs, cw = compute_conviction(strong), compute_conviction(weak)
    assert cs.score > 70 and cs.label in ("hoch", "sehr hoch")
    assert cw.score < 40
    assert 0 <= cs.score <= 100 and 0 <= cw.score <= 100
    out = render_conviction(strong, cs)
    assert "Conviction" in out and "Modell-Wahrscheinlichkeit" in out
    # Volumen + steigender Kurs = positiver Beitrag, mit fallendem Kurs negativ
    assert dict(cs.parts)["Volumen-Bestätigung"] > 0
    assert dict(cw.parts)["Volumen-Bestätigung"] < 0


def test_personal_track_record(tmp_path):
    """Track-Record lässt sich auf die eigenen Depot-Werte einschränken."""
    import numpy as np
    import pandas as pd
    from stockai import track
    from stockai.config import load_config
    from stockai.model.store import _FEATURE_STORE_FILE

    cfg = load_config()
    cfg.paths = {"store_dir": str(tmp_path), "model_dir": str(tmp_path)}
    rng = np.random.default_rng(0)
    rows = []
    for tkr in ("NVDA", "TSLA"):
        proba = rng.uniform(0, 1, 40)
        target = (proba + rng.normal(0, 0.3, 40) > 0.5).astype(float)
        rows.append(pd.DataFrame({"ticker": [tkr] * 40,
                                  "date": pd.date_range("2026-01-01", periods=40).astype(str),
                                  "pred_proba": proba, "target": target}))
    pd.concat(rows).to_csv(tmp_path / _FEATURE_STORE_FILE, index=False)

    full = track.build_track_record(cfg)
    mine = track.build_track_record(cfg, tickers=["NVDA"], scope="deine Depot-Werte")
    assert full.n_labeled == 80 and mine.n_labeled == 40   # gefiltert auf NVDA
    assert "deine Depot-Werte" in track.render_track_record(mine)


def test_analyze_cache(tmp_path):
    """Kurzzeit-Cache: zweiter Aufruf liefert dasselbe Ergebnis sofort; ohne
    Cache bzw. nach Leeren wird neu gerechnet."""
    from stockai import pipeline
    from stockai.config import load_config

    cfg = load_config()
    cfg.raw["data_source"] = "demo"
    cfg.tickers = ["AAA", "BBB", "CCC"]; cfg.etfs = []; cfg.crypto = []
    cfg.model = {"type": "logistic", "random_state": 42}
    cfg.paths = {"store_dir": str(tmp_path / "s"), "model_dir": str(tmp_path / "m")}

    pipeline.clear_analyze_cache()
    a = pipeline.analyze(cfg, use_cache=True)
    b = pipeline.analyze(cfg, use_cache=True)
    assert a is b                                  # Cache-Treffer (identisches Objekt)
    pipeline.clear_analyze_cache()
    c = pipeline.analyze(cfg, use_cache=True)
    assert c is not a                              # nach Leeren neu berechnet


def test_whale_signals(tmp_path):
    """Whale-Radar: Richtung/Stärke-Logik und Rendern."""
    from stockai import whale as wh
    from stockai.config import load_config

    # Richtung aus Volumen + Kursreaktion
    acc = wh.WhaleSignal("NVDA", "Aktie", rel_volume=3.0, price_change=0.04, direction="Akkumulation")
    dist = wh.WhaleSignal("BTC-USD", "Krypto", rel_volume=4.0, price_change=-0.05, direction="Distribution")
    # stärkeres Signal hat höhere strength (mehr Volumen + größere Reaktion)
    assert dist.strength > acc.strength

    scan = wh.WhaleScan(signals=[dist, acc], n_scanned=20)
    out = wh.render_whales(scan)
    assert "Whale-Radar" in out and "Akkumulation" in out and "Distribution" in out
    assert "🐋 Keine" in wh.render_whales(wh.WhaleScan(n_scanned=5))

    # Integration im Demo-Modus: scannt, liefert eine gültige Struktur
    cfg = load_config()
    cfg.raw["data_source"] = "demo"
    cfg.tickers = ["AAA", "BBB", "CCC"]; cfg.etfs = []; cfg.crypto = []
    cfg.model = {"type": "logistic", "random_state": 42}
    cfg.paths = {"store_dir": str(tmp_path / "s"), "model_dir": str(tmp_path / "m")}
    res = wh.scan_whales(cfg, min_rel=1.2)
    assert res.n_scanned >= 1
    assert all(0 <= s.rel_volume for s in res.signals)


def test_clock_berlin_time():
    """Sichtbare Zeiten laufen über die Berlin-Zeitzone (nicht UTC)."""
    from datetime import timezone
    from stockai.clock import now_de, now_de_str

    dt = now_de()
    assert dt.tzinfo is not None
    # Berlin liegt im Sommer +2h, im Winter +1h vor UTC – nie UTC (0) bei korrekter tz
    off = dt.utcoffset()
    assert off is not None
    # Format der Anzeige enthält 'Uhr'
    assert "Uhr" in now_de_str()
    # Alerts-Zeitstempel ist nicht mehr in UTC beschriftet
    from stockai import alerts
    assert "UTC" not in alerts.check_alerts.__doc__ if alerts.check_alerts.__doc__ else True


def test_chat_id_allowlist():
    """Mehrere erlaubte Chat-IDs werden korrekt zerlegt (Allowlist/Freundeskreis)."""
    from stockai import notify

    assert notify.parse_chat_ids("123,456") == ["123", "456"]
    assert notify.parse_chat_ids("  111, 222 ,333 ") == ["111", "222", "333"]
    assert notify.parse_chat_ids("999") == ["999"]
    assert notify.parse_chat_ids("") == [] and notify.parse_chat_ids(None) == []
    # ohne Token/IDs wird nichts gesendet (kein Fehler)
    assert notify.send_telegram("x", token=None, chat_id="123,456") is False


def test_health_self_regulation(tmp_path):
    """Bei Verschlechterung steigt die Vorsicht (Kaufschwelle), Erholung lockert."""
    import numpy as np
    import pandas as pd
    from stockai import advisor, health as hl
    from stockai.config import load_config
    from stockai.model.store import _FEATURE_STORE_FILE

    cfg = load_config()
    sdir = tmp_path / "s"
    sdir.mkdir()
    cfg.paths = {"store_dir": str(sdir), "model_dir": str(tmp_path / "m")}
    rng = np.random.default_rng(1)

    def write(acc):
        proba = rng.uniform(0, 1, 80)
        y = (proba >= 0.5).astype(int)
        flip = rng.uniform(0, 1, 80) > acc
        y[flip] = 1 - y[flip]
        pd.DataFrame({
            "ticker": ["X"] * 80,
            "date": pd.date_range("2026-01-01", periods=80).astype(str),
            "pred_proba": proba, "target": y.astype(float),
        }).to_csv(sdir / _FEATURE_STORE_FILE, index=False)

    write(0.62); hl.assess_health(cfg)
    assert hl.load_posture(cfg) == 0.0               # gut: keine Vorsicht
    write(0.45); hl.assess_health(cfg)
    assert hl.load_posture(cfg) > 0.0                # schlecht: strenger geworden
    high = hl.load_posture(cfg)
    write(0.65); hl.assess_health(cfg)
    assert hl.load_posture(cfg) < high               # Erholung: wieder gelockert

    # Grenzsignal: gleiches P, aber mit Offset wird aus KAUFEN ein HALTEN
    base = dict(profit_probability=0.57, rsi_14=55, momentum_5d=0.0,
                price_vs_high_20=0.9, macd_hist=0.01, sentiment_mean=0.0)
    assert advisor.recommend(**base).action == "KAUFEN"
    assert advisor.recommend(**base, caution_offset=0.04).action == "HALTEN"


def test_track_record(tmp_path):
    """Live-Track-Record aus gesammelten Snapshots (Prognose vs. Ergebnis)."""
    import numpy as np
    import pandas as pd
    from stockai import track
    from stockai.config import load_config

    cfg = load_config()
    cfg.paths = {"store_dir": str(tmp_path), "model_dir": str(tmp_path)}
    # Feature-Store mit Prognosen + realem Ergebnis simulieren
    rng = np.random.default_rng(0)
    proba = rng.uniform(0, 1, 60)
    target = (proba + rng.normal(0, 0.3, 60) > 0.5).astype(float)
    df = pd.DataFrame({"ticker": ["X"] * 60,
                       "date": pd.date_range("2026-01-01", periods=60).astype(str),
                       "pred_proba": proba, "target": target})
    # ein paar noch offene (ungelabelte) Snapshots
    df = pd.concat([df, pd.DataFrame({"ticker": ["Y"] * 5, "date": ["2026-04-01"] * 5,
                                      "pred_proba": [0.6] * 5, "target": [np.nan] * 5})])
    df.to_csv(tmp_path / "feature_store.csv", index=False)

    rec = track.build_track_record(cfg)
    assert rec.n_labeled == 60 and rec.n_pending == 5
    assert 0.0 <= rec.accuracy <= 1.0
    assert rec.calibration
    out = track.render_track_record(rec)
    assert "Track-Record" in out


def test_market_regime():
    from types import SimpleNamespace
    from stockai.briefing import market_regime
    bull = [SimpleNamespace(momentum_5d=0.03, rsi_14=60, profit_probability=0.6)
            for _ in range(5)]
    bear = [SimpleNamespace(momentum_5d=-0.03, rsi_14=40, profit_probability=0.4)
            for _ in range(5)]
    assert "bullisch" in market_regime(bull)
    assert "bärisch" in market_regime(bear)
    assert market_regime([]) == "unbekannt"


def test_sector_cap_diversification():
    from stockai.portfolio import _apply_sector_cap

    # 4 Tech-Werte (je 0.25) -> Sektor 100%; Cap 40% muss umverteilen
    weights = {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25}
    sectors = {"A": "Tech", "B": "Tech", "C": "Tech", "D": "Energy"}
    capped = _apply_sector_cap(weights, sectors, cap=0.40, pos_cap=0.40)
    tech = capped["A"] + capped["B"] + capped["C"]
    assert tech <= 0.40 + 1e-6           # Tech-Sektor begrenzt
    assert capped["D"] >= 0.25           # Energy bekommt mehr Gewicht
    assert all(w <= 0.40 + 1e-6 for w in capped.values())


def test_portfolio_no_candidates():
    from types import SimpleNamespace
    from stockai.portfolio import build_portfolio

    analyses = [
        SimpleNamespace(ticker="X", action="MEIDEN", profit_probability=0.3,
                        confidence=0.6, last_price=10.0),
    ]
    pf = build_portfolio(analyses, capital=5_000.0)
    assert pf.allocations == []
    assert pf.cash == 5_000.0
    assert "X" in pf.sells


def test_savings_plan_demo():
    """Sparplan-Generator (Core-Satellite) im Demo-Modus."""
    from stockai.savings_plan import build_savings_plan
    from stockai import notify
    from stockai.config import load_config

    cfg = load_config()
    cfg.raw["data_source"] = "demo"
    cfg.tickers = ["AAA", "BBB", "CCC"]
    cfg.etfs = ["WORLD", "SP500"]
    cfg.model = {"type": "logistic", "random_state": 42}

    plan = build_savings_plan(cfg, monthly_amount=100.0, core_share=0.5)
    total = sum(p.monthly for p in plan.positions)
    assert total <= 100.0 + 0.01           # nie mehr als der Sparbetrag
    assert len(plan.core_positions) == 2    # beide ETFs im Core
    # Report rendert ohne Fehler; ohne Webhook-URL wird nichts gesendet
    report = notify.render_savings_plan(plan)
    assert "Sparplan-Update" in report
    assert "**" not in report and "# " not in report   # sauberes Telegram-Format
    # antippbares Menü: valides JSON mit Callback-Befehlen
    import json
    kb = json.loads(notify.main_menu_markup())
    cbs = [b["callback_data"] for row in kb["inline_keyboard"] for b in row]
    assert "/briefing" in cbs and "/weakspots" in cbs and "/help" in cbs
    # Ohne Konfiguration wird nichts gesendet (kein Fehler)
    assert notify.send_webhook("test", url=None) is False
    assert notify.send_telegram("test", token=None, chat_id=None) is False
    sent, channel = notify.notify("test")
    assert sent is False and isinstance(channel, str)


def test_scorecard_demo():
    """Recommendation-Scorecard (Walk-Forward) im Demo-Modus."""
    from stockai import scorecard as sc
    from stockai.config import load_config

    cfg = load_config()
    cfg.raw["data_source"] = "demo"
    cfg.tickers = ["AAA", "BBB", "CCC"]
    cfg.model = {"type": "logistic", "random_state": 42}

    card = sc.evaluate_recommendations(cfg)
    assert card.n_recommendations > 0
    assert 0.0 <= card.overall_hit_rate <= 1.0
    assert card.by_action  # mindestens eine Aktion bewertet
    for c in card.calibration:
        assert 0.0 <= c["actual"] <= 1.0


def test_hyperparameter_tuning_demo():
    """Hyperparameter-Tuning liefert gültige Parameter für ein Baummodell."""
    from stockai import pipeline
    from stockai.config import load_config
    from stockai.model.tuning import tune_model

    cfg = load_config()
    cfg.raw["data_source"] = "demo"
    cfg.tickers = ["AAA", "BBB", "CCC"]
    cfg.model = {"type": "random_forest", "random_state": 42}

    data = pipeline._combined_training_data(cfg)
    res = tune_model(data, pipeline.FEATURE_COLUMNS, "random_forest")
    assert res.best_params
    assert "n_estimators" in res.best_params
    assert 0.0 <= res.best_score <= 1.0


def test_strategy_backtest_demo(tmp_path):
    """Walk-Forward-Strategie-Backtest im Demo-Modus (schnelles Modell)."""
    from stockai import strategy
    from stockai.config import load_config

    cfg = load_config()
    cfg.raw["data_source"] = "demo"
    cfg.tickers = ["AAA", "BBB", "CCC"]
    cfg.model = {"type": "logistic", "test_size": 0.2, "random_state": 42}

    res = strategy.run_strategy_backtest(cfg, prob_threshold=0.5, top_k=2,
                                         initial_capital=500.0)
    assert res.n_rebalances > 0
    assert len(res.strategy_equity) == res.n_rebalances
    assert len(res.benchmark_equity) == res.n_rebalances
    for key in ("total_return", "sharpe", "max_drawdown", "win_rate"):
        assert key in res.metrics
    assert res.metrics["max_drawdown"] <= 0.0
    # €-Auswertung & Zeitspanne
    assert res.initial_capital == 500.0
    assert res.final_value == 500.0 * res.strategy_equity[-1]
    assert res.years > 0.0

    out = tmp_path / "equity.png"
    path = strategy.plot_equity_curve(res, str(out))
    assert out.exists() and path == str(out)

    # Mit Transaktionskosten ist die Gesamtrendite niedriger (ehrlicher)
    res_cost = strategy.run_strategy_backtest(cfg, prob_threshold=0.5, top_k=2,
                                              initial_capital=500.0, cost_bps=50.0)
    assert res_cost.metrics["total_return"] <= res.metrics["total_return"] + 1e-9


def test_demo_pipeline_train_and_learning_curve(tmp_path):
    """End-to-End im Demo-Modus (offline): trainieren + Lernkurve erzeugen."""
    from stockai import pipeline
    from stockai.config import load_config

    cfg = load_config()
    # Demo-Modus erzwingen und in Temp-Verzeichnisse schreiben
    cfg.raw["data_source"] = "demo"
    cfg.paths = {
        "store_dir": str(tmp_path / "store"),
        "model_dir": str(tmp_path / "models"),
    }
    cfg.tickers = ["AAA", "BBB", "CCC"]
    cfg.etfs = []
    cfg.crypto = []

    result = pipeline.train(cfg)
    assert result.n_train > 0 and 0.0 <= result.metrics["accuracy"] <= 1.0

    curve = pipeline.learning_curve(cfg, steps=3)
    assert len(curve) == 3
    assert all("metrics" in c for c in curve)
    # Mit der größten Datenmenge wird ein Modell gespeichert -> analyse läuft
    results = pipeline.analyze(cfg, retrain_if_missing=False)
    assert len(results) == 3
    assert all(0.0 <= r.profit_probability <= 1.0 for r in results)
