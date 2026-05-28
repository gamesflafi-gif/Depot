"""Synthetischer Demo-Datengenerator (offline, ohne Netzwerk).

Wird genutzt, wenn ``data_source: demo`` gesetzt ist – z.B. in gesperrten
Netzwerkumgebungen oder zum Ausprobieren der Lern-Logik. Die Daten sind pro
Ticker deterministisch (stabil über mehrere Aufrufe), damit das Labeling von
Snapshots konsistent funktioniert.
"""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

from stockai.data.news import NewsItem

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


def _period_to_days(period: str) -> int:
    period = period.strip().lower()
    mapping = {"1y": 252, "2y": 504, "5y": 1260, "6mo": 126, "3mo": 63, "max": 1260}
    return mapping.get(period, 504)


def demo_prices(ticker: str, period: str = "2y", interval: str = "1d") -> pd.DataFrame:
    """Erzeugt realistische synthetische OHLCV-Daten (Geometric Brownian Motion)."""
    n = _period_to_days(period)
    rng = np.random.default_rng(_seed(ticker))
    # leichter, ticker-spezifischer Drift + Volatilität
    drift = rng.uniform(-0.0003, 0.0009)
    vol = rng.uniform(0.012, 0.028)
    rets = rng.normal(drift, vol, n)
    # gelegentliche "News-Schocks" für Realismus
    shocks = rng.choice([0, 1], size=n, p=[0.97, 0.03]) * rng.normal(0, 0.05, n)
    rets = rets + shocks
    start = rng.uniform(40, 400)
    close = start * np.cumprod(1 + rets)

    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    daily_range = np.abs(rng.normal(0, vol, n)) * close
    df = pd.DataFrame(
        {
            "Open": close * (1 + rng.normal(0, vol / 2, n)),
            "High": close + daily_range,
            "Low": close - daily_range,
            "Close": close,
            "Volume": rng.integers(1_000_000, 8_000_000, n).astype(float),
        },
        index=idx,
    )
    df.index.name = "Date"
    return df


def demo_news(ticker: str, limit: int = 25) -> list[NewsItem]:
    """Erzeugt eine gemischte Menge synthetischer Schlagzeilen."""
    rng = np.random.default_rng(_seed(ticker) + 7)
    n = min(limit, rng.integers(4, 9))
    items: list[NewsItem] = []
    pools = [(_POS_TEMPLATES, "pos"), (_NEG_TEMPLATES, "neg"), (_NEUTRAL_TEMPLATES, "neu")]
    for _ in range(n):
        templates, _kind = pools[rng.integers(0, len(pools))]
        title = templates[rng.integers(0, len(templates))].format(t=ticker)
        items.append(
            NewsItem(
                ticker=ticker,
                title=title,
                summary="",
                link="https://example.local/news",
                published=None,
                source="demo",
            )
        )
    return items
