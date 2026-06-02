"""Smarte bedingte Alerts: frei definierbare Trigger fürs Handy.

Du legst eigene Bedingungen fest – „melde dich, wenn BTC unter 50000 fällt",
„wenn NVDA-RSI unter 30 geht" oder „wenn das Volumen ungewöhnlich hoch ist".
Der Cron prüft sie regelmäßig und schickt nur dann eine Nachricht, wenn eine
Bedingung **frisch erreicht** wird (Crossing-Logik: erst wieder, wenn sie
zwischendurch nicht mehr erfüllt war – so gibt es keinen Dauer-Spam).

Bedingungen liegen lokal im Feature-Store (``watches.json``).
Keine Anlageberatung.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from stockai.config import Config

_FILE = "watches.json"
_METRICS = {"price", "rsi", "vol", "pct"}
_LABEL = {"price": "Kurs", "rsi": "RSI", "vol": "rel. Volumen", "pct": "Tagesänderung"}


@dataclass
class Watch:
    ticker: str
    metric: str          # price | rsi | vol | pct
    op: str              # "<" oder ">"
    value: float
    armed: bool = True   # bereit auszulösen (verhindert Dauer-Spam)


# --------------------------------------------------------------------------- #
def _path(cfg: Config) -> Path:
    return Path(cfg.store_dir) / _FILE


def load_watches(cfg: Config) -> list[Watch]:
    p = _path(cfg)
    if not p.exists():
        return []
    try:
        return [Watch(w["ticker"], w["metric"], w["op"], float(w["value"]),
                      bool(w.get("armed", True))) for w in json.load(open(p, encoding="utf-8"))]
    except Exception:
        return []


def save_watches(cfg: Config, watches: list[Watch]) -> None:
    p = _path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    json.dump([{"ticker": w.ticker, "metric": w.metric, "op": w.op,
                "value": w.value, "armed": w.armed} for w in watches],
              open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def parse_spec(parts: list[str]) -> Watch | None:
    """Liest eine Bedingung aus Befehlsteilen, z.B.:

        BTC-USD < 50000          (Kurs, Standard)
        NVDA rsi < 30            (RSI)
        BTC-USD vol > 2          (relatives Volumen)
        NVDA pct < -5            (Tagesänderung in %)
    """
    if len(parts) < 3:
        return None
    ticker = parts[0].upper()
    rest = parts[1:]
    metric = "price"
    if rest[0].lower() in _METRICS:
        metric = rest[0].lower()
        rest = rest[1:]
    if len(rest) < 2 or rest[0] not in ("<", ">"):
        return None
    try:
        value = float(rest[1].replace(",", "."))
    except ValueError:
        return None
    return Watch(ticker=ticker, metric=metric, op=rest[0], value=value)


def add_watch(cfg: Config, watch: Watch) -> list[Watch]:
    watches = load_watches(cfg)
    watches.append(watch)
    save_watches(cfg, watches)
    return watches


def remove_watch(cfg: Config, index: int) -> bool:
    watches = load_watches(cfg)
    if 0 <= index < len(watches):
        watches.pop(index)
        save_watches(cfg, watches)
        return True
    return False


# --------------------------------------------------------------------------- #
def _current_value(cfg: Config, ticker: str, metric: str) -> float | None:
    """Holt den aktuellen Wert der Kennzahl (Live, wo möglich)."""
    from stockai.data.live import get_quote
    if metric in ("price", "pct"):
        q = get_quote(ticker)
        if q:
            return q.price if metric == "price" else q.change_pct
        if metric == "pct":
            return None
    # rsi/vol – und Preis-Fallback – aus der Kurshistorie
    from stockai.data import provider
    from stockai.features.technical import add_technical_features
    try:
        prices = provider.get_prices(cfg, ticker)
        if prices.empty:
            return None
        feat = add_technical_features(prices)
        last = feat.iloc[-1]
    except Exception:
        return None
    if metric == "price":
        return float(prices["Close"].iloc[-1])
    if metric == "rsi":
        return float(last.get("rsi_14", float("nan")))
    if metric == "vol":
        return float(last.get("rel_volume", float("nan")))
    return None


def _holds(val: float, op: str, threshold: float) -> bool:
    return val < threshold if op == "<" else val > threshold


def check_watches(cfg: Config, fire: bool = True) -> list[str]:
    """Prüft alle Bedingungen; liefert Meldungen für frisch erreichte Trigger.

    Crossing-Logik: ein Trigger feuert nur, wenn er gerade *erstmals wieder*
    erfüllt ist; er wird erst dann erneut scharf, wenn die Bedingung zwischendurch
    nicht mehr galt. So kommt keine Nachricht im Minutentakt.
    """
    watches = load_watches(cfg)
    messages: list[str] = []
    changed = False
    for w in watches:
        val = _current_value(cfg, w.ticker, w.metric)
        if val is None or val != val:                 # None oder NaN
            continue
        cond = _holds(val, w.op, w.value)
        if cond and w.armed:
            messages.append(_trigger_text(w, val))
            w.armed = False
            changed = True
        elif not cond and not w.armed:
            w.armed = True                            # wieder scharf machen
            changed = True
    if changed and fire:
        save_watches(cfg, watches)
    return messages


def _fmt(metric: str, val: float) -> str:
    if metric == "rsi":
        return f"{val:.0f}"
    if metric == "vol":
        return f"{val:.1f}×"
    if metric == "pct":
        return f"{val:+.1f}%"
    return f"{val:,.2f}"


def _trigger_text(w: Watch, val: float) -> str:
    arrow = "📉" if w.op == "<" else "📈"
    return (f"{arrow} {w.ticker}: {_LABEL[w.metric]} {_fmt(w.metric, val)} "
            f"{w.op} {_fmt(w.metric, w.value)} erreicht")


def render_watches(cfg: Config) -> str:
    watches = load_watches(cfg)
    if not watches:
        return ("🔔 Keine Alerts gesetzt.\n"
                "Beispiele:\n"
                "  /watch add BTC-USD < 50000\n"
                "  /watch add NVDA rsi < 30\n"
                "  /watch add BTC-USD vol > 2\n"
                "  /watch add NVDA pct < -5")
    lines = ["🔔 Deine Alerts:"]
    for i, w in enumerate(watches):
        state = "scharf" if w.armed else "ausgelöst (wartet auf Reset)"
        lines.append(f"  [{i}] {w.ticker} {_LABEL[w.metric]} {w.op} "
                     f"{_fmt(w.metric, w.value)} · {state}")
    lines.append("\nEntfernen: /watch remove NUMMER · Alle löschen: /watch clear")
    return "\n".join(lines)
