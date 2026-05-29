"""Synthetischer Demo-Datengenerator (offline, ohne Netzwerk).

Wird genutzt, wenn ``data_source: demo`` gesetzt ist – z.B. in gesperrten
Netzwerkumgebungen oder zum Ausprobieren der Lern-Logik. Die Daten sind pro
Ticker deterministisch (stabil über mehrere Aufrufe), damit das Labeling von
Snapshots konsistent funktioniert.
"""
from __future__ import annotations

import hashlib
from functools import lru_cache

import numpy as np
import pandas as pd

from stockai.data.news import NewsItem
from stockai.features.sentiment import SENTIMENT_FEATURES

_POS_TEMPLATES = [
    "{t} beats earnings expectations, shares rally",
    "{t} unveils record sales and strong growth outlook",
    "Analysts upgrade {t} on booming demand",
    "{t} announces major partnership, investors optimistic",
]
_NEG_TEMPLATES = [
    "{t} misses revenue targets, stock slides",
    "Regulators probe {t} amid fraud concerns",
    "{t} cuts guidance as costs surge",
    "Lawsuit weighs on {t}, analysts cautious",
]
_NEUTRAL_TEMPLATES = [
    "{t} to report quarterly results next week",
    "{t} holds annual shareholder meeting",
    "What investors should know about {t} today",
]


def _seed(ticker: str) -> int:
    return int(hashlib.sha256(ticker.encode()).hexdigest(), 16) % (2**32)


# Länge der kanonischen Vollreihe (Business-Tage); alle Zeiträume werden als
# Ausschnitt hieraus gebildet, damit sie konsistent zueinander sind.
_CANONICAL_DAYS = 756  # ~3 Jahre


def _period_to_days(period: str) -> int:
    period = period.strip().lower()
    mapping = {"1y": 252, "2y": 504, "5y": 1260, "6mo": 126, "3mo": 63, "max": 1260}
    return mapping.get(period, 504)


@lru_cache(maxsize=64)
def _canonical_arrays(ticker: str) -> tuple:
    """Berechnet (einmalig je Ticker) Index, Close-Reihe und verborgene Drift.

    Die persistente AR(1)-Drift (Trend-Regime) ist die treibende, *vorhersagende*
    Größe: Sie bestimmt sowohl die künftige Kursrichtung als auch – über
    ``demo_sentiment_*`` – das News-Sentiment. Dadurch ist das News-Signal ein
    echter, lernbarer Frühindikator, der mit der Kursentwicklung zusammenhängt.
    """
    n = _CANONICAL_DAYS
    rng = np.random.default_rng(_seed(ticker))
    base_vol = rng.uniform(0.011, 0.016)

    drift = np.zeros(n)
    d = rng.normal(0, 0.0012)
    for i in range(n):
        d = 0.985 * d + rng.normal(0, 0.0012)
        d = float(np.clip(d, -0.007, 0.007))
        drift[i] = d
    rets = drift + rng.normal(0, base_vol, n)
    shocks = rng.choice([0, 1], size=n, p=[0.985, 0.015]) * rng.normal(0, 0.05, n)
    rets = rets + shocks
    start = rng.uniform(40, 400)
    close = start * np.cumprod(1 + rets)
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    return idx, close, drift, base_vol


def _canonical_series(ticker: str) -> pd.DataFrame:
    """Vollständige, deterministische OHLCV-Reihe eines Tickers."""
    idx, close, _drift, base_vol = _canonical_arrays(ticker)
    n = len(close)
    rng = np.random.default_rng(_seed(ticker) + 1)
    daily_range = np.abs(rng.normal(0, base_vol, n)) * close
    df = pd.DataFrame(
        {
            "Open": close * (1 + rng.normal(0, base_vol / 2, n)),
            "High": close + daily_range,
            "Low": close - daily_range,
            "Close": close,
            "Volume": rng.integers(1_000_000, 8_000_000, n).astype(float),
        },
        index=idx,
    )
    df.index.name = "Date"
    return df


