"""Live-Kurse (Echtzeit, soweit kostenlos verfügbar).

    * Krypto: Binance Public-API (ohne API-Key, echte Live-Kurse)
    * Aktien/ETFs: Finnhub (kostenloser Key in STOCKAI_FINNHUB_KEY) – US-Quotes
      nahe Echtzeit. Ohne Key kein Aktien-Live-Kurs (Tagesdaten reichen dafür
      nicht).

Liefert den aktuellen Preis und die Tagesveränderung. Bei Fehlern/ohne Quelle
wird None zurückgegeben (der Aufrufer fällt dann auf den letzten Schlusskurs
zurück).
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from dataclasses import dataclass

log = logging.getLogger(__name__)

_FINNHUB_KEY_ENV = "STOCKAI_FINNHUB_KEY"
_TWELVEDATA_KEY_ENV = "STOCKAI_TWELVEDATA_KEY"
_UA = "Mozilla/5.0 (compatible; stockai/0.1)"
_CRYPTO_HINTS = {"BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "BNB", "DOT", "LTC", "AVAX"}


@dataclass
class Quote:
    ticker: str
    price: float
    change_pct: float          # Tagesveränderung in %
    source: str


def is_crypto(ticker: str) -> bool:
    t = ticker.strip().upper()
    return t.endswith("-USD") or t.split("-")[0] in _CRYPTO_HINTS


def to_binance_symbol(ticker: str) -> str:
    """BTC-USD/BTC -> BTCUSDT."""
    base = ticker.strip().upper().replace("-USD", "").split("-")[0]
    return f"{base}USDT"


def _http_json(url: str, timeout: int = 8):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_binance(data: dict, ticker: str) -> Quote | None:
    """Wertet die Binance /ticker/24hr-Antwort aus."""
    try:
        return Quote(ticker=ticker, price=float(data["lastPrice"]),
                     change_pct=float(data["priceChangePercent"]), source="binance")
    except (KeyError, ValueError, TypeError):
        return None


def parse_finnhub(data: dict, ticker: str) -> Quote | None:
    """Wertet die Finnhub /quote-Antwort aus (c=Kurs, dp=Tages-%)."""
    try:
        price = float(data["c"])
        if price <= 0:
            return None
        return Quote(ticker=ticker, price=price,
                     change_pct=float(data.get("dp") or 0.0), source="finnhub")
    except (KeyError, ValueError, TypeError):
        return None


def parse_twelvedata_quote(data: dict, ticker: str) -> Quote | None:
    """Wertet die Twelve-Data /quote-Antwort aus (close, percent_change)."""
    try:
        if data.get("status") == "error":
            return None
        price = float(data["close"])
        return Quote(ticker=ticker, price=price,
                     change_pct=float(data.get("percent_change") or 0.0),
                     source="twelvedata")
    except (KeyError, ValueError, TypeError):
        return None


def get_quote(ticker: str) -> Quote | None:
    """Aktueller Live-Kurs (oder None, falls keine Quelle verfügbar)."""
    try:
        if is_crypto(ticker):
            sym = to_binance_symbol(ticker)
            data = _http_json(f"https://api.binance.com/api/v3/ticker/24hr?symbol={sym}")
            return parse_binance(data, ticker)
        # Aktien/ETFs: Twelve Data (ein Key für Quote + Intraday) bevorzugt,
        # sonst Finnhub.
        td = os.environ.get(_TWELVEDATA_KEY_ENV)
        if td:
            data = _http_json(
                f"https://api.twelvedata.com/quote?symbol={ticker.upper()}&apikey={td}")
            return parse_twelvedata_quote(data, ticker)
        fh = os.environ.get(_FINNHUB_KEY_ENV)
        if fh:
            data = _http_json(
                f"https://finnhub.io/api/v1/quote?symbol={ticker.upper()}&token={fh}")
            return parse_finnhub(data, ticker)
        return None
    except Exception as exc:
        log.warning("Live-Kurs für %s fehlgeschlagen: %s", ticker, exc)
        return None


def finnhub_configured() -> bool:
    return bool(os.environ.get(_FINNHUB_KEY_ENV))
