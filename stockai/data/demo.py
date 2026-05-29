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
    """Erzeugt synthetische OHLCV-Daten mit einem *lernbaren* Trend-Signal.

    Im Gegensatz zu reinem Random-Walk besitzt die Serie eine persistente,
    langsam wandernde Drift (Trend-/Momentum-Regime, AR(1)-Prozess). Dadurch
    sagt das aktuelle Momentum die Folge-Rendite teilweise voraus – das Modell
    kann also ein echtes Signal lernen und seine Präzision steigern.
    """
    n = _period_to_days(period)
    rng = np.random.default_rng(_seed(ticker))
    base_vol = rng.uniform(0.012, 0.022)

    # Versteckter Trendzustand: AR(1)-Drift mit hoher Persistenz -> Regime
    drift = np.zeros(n)
    d = rng.normal(0, 0.0008)
    for i in range(n):
        d = 0.97 * d + rng.normal(0, 0.0006)
        drift[i] = d
    rets = drift + rng.normal(0, base_vol, n)
    # gelegentliche "News-Schocks" für Realismus
    shocks = rng.choice([0, 1], size=n, p=[0.98, 0.02]) * rng.normal(0, 0.05, n)
    rets = rets + shocks
    start = rng.uniform(40, 400)
    close = start * np.cumprod(1 + rets)

    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
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


def _recent_trend(ticker: str) -> float:
    """Vorzeichen/Stärke des jüngsten Trends – steuert das News-Sentiment."""
    df = demo_prices(ticker, period="3mo")
    if len(df) < 10:
        return 0.0
    return float(df["Close"].iloc[-1] / df["Close"].iloc[-10] - 1.0)


def demo_news(ticker: str, limit: int = 25) -> list[NewsItem]:
    """Erzeugt Schlagzeilen, deren Sentiment zum aktuellen Trend passt.

    So korreliert das News-Sentiment mit der Kursrichtung (wie in der Realität)
    und liefert dem Modell ein zusätzliches, lernbares Signal.
    """
    rng = np.random.default_rng(_seed(ticker) + 7)
    n = int(min(limit, rng.integers(4, 9)))
    trend = _recent_trend(ticker)
    # Wahrscheinlichkeiten je nach Trend gewichten (pos, neg, neutral)
    if trend > 0.01:
        probs = [0.6, 0.15, 0.25]
    elif trend < -0.01:
        probs = [0.15, 0.6, 0.25]
    else:
        probs = [0.34, 0.33, 0.33]
    pools = [_POS_TEMPLATES, _NEG_TEMPLATES, _NEUTRAL_TEMPLATES]

    items: list[NewsItem] = []
    for _ in range(n):
        kind = rng.choice([0, 1, 2], p=probs)
        templates = pools[kind]
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
