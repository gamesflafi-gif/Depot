"""Intraday-/Live-Alerts: starke Kursbewegungen near-realtime erkennen.

Vergleicht die aktuellen Live-Kurse mit dem Stand des letzten Alert-Laufs und
meldet Werte, die sich seitdem stark bewegt haben (Schwelle in %), sowie große
Tagesbewegungen. Zustand wird zwischen den Läufen gespeichert.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from stockai.config import Config

_STATE_FILE = "last_alerts.json"


@dataclass
class AlertResult:
    timestamp: str
    moves: list = field(default_factory=list)   # (ticker, price, change_since_last, day_pct)
    has_alerts: bool = False


def _state_path(cfg: Config) -> Path:
    return Path(cfg.store_dir) / _STATE_FILE


def _load(cfg: Config) -> dict:
    p = _state_path(cfg)
    if p.exists():
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save(cfg: Config, prices: dict) -> None:
    json.dump(prices, open(_state_path(cfg), "w", encoding="utf-8"), indent=2)


def scan_moves(cfg: Config, save_state: bool = True):
    """Erfasst je Wert die Bewegung seit dem letzten Lauf (ohne Schwelle).

    Liefert ``(timestamp, moves)`` mit ``moves`` = Liste ``(ticker, price, since%,
    day%)``. Aktualisiert den gespeicherten Stand **einmal** (``save_state``),
    damit die Pro-Nutzer-Filterung danach denselben Datenstand nutzt.
    """
    from stockai.data.live import get_quote
    from stockai import pipeline
    from stockai.clock import now_de_str

    prev = _load(cfg)
    current: dict = {}
    moves: list = []
    for t in pipeline.universe(cfg):
        q = get_quote(t)
        if not q:
            continue
        current[t] = q.price
        old = prev.get(t)
        since = (q.price / old - 1.0) * 100 if old else 0.0
        moves.append((t, q.price, since, q.change_pct))
    if current and save_state:
        _save(cfg, current)
    return now_de_str(), moves


def filter_result(timestamp: str, moves: list, move_pct: float = 3.0) -> AlertResult:
    """Filtert die erfassten Bewegungen auf eine Schwelle (in %)."""
    res = AlertResult(timestamp=timestamp)
    for t, price, since, day in moves:
        if abs(since) >= move_pct or abs(day) >= move_pct * 1.5:
            res.moves.append((t, price, since, day))
    res.moves.sort(key=lambda m: abs(m[2]) + abs(m[3]), reverse=True)
    res.has_alerts = bool(res.moves)
    return res


def check_alerts(cfg: Config, move_pct: float = 3.0, save_state: bool = True) -> AlertResult:
    """Prüft Live-Kurse auf starke Bewegungen seit dem letzten Lauf."""
    ts, moves = scan_moves(cfg, save_state=save_state)
    return filter_result(ts, moves, move_pct)


def render_alerts(res: AlertResult) -> str:
    lines = [f"Live-Alerts ({res.timestamp})"]
    if not res.moves:
        return ""  # nichts zu melden
    for t, price, since, day in res.moves:
        arrow = "↑" if since >= 0 else "↓"
        lines.append(f"{arrow} {t}: {price:.2f}  ({since:+.1f}% seit letztem Check, "
                     f"{day:+.1f}% heute)")
    lines.append("\nKeine Anlageberatung.")
    return "\n".join(lines)