def demo_prices(ticker: str, period: str = "2y", interval: str = "1d") -> pd.DataFrame:
    """Liefert das angeforderte Zeitfenster der kanonischen Ticker-Reihe."""
    n = _period_to_days(period)
    return _canonical_series(ticker).iloc[-n:].copy()


# --------------------------------------------------------------------------- #
# News-Sentiment (an das verborgene Trend-Regime gekoppelt)
# --------------------------------------------------------------------------- #
def _sentiment_mean_series(ticker: str) -> tuple:
    """Tägliches mittleres Sentiment, gekoppelt an die Drift (+ Rauschen)."""
    idx, _close, drift, _vol = _canonical_arrays(ticker)
    rng = np.random.default_rng(_seed(ticker) + 13)
    # tanh-Mapping der Drift auf [-1,1] + Rauschen -> realistisches, verrauschtes
    # aber vorhersagekräftiges News-Signal
    sent = np.tanh(drift * 90.0) + rng.normal(0, 0.18, len(drift))
    sent = np.clip(sent, -1.0, 1.0)
    return idx, sent


def _sentiment_features_from_mean(s: float, rng) -> dict:
    """Leitet aus einem mittleren Sentiment die aggregierten Feature-Werte ab."""
    n = int(4 + round(4 * abs(s)) + rng.integers(0, 3))
    return {
        "news_count": float(n),
        "sent_mean": float(s),
        "sent_pos_ratio": float(np.clip(0.5 + 0.5 * s, 0.0, 1.0)),
        "sent_neg_ratio": float(np.clip(0.5 - 0.5 * s, 0.0, 1.0)),
        "sent_max": float(np.clip(s + 0.3, -1.0, 1.0)),
        "sent_min": float(np.clip(s - 0.3, -1.0, 1.0)),
    }


def demo_sentiment_history(ticker: str) -> pd.DataFrame:
    """Historische, tagesgenaue Sentiment-Features (für das Modell-Training)."""
    idx, sent = _sentiment_mean_series(ticker)
    rng = np.random.default_rng(_seed(ticker) + 17)
    rows = [_sentiment_features_from_mean(float(s), rng) for s in sent]
    df = pd.DataFrame(rows, index=idx)
    df.index.name = "Date"
    return df


def demo_sentiment_today(ticker: str) -> dict:
    """Aktuelle Sentiment-Features (konsistent zur Historie)."""
    _idx, sent = _sentiment_mean_series(ticker)
    rng = np.random.default_rng(_seed(ticker) + 19)
    return _sentiment_features_from_mean(float(sent[-1]), rng)


def demo_news(ticker: str, limit: int = 25) -> list[NewsItem]:
    """Schlagzeilen, deren Polarität zum aktuellen Sentiment passt (für Anzeige)."""
    rng = np.random.default_rng(_seed(ticker) + 7)
    _idx, sent = _sentiment_mean_series(ticker)
    s = float(sent[-1])
    n = int(min(limit, 4 + round(4 * abs(s)) + rng.integers(0, 3)))
    # Wahrscheinlichkeiten je nach Sentiment gewichten (pos, neg, neutral)
    pos = np.clip(0.3 + 0.5 * s, 0.05, 0.85)
    neg = np.clip(0.3 - 0.5 * s, 0.05, 0.85)
    neu = max(0.05, 1.0 - pos - neg)
    probs = np.array([pos, neg, neu]); probs = probs / probs.sum()
    pools = [_POS_TEMPLATES, _NEG_TEMPLATES, _NEUTRAL_TEMPLATES]

    items: list[NewsItem] = []
    for _ in range(n):
        kind = int(rng.choice([0, 1, 2], p=probs))
        templates = pools[kind]
        title = templates[rng.integers(0, len(templates))].format(t=ticker)
        items.append(
            NewsItem(ticker=ticker, title=title, summary="",
                     link="https://example.local/news", published=None, source="demo")
        )
    return items
