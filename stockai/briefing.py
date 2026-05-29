"""Tägliches Briefing mit „Moves"-Alerts.

Fasst die aktuelle Analyse kompakt zusammen (beste Chancen, Verkaufssignale,
Sparplan‑Kurzfassung) und erkennt **Veränderungen seit dem letzten Lauf**:

    * neue Kaufsignale (BOOM/KAUFEN)
    * neue Verkaufs-/Meiden-Signale
    * große Sprünge der Profit‑Wahrscheinlichkeit

So bekommst du nicht nur einen Status, sondern wirst gezielt über *Bewegungen*
informiert. Der Zustand wird zwischen den Läufen gespeichert.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from stockai.config import Config

_STATE_FILE = "last_briefing.json"
_BUY = {"BOOM", "KAUFEN"}
_SELL = {"VERKAUFEN", "MEIDEN"}
_PROB_JUMP = 0.10


@dataclass
class Briefing:
    timestamp: str
    top_buys: list = field(default_factory=list)      # TickerAnalysis
    top_sells: list = field(default_factory=list)
    new_buys: list = field(default_factory=list)      # (ticker, prob)
    new_sells: list = field(default_factory=list)
    prob_moves: list = field(default_factory=list)    # (ticker, old, new)
    has_changes: bool = False


def _state_path(cfg: Config) -> Path:
    return Path(cfg.store_dir) / _STATE_FILE


def _load_state(cfg: Config) -> dict:
    p = _state_path(cfg)
    if p.exists():
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_state(cfg: Config, analyses) -> None:
    state = {a.ticker: {"action": a.action, "prob": round(a.profit_probability, 4)}
             for a in analyses}
    json.dump(state, open(_state_path(cfg), "w", encoding="utf-8"), indent=2)


def build_briefing(cfg: Config, top_n: int = 5) -> Briefing:
    """Erzeugt das Briefing inkl. Moves gegenüber dem letzten Lauf."""
    from stockai import pipeline

    analyses = pipeline.analyze(cfg)
    prev = _load_state(cfg)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    br = Briefing(timestamp=ts)
    br.top_buys = [a for a in analyses if a.action in _BUY][:top_n]
    br.top_sells = [a for a in analyses if a.action in _SELL][:top_n]

    for a in analyses:
        old = prev.get(a.ticker)
        if not old:
            continue
        old_action, old_prob = old.get("action", "HALTEN"), old.get("prob", 0.5)
        if a.action in _BUY and old_action not in _BUY:
            br.new_buys.append((a.ticker, a.profit_probability))
        if a.action in _SELL and old_action not in _SELL:
            br.new_sells.append((a.ticker, a.profit_probability))
        if abs(a.profit_probability - old_prob) >= _PROB_JUMP:
            br.prob_moves.append((a.ticker, old_prob, a.profit_probability))

    br.has_changes = bool(br.new_buys or br.new_sells or br.prob_moves)
    _save_state(cfg, analyses)
    return br


def render_briefing(br: Briefing, cfg: Config | None = None) -> str:
    """Markdown-Report (Telegram-tauglich)."""
    lines = [f"# 📊 Aktien-KI Briefing ({br.timestamp})"]

    if br.has_changes:
        lines.append("\n## ⚡ Bewegungen seit dem letzten Lauf")
        for t, p in br.new_buys:
            lines.append(f"- 🟢 **NEU Kaufsignal:** {t} (P {p:.0%})")
        for t, p in br.new_sells:
            lines.append(f"- 🔴 **NEU Verkaufen/Meiden:** {t} (P {p:.0%})")
        for t, o, n in br.prob_moves:
            arrow = "↑" if n > o else "↓"
            lines.append(f"- {arrow} {t}: P {o:.0%} → {n:.0%}")
    else:
        lines.append("\n_Keine wesentlichen Veränderungen seit dem letzten Lauf._")

    lines.append("\n## 🚀 Beste Chancen")
    if br.top_buys:
        for a in br.top_buys:
            er = f", E[Rendite] {a.expected_return:+.1%}" if a.expected_return is not None else ""
            lines.append(f"- **{a.ticker}** [{a.asset_class}] {a.action} – "
                         f"P {a.profit_probability:.0%}{er}")
    else:
        lines.append("- (aktuell keine klaren Kaufsignale)")

    if br.top_sells:
        lines.append("\n## 💰 Verkaufen / Meiden")
        for a in br.top_sells:
            lines.append(f"- **{a.ticker}** [{a.asset_class}] – {a.timing}")

    lines.append("\n_Keine Anlageberatung._")
    return "\n".join(lines)
