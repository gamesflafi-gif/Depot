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
    df = df.dropna(subset=FEATURE_COLUMNS + ["target"])
    pred = Predictor(FEATURE_COLUMNS, model_type="logistic")
    result = pred.train(df, test_size=0.2)
    assert 0.0 <= result.metrics["accuracy"] <= 1.0
    proba = pred.predict_proba(df.head(5))
    assert ((proba >= 0) & (proba <= 1)).all()


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

    result = pipeline.train(cfg)
    assert result.n_train > 0 and 0.0 <= result.metrics["accuracy"] <= 1.0

    curve = pipeline.learning_curve(cfg, steps=3)
    assert len(curve) == 3
    assert all("metrics" in c for c in curve)
    # Mit der größten Datenmenge wird ein Modell gespeichert -> analyse läuft
    results = pipeline.analyze(cfg, retrain_if_missing=False)
    assert len(results) == 3
    assert all(0.0 <= r.profit_probability <= 1.0 for r in results)
