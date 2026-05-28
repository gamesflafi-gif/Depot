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
