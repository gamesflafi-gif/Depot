"""Direkter Kursdaten-Download von Stooq (CSV, ohne API-Key).

Stooq stellt historische Tageskurse als einfache CSV-Datei bereit – das ist ein
*direkter* Download öffentlicher Daten, keine Anbieter-API/Bibliothek. Dient als
unabhängige Zweitquelle/Fallback zu yfinance, damit das Projekt nicht von einem
einzelnen Anbieter abhängt.

CSV-Format: Date,Open,High,Low,Close,Volume
"""
from __future__ import annotations

import csv
import io
import logging
import urllib.request

import pandas as pd

log = logging.getLogger(__name__)

_URL = "https://stooq.com/q/d/l/?s={symbol}&i=d"
_USER_AGENT = "Mozilla/5.0 (compatible; stockai/0.1)"

_PERIOD_DAYS = {
    "3mo": 63, "6mo": 126, "1y": 252, "2y": 504, "3y": 756,
    "5y": 1260, "10y": 2520, "max": 100_000,
}


def _to_symbol(ticker: str) -> str:
    """Bildet einen Ticker auf das Stooq-Symbol ab (z.B. AAPL -> aapl.us)."""
    t = ticker.strip().lower()
    if "." in t:          # bereits mit Börsensuffix, z.B. vwce.de
        return t
    return f"{t}.us"      # US-Werte brauchen das .us-Suffix


def parse_stooq_csv(raw: str) -> pd.DataFrame:
    """Parst eine Stooq-CSV in einen OHLCV-DataFrame (DatetimeIndex)."""
    rows = list(csv.DictReader(io.StringIO(raw)))
    if not rows or "Close" not in (rows[0].keys() if rows else {}):
        return pd.DataFrame()
    recs = []
    for r in rows:
        try:
            recs.append({
                "Date": pd.Timestamp(r["Date"]),
                "Open": float(r["Open"]), "High": float(r["High"]),
                "Low": float(r["Low"]), "Close": float(r["Close"]),
                "Volume": float(r.get("Volume") or 0.0),
            })
        except (ValueError, KeyError, TypeError):
            continue
    if not recs:
        return pd.DataFrame()
    df = pd.DataFrame(recs).set_index("Date").sort_index()
    df.index.name = "Date"
    return df


def fetch_prices_stooq(ticker: str, period: str = "2y", interval: str = "1d") -> pd.DataFrame:
    """Lädt Tageskurse direkt als CSV von Stooq (leerer DF bei Fehler)."""
    url = _URL.format(symbol=_to_symbol(ticker))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        log.warning("Stooq-Download für %s fehlgeschlagen: %s", ticker, exc)
        return pd.DataFrame()

    df = parse_stooq_csv(raw)
    if df.empty:
        return df
    n = _PERIOD_DAYS.get(period, 504)
    return df.iloc[-n:].copy()
