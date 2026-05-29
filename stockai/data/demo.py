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


# Bekannte Krypto-Kürzel (für höhere Demo-Volatilität, deterministisch am Ticker).
_CRYPTO_HINTS = {"BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "BNB", "DOT", "LTC", "AVAX"}


def _is_crypto(ticker: str) -> bool:
    t = ticker.strip().upper()
    return t.endswith("-USD") or t.split("-")[0] in _CRYPTO_HINTS


# Länge der kanonischen Vollreihe (Business-Tage); alle Zeiträume werden als
# Ausschnitt hieraus gebildet, damit sie konsistent zueinander sind.
_CANONICAL_DAYS = 2520  # ~10 Jahre


def _period_to_days(period: str) -> int:
    period = period.strip().lower()
    mapping = {
        "3mo": 63, "6mo": 126, "1y": 252, "2y": 504, "3y": 756,
        "5y": 1260, "10y": 2520, "max": _CANONICAL_DAYS,
    }
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
    # Krypto: deutlich höhere Volatilität und stärkere Trend-Regime.
    crypto = _is_crypto(ticker)
    base_vol = rng.uniform(0.03, 0.05) if crypto else rng.uniform(0.012, 0.018)
    dsig = 0.0018 if crypto else 0.0009
    clip = 0.009 if crypto else 0.0045
    shock_p = 0.03 if crypto else 0.015

    # Moderate, realistisch verrauschte Trend-Regime (kleiner Edge, kein
    # „sauberes" Signal). Die Drift ist begrenzt -> realistische Kurse.
    drift = np.zeros(n)
    d = rng.normal(0, dsig)
    for i in range(n):
        d = 0.975 * d + rng.normal(0, dsig)
        d = float(np.clip(d, -clip, clip))
        drift[i] = d
    rets = drift + rng.normal(0, base_vol, n)
    shocks = rng.choice([0, 1], size=n, p=[1 - shock_p, shock_p]) * rng.normal(0, 0.08 if crypto else 0.05, n)
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
    sent = np.tanh(drift * 35.0) + rng.normal(0, 0.30, len(drift))
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
    """Historische, tagesgenaue Sentiment-Features (für das Modell-Training).

    Enthält auch die erweiterten News-Features: Sentiment-Trend (Veränderung),
    News-Mengen-Spike (z-Score) und Schlagwort-Signal.
    """
    idx, sent = _sentiment_mean_series(ticker)
    rng = np.random.default_rng(_seed(ticker) + 17)
    rows = [_sentiment_features_from_mean(float(s), rng) for s in sent]
    df = pd.DataFrame(rows, index=idx)
    s = df["sent_mean"]
    # Sentiment-Trend: Abweichung vom 5-Tage-Mittel
    df["sent_trend"] = (s - s.rolling(5).mean()).fillna(0.0)
    # News-Mengen-Spike: z-Score der News-Anzahl über 20 Tage
    c = df["news_count"]
    df["news_vol_z"] = ((c - c.rolling(20).mean()) / c.rolling(20).std()).fillna(0.0)
    # Schlagwort-Signal: in der Demo folgt die Polarität dem Sentiment
    df["kw_signal"] = s.clip(-1.0, 1.0)
    df.index.name = "Date"
    return df


def demo_sentiment_today(ticker: str) -> dict:
    """Aktuelle Sentiment-Features (konsistent zur Historie)."""
    return demo_sentiment_history(ticker).iloc[-1].to_dict()


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
