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
    "ret_20d",
    "vol_10d",
    "vol_20d",
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_hist",
    "sma_ratio",
    "dist_sma50",
    "volume_change",
    "volume_z",
    "price_vs_high_20",
    "bb_pctb",
    "atr_pct",
    "stoch_k",
    "dow",
    "month",
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
    high = out.get("High", close)
    low = out.get("Low", close)
    volume = out["Volume"]

    # Renditen über verschiedene Zeiträume
    out["ret_1d"] = close.pct_change(1)
    out["ret_5d"] = close.pct_change(5)
    out["ret_10d"] = close.pct_change(10)
    out["ret_20d"] = close.pct_change(20)

    # Volatilität (rollierende Std der Tagesrenditen)
    daily_ret = close.pct_change()
    out["vol_10d"] = daily_ret.rolling(10).std()
    out["vol_20d"] = daily_ret.rolling(20).std()

    # RSI
    out["rsi_14"] = _rsi(close, 14)

    # MACD (12/26) + Signallinie (9) + Histogramm
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    out["macd"] = ema12 - ema26
    out["macd_signal"] = out["macd"].ewm(span=9, adjust=False).mean()
    out["macd_hist"] = out["macd"] - out["macd_signal"]

    # Gleitende Durchschnitte
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    out["sma_ratio"] = sma20 / sma50
    out["dist_sma50"] = close / sma50 - 1.0

    # Volumen: Veränderung + z-Score
    out["volume_change"] = volume.pct_change(5)
    vol_mean = volume.rolling(20).mean()
    vol_std = volume.rolling(20).std()
    out["volume_z"] = (volume - vol_mean) / vol_std.replace(0, np.nan)

    # Abstand zum 20-Tage-Hoch
    high20 = close.rolling(20).max()
    out["price_vs_high_20"] = close / high20

    # Bollinger %B (20, 2σ): Position im Band, 0 = unteres, 1 = oberes Band
    std20 = close.rolling(20).std()
    upper = sma20 + 2 * std20
    lower = sma20 - 2 * std20
    out["bb_pctb"] = (close - lower) / (upper - lower).replace(0, np.nan)

    # ATR (14) als Anteil des Kurses (normierte Volatilität)
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    out["atr_pct"] = tr.rolling(14).mean() / close

    # Stochastik %K (14)
    low14 = low.rolling(14).min()
    high14 = high.rolling(14).max()
    out["stoch_k"] = (close - low14) / (high14 - low14).replace(0, np.nan) * 100

    # Saisonalität: wiederkehrende Kalendereffekte (Wochentag, Monat)
    idx = pd.DatetimeIndex(out.index)
    out["dow"] = idx.dayofweek.astype(float)      # 0=Mo … 4=Fr
    out["month"] = idx.month.astype(float)        # 1..12

    return out
