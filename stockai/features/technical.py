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
    "ret_60d",
    "vol_10d",
    "vol_20d",
    "vol_ratio",
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_hist",
    "sma_ratio",
    "dist_sma50",
    "dist_sma200",
    "volume_change",
    "volume_z",
    "rel_volume",
    "obv_slope",
    "mfi_14",
    "ret_skew_20",
    "price_vs_high_20",
    "price_vs_high_252",
    "bb_pctb",
    "atr_pct",
    "stoch_k",
    "dow",
    "month",
    "hour",
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
    out["ret_60d"] = close.pct_change(60)        # 3-Monats-Momentum (Faktor)

    # Volatilität (rollierende Std der Tagesrenditen)
    daily_ret = close.pct_change()
    out["vol_10d"] = daily_ret.rolling(10).std()
    out["vol_20d"] = daily_ret.rolling(20).std()
    # Volatilitäts-Regime: kurzfristige vs. längerfristige Schwankung (>1 = steigend)
    vol_60d = daily_ret.rolling(60, min_periods=30).std()
    out["vol_ratio"] = out["vol_20d"] / vol_60d.replace(0, np.nan)

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
    # Langfrist-Trendfilter: Abstand zur 200-Tage-Linie (oberhalb = Aufwärtstrend)
    sma200 = close.rolling(200, min_periods=60).mean()
    out["dist_sma200"] = close / sma200 - 1.0

    # Volumen: Veränderung + z-Score
    out["volume_change"] = volume.pct_change(5)
    vol_mean = volume.rolling(20).mean()
    vol_std = volume.rolling(20).std()
    out["volume_z"] = (volume - vol_mean) / vol_std.replace(0, np.nan)

    # Relatives Volumen: aktuelles vs. 20-Tage-Schnitt (>1 = ungewöhnlich aktiv,
    # die „Whale"-/Smart-Money-Spur). Robuster fürs Schwellen-Setzen als der z-Score.
    out["rel_volume"] = volume / vol_mean.replace(0, np.nan)

    # On-Balance-Volume-Trend: fließt Volumen netto in Käufe (Akkumulation) oder
    # Verkäufe (Distribution)? Steigung über 10 Tage, skaliert aufs typische Volumen
    # → vergleichbar über Werte hinweg. Klassisches Frühsignal für „Smart Money".
    obv = (np.sign(close.diff()).fillna(0.0) * volume).cumsum()
    out["obv_slope"] = (obv - obv.shift(10)) / (vol_mean.replace(0, np.nan) * 10.0)

    # Money-Flow-Index (14): volumengewichtetes Momentum (wie RSI, aber mit
    # Geldfluss) – erkennt, ob Kauf-/Verkaufsdruck *mit* Volumen unterlegt ist.
    typical = (high + low + close) / 3.0
    raw_flow = typical * volume
    up = typical.diff() > 0
    pos_flow = raw_flow.where(up, 0.0).rolling(14).sum()
    neg_flow = raw_flow.where(~up, 0.0).rolling(14).sum()
    mfr = pos_flow / neg_flow.replace(0, np.nan)
    out["mfi_14"] = 100 - (100 / (1 + mfr))

    # Schiefe der Tagesrenditen (20T): asymmetrisches Risiko – stark negative
    # Schiefe warnt vor Abwärts-Ausreißern (Crash-Neigung), positive vor Sprüngen.
    out["ret_skew_20"] = daily_ret.rolling(20).skew()

    # Abstand zum 20-Tage-Hoch
    high20 = close.rolling(20).max()
    out["price_vs_high_20"] = close / high20
    # Nähe zum 52-Wochen-Hoch: starker Momentum-Faktor (1.0 = am Jahreshoch)
    high252 = close.rolling(252, min_periods=60).max()
    out["price_vs_high_252"] = close / high252

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
    out["hour"] = idx.hour.astype(float)          # Intraday: Tageszeit (0 bei Tagesdaten)

    # Unendlich-Werte neutralisieren (z.B. pct_change aus Volumen 0 -> inf), damit
    # sie als NaN behandelt und sauber rausgefiltert werden statt das Training zu
    # sprengen ("Input X contains infinity").
    out[TECHNICAL_FEATURES] = out[TECHNICAL_FEATURES].replace([np.inf, -np.inf], np.nan)
    return out
