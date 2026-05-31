"""Intraday-Kursdaten (Bars feiner als ein Tag).

    * Krypto: Binance Klines (kostenlos, ohne Key)
    * Aktien/ETFs: Twelve Data (kostenloser Key in STOCKAI_TWELVEDATA_KEY) –
      liefert Intraday-Kerzen im Free-Tier.

Hinweis: Intraday-Historie ist anbieterseitig begrenzt (einige Tage bis Wochen),
also stehen weniger Trainingsdaten zur Verfügung als bei Tagesdaten.
"""
from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request

import pandas as pd

log = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (compatible; stockai/0.1)"

# Unsere Config-Intervalle -> Anbieter-Intervalle
_BINANCE = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "60m": "1h",
            "1h": "1h", "4h": "4h", "1d": "1d"}
_TWELVE = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
           "60m": "1h", "1h": "1h", "4h": "4h", "1d": "1day"}


def is_intraday(interval: str) -> bool:
    return interval.strip().lower() not in ("1d", "1day", "1w", "1mo")


def _http(url: str, timeout: int = 12):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# --------------------------------------------------------------------------- #
def parse_binance_klines(data: list) -> pd.DataFrame:
    """Binance-Klines (Liste von Arrays) -> OHLCV-DataFrame."""
    rows = []
    for k in data:
        try:
            rows.append({
                "Date": pd.to_datetime(int(k[0]), unit="ms"),
                "Open": float(k[1]), "High": float(k[2]), "Low": float(k[3]),
                "Close": float(k[4]), "Volume": float(k[5]),
            })
        except (ValueError, IndexError, TypeError):
            continue
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).set_index("Date").sort_index()


def fetch_binance_klines(symbol: str, interval: str, limit: int = 1000) -> pd.DataFrame:
    iv = _BINANCE.get(interval, "15m")
    url = (f"https://api.binance.com/api/v3/klines?symbol={symbol}"
           f"&interval={iv}&limit={min(limit, 1000)}")
    try:
        return parse_binance_klines(_http(url))
    except Exception as exc:
        log.warning("Binance-Klines für %s fehlgeschlagen: %s", symbol, exc)
        return pd.DataFrame()


# --------------------------------------------------------------------------- #
def parse_twelvedata(data: dict) -> pd.DataFrame:
    """Twelve-Data time_series -> OHLCV-DataFrame (älteste zuerst)."""
    if not isinstance(data, dict) or data.get("status") == "error":
        return pd.DataFrame()
    values = data.get("values")
    if not values:
        return pd.DataFrame()
    rows = []
    for v in values:
        try:
            rows.append({
                "Date": pd.to_datetime(v["datetime"]),
                "Open": float(v["open"]), "High": float(v["high"]),
                "Low": float(v["low"]), "Close": float(v["close"]),
                "Volume": float(v.get("volume") or 0.0),
            })
        except (KeyError, ValueError, TypeError):
            continue
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).set_index("Date").sort_index()


def fetch_twelvedata(symbol: str, interval: str, outputsize: int, key: str) -> pd.DataFrame:
    iv = _TWELVE.get(interval, "15min")
    params = urllib.parse.urlencode({
        "symbol": symbol, "interval": iv,
        "outputsize": min(outputsize, 5000), "apikey": key,
    })
    try:
        return parse_twelvedata(_http(f"https://api.twelvedata.com/time_series?{params}"))
    except Exception as exc:
        log.warning("Twelve-Data für %s fehlgeschlagen: %s", symbol, exc)
        return pd.DataFrame()
