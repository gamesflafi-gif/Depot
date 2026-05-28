"""Technische Indikatoren als Modell-Features.

Bewusst ohne Zusatz-Abhängigkeiten (TA-Lib o.ä.) – alles in pandas/numpy,
damit das Projekt überall ohne Kompilierung läuft.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Liste der erzeugten Feature-Spalten – wird auch vom Modell genutzt.
TECHNICAL_FEATURES: list[str] = [
    "ret_1d",
    "ret_5d",
    "ret_10d",
    "vol_10d",
    "vol_20d",
    "rsi_14",
    "macd",
    "macd_signal",
    "sma_ratio",
    "volume_change",
    "price_vs_high_20",
]


def _rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def add_technical_features(df: pd.DataFrame) -> pd.DataFrame:
    """Ergänzt einen OHLCV-DataFrame um technische Indikatoren.

    Erwartet Spalten: Open, High, Low, Close, Volume.
    """
    out = df.copy()
    close = out["Close"]

    # Renditen über verschiedene Zeiträume
    out["ret_1d"] = close.pct_change(1)
    out["ret_5d"] = close.pct_change(5)
    out["ret_10d"] = close.pct_change(10)

    # Volatilität (rollierende Std der Tagesrenditen)
    daily_ret = close.pct_change()
    out["vol_10d"] = daily_ret.rolling(10).std()
    out["vol_20d"] = daily_ret.rolling(20).std()

    # RSI
    out["rsi_14"] = _rsi(close, 14)

    # MACD (12/26) + Signallinie (9)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    out["macd"] = ema12 - ema26
    out["macd_signal"] = out["macd"].ewm(span=9, adjust=False).mean()

    # Verhältnis kurzer/langer gleitender Durchschnitt
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    out["sma_ratio"] = sma20 / sma50

    # Volumenveränderung
    out["volume_change"] = out["Volume"].pct_change(5)

    # Abstand zum 20-Tage-Hoch
    high20 = close.rolling(20).max()
    out["price_vs_high_20"] = close / high20

    return out
