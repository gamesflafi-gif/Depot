"""Kursdaten über yfinance (Yahoo Finance) – kostenlos und ohne API-Key."""
from __future__ import annotations

import logging

import pandas as pd
import yfinance as yf

log = logging.getLogger(__name__)


def fetch_prices(
    ticker: str,
    period: str = "2y",
    interval: str = "1d",
) -> pd.DataFrame:
    """Lädt OHLCV-Kursdaten für einen Ticker.

    Returns:
        DataFrame mit Spalten Open, High, Low, Close, Volume und
        DatetimeIndex. Leerer DataFrame, falls keine Daten verfügbar.
    """
    try:
        df = yf.download(
            ticker,
            period=period,
            interval=interval,
            auto_adjust=True,
            progress=False,
        )
    except Exception as exc:  # Netzwerk-/API-Fehler robust abfangen
        log.warning("Kursabruf für %s fehlgeschlagen: %s", ticker, exc)
        return pd.DataFrame()

    if df is None or df.empty:
        log.warning("Keine Kursdaten für %s erhalten.", ticker)
        return pd.DataFrame()

    # yfinance liefert bei Einzel-Ticker manchmal MultiIndex-Spalten -> glätten
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.rename(columns=str.title)
    keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    df = df[keep].copy()
    df.index = pd.to_datetime(df.index)
    df.index.name = "Date"
    return df


def fetch_latest_price(ticker: str) -> float | None:
    """Liefert den zuletzt verfügbaren Schlusskurs (oder None)."""
    df = fetch_prices(ticker, period="5d", interval="1d")
    if df.empty:
        return None
    return float(df["Close"].iloc[-1])
