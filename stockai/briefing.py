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


def _now_de() -> datetime:
    """Aktuelle Zeit in deutscher Lokalzeit (Fallback: UTC)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Berlin"))
    except Exception:
        return datetime.now(timezone.utc)


def _klass(asset_class: str) -> str:
    """Kurzlabel der Anlageklasse ohne eckige Klammern."""
    return {"ETF": "ETF", "Krypto": "Krypto", "Aktie": "Aktie"}.get(
        asset_class, asset_class or "Wert")


@dataclass
class Briefing:
    timestamp: str
    top_buys: list = field(default_factory=list)      # TickerAnalysis
    top_sells: list = field(default_factory=list)
    new_buys: list = field(default_factory=list)      # (ticker, prob)
    new_sells: list = field(default_factory=list)
    prob_moves: list = field(default_factory=list)    # (ticker, old, new)
    has_changes: bool = False
    regime: str = ""


def market_regime(analyses) -> str:
    """Grobe Marktlage aus den Analysen: bullisch / neutral / bärisch."""
    if not analyses:
        return "unbekannt"
    import statistics
    mom = statistics.mean(a.momentum_5d for a in analyses)
    rsi = statistics.mean(a.rsi_14 for a in analyses)
    up = sum(1 for a in analyses if a.profit_probability >= 0.5) / len(analyses)
    if mom > 0.01 and rsi >= 52 and up >= 0.55:
        return f"📈 bullisch (Ø Momentum {mom:+.1%}, RSI {rsi:.0f})"
    if mom < -0.01 and rsi <= 48 and up <= 0.45:
        return f"📉 bärisch (Ø Momentum {mom:+.1%}, RSI {rsi:.0f})"
    return f"➖ neutral (Ø Momentum {mom:+.1%}, RSI {rsi:.0f})"


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

    ts = _now_de().strftime("%d.%m.%Y, %H:%M Uhr")
    br = Briefing(timestamp=ts)
    br.regime = market_regime(analyses)
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
    """Sauberer Telegram-Report – reiner Text, gut lesbar (kein Markdown-Wirrwarr)."""
    lines = [f"📊 Aktien-KI Briefing · {br.timestamp}"]
    if br.regime:
        lines.append(f"Marktlage: {br.regime}")

    # --- Was hat sich bewegt? ---------------------------------------------
    if br.has_changes:
        lines.append("")
        lines.append("⚡ NEU SEIT DEM LETZTEN LAUF")
        for t, p in br.new_buys:
            lines.append(f"  🟢 Kaufsignal: {t}  ({p:.0%} Chance)")
        for t, p in br.new_sells:
            lines.append(f"  🔴 Verkaufen/Meiden: {t}  ({p:.0%})")
        for t, o, n in br.prob_moves:
            arrow = "↗︎" if n > o else "↘︎"
            lines.append(f"  {arrow} {t}: {o:.0%} → {n:.0%}")
    else:
        lines.append("")
        lines.append("➖ Keine neuen Signale seit dem letzten Lauf.")

    # --- Beste Chancen -----------------------------------------------------
    lines.append("")
    lines.append("🚀 BESTE CHANCEN HEUTE")
    if br.top_buys:
        for a in br.top_buys:
            er = (f"  ·  erwartet {a.expected_return:+.1%}"
                  if a.expected_return is not None else "")
            lines.append(f"  🟢 {a.ticker} ({_klass(a.asset_class)})  ·  "
                         f"Chance {a.profit_probability:.0%}{er}")
    else:
        lines.append("  – aktuell keine klaren Kaufsignale")

    # --- Verkaufen / Meiden ------------------------------------------------
    if br.top_sells:
        lines.append("")
        lines.append("🔴 LIEBER MEIDEN")
        for a in br.top_sells:
            lines.append(f"  {a.ticker} ({_klass(a.asset_class)})  ·  {a.timing}")

    lines.append("")
    lines.append("💬 Befehle: /analyse NVDA · /top · /sparplan · /weakspots · /help")
    lines.append("ℹ️ Keine Anlageberatung.")
    return "\n".join(lines)


def build_top(cfg: Config, n: int = 5):
    """Liefert (top_n, bottom_n) Werte nach Profit-Wahrscheinlichkeit."""
    from stockai import pipeline

    analyses = pipeline.analyze(cfg)
    ranked = sorted(analyses, key=lambda a: a.profit_probability, reverse=True)
    top = ranked[:n]
    bottom = list(reversed(ranked[-n:])) if len(ranked) >= n else list(reversed(ranked))
    return top, bottom


def render_top(top: list, bottom: list, n: int = 5) -> str:
    """Wöchentlicher Überblick: Top-N Chancen und Top-N Risiken (sauberer Text)."""
    ts = _now_de().strftime("%d.%m.%Y")
    lines = [f"📅 Wochen-Überblick · {ts}", "",
             f"🚀 TOP {n} CHANCEN (höchste Gewinn-Chance)"]
    for a in top:
        er = (f"  ·  erwartet {a.expected_return:+.1%}"
              if a.expected_return is not None else "")
        lines.append(f"  🟢 {a.ticker} ({_klass(a.asset_class)})  ·  "
                     f"Chance {a.profit_probability:.0%}{er}")

    lines.append("")
    lines.append(f"🔻 TOP {n} RISIKEN (schwächste Werte)")
    for a in bottom:
        lines.append(f"  🔴 {a.ticker} ({_klass(a.asset_class)})  ·  "
                     f"Chance {a.profit_probability:.0%}")

    lines.append("")
    lines.append("💬 Mehr: /analyse SYM · /briefing · /help")
    lines.append("ℹ️ Keine Anlageberatung.")
    return "\n".join(lines)
