"""Alpaca Market Data (IEX) – kostenlose Intraday-Bars & Live-Quotes für Aktien.

Großzügiges Gratis-Limit (~200 Anfragen/Min) – die beste freie Quelle für
Intraday-US-Aktien. Keys als Umgebungsvariablen:
    STOCKAI_ALPACA_KEY, STOCKAI_ALPACA_SECRET

Nutzt den IEX-Feed (im Free-Tier). Für Bars und Snapshot-Quotes.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request

import pandas as pd

from stockai.data.live import Quote

log = logging.getLogger(__name__)

_KEY_ENV = "STOCKAI_ALPACA_KEY"
_SECRET_ENV = "STOCKAI_ALPACA_SECRET"
_BASE = "https://data.alpaca.markets/v2/stocks"

_TIMEFRAME = {"1m": "1Min", "5m": "5Min", "15m": "15Min", "30m": "30Min",
              "60m": "1Hour", "1h": "1Hour", "4h": "4Hour", "1d": "1Day"}


def configured() -> bool:
    return bool(os.environ.get(_KEY_ENV) and os.environ.get(_SECRET_ENV))


def _headers() -> dict:
    return {"APCA-API-KEY-ID": os.environ.get(_KEY_ENV, ""),
            "APCA-API-SECRET-KEY": os.environ.get(_SECRET_ENV, "")}


def _http(url: str, timeout: int = 12):
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_bars(data: dict) -> pd.DataFrame:
    """Alpaca-Bars -> OHLCV-DataFrame."""
    bars = (data or {}).get("bars") or []
    rows = []
    for b in bars:
        try:
            rows.append({
                "Date": pd.to_datetime(b["t"]).tz_localize(None),
                "Open": float(b["o"]), "High": float(b["h"]), "Low": float(b["l"]),
                "Close": float(b["c"]), "Volume": float(b.get("v") or 0.0),
            })
        except (KeyError, ValueError, TypeError):
            continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).set_index("Date").sort_index()
    df.index.name = "Date"
    return df


def fetch_bars(symbol: str, interval: str, limit: int = 5000) -> pd.DataFrame:
    if not configured():
        return pd.DataFrame()
    tf = _TIMEFRAME.get(interval, "15Min")
    params = urllib.parse.urlencode({"timeframe": tf, "limit": min(limit, 10000),
                                     "feed": "iex", "adjustment": "raw"})
    try:
        return parse_bars(_http(f"{_BASE}/{symbol.upper()}/bars?{params}"))
    except Exception as exc:
        log.warning("Alpaca-Bars für %s fehlgeschlagen: %s", symbol, exc)
        return pd.DataFrame()


def parse_snapshot(data: dict, ticker: str) -> Quote | None:
    """Alpaca-Snapshot -> Quote (latestTrade vs vorheriger Tagesschluss)."""
    try:
        price = float(data["latestTrade"]["p"])
        prev = data.get("prevDailyBar") or data.get("dailyBar") or {}
        prev_c = float(prev.get("c") or price)
        pct = (price / prev_c - 1.0) * 100 if prev_c else 0.0
        return Quote(ticker=ticker, price=price, change_pct=pct, source="alpaca")
    except (KeyError, ValueError, TypeError):
        return None


def get_quote(ticker: str) -> Quote | None:
    if not configured():
        return None
    try:
        data = _http(f"{_BASE}/{ticker.upper()}/snapshot?feed=iex")
        return parse_snapshot(data, ticker)
    except Exception as exc:
        log.warning("Alpaca-Quote für %s fehlgeschlagen: %s", ticker, exc)
        return None
