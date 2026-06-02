"""Eigenes Depot: persönliche Positionen verfolgen und von der KI bewerten lassen.

Du trägst deine echten Positionen ein (Ticker, Stückzahl, Kaufkurs); die KI
zeigt dir dann für *deine* Werte den aktuellen Gewinn/Verlust **und** ihre
Einschätzung (Halten/Verkaufen) – inklusive gezielter Warnung, wenn sie zu einer
Position nicht mehr bullisch ist. So wird die Analyse persönlich relevant statt
nur allgemein.

Die Daten liegen lokal im Feature-Store (``holdings.json``) – nichts verlässt
deinen Server. Keine Anlageberatung.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from stockai.config import Config

_FILE = "holdings.json"
_SELL = {"VERKAUFEN", "MEIDEN"}


@dataclass
class Holding:
    ticker: str
    qty: float
    buy_price: float


@dataclass
class Position:
    ticker: str
    qty: float
    buy_price: float
    price: float                 # aktueller Kurs
    asset_class: str = "Aktie"
    action: str = "HALTEN"
    probability: float = float("nan")
    expected_return: float | None = None
    timing: str = ""
    source: str = ""

    @property
    def value(self) -> float:
        return self.qty * self.price

    @property
    def cost(self) -> float:
        return self.qty * self.buy_price

    @property
    def pnl(self) -> float:
        return self.value - self.cost

    @property
    def pnl_pct(self) -> float:
        return (self.price / self.buy_price - 1.0) if self.buy_price else float("nan")

    @property
    def sell_warning(self) -> bool:
        return self.action in _SELL


@dataclass
class DepotReport:
    positions: list = field(default_factory=list)
    total_value: float = 0.0
    total_cost: float = 0.0

    @property
    def total_pnl(self) -> float:
        return self.total_value - self.total_cost

    @property
    def total_pnl_pct(self) -> float:
        return (self.total_value / self.total_cost - 1.0) if self.total_cost else float("nan")


# --------------------------------------------------------------------------- #
def _path(cfg: Config, user: str | None) -> Path:
    from stockai.users import user_path
    return user_path(cfg, user, _FILE)


def load_holdings(cfg: Config, user: str | None = None) -> list[Holding]:
    p = _path(cfg, user)
    if not p.exists():
        return []
    try:
        raw = json.load(open(p, encoding="utf-8"))
        return [Holding(h["ticker"], float(h["qty"]), float(h["buy_price"])) for h in raw]
    except Exception:
        return []


def save_holdings(cfg: Config, holdings: list[Holding], user: str | None = None) -> None:
    p = _path(cfg, user)
    p.parent.mkdir(parents=True, exist_ok=True)
    json.dump([{"ticker": h.ticker, "qty": h.qty, "buy_price": h.buy_price} for h in holdings],
              open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def add_holding(cfg: Config, ticker: str, qty: float, buy_price: float,
                user: str | None = None) -> list[Holding]:
    """Fügt eine Position hinzu oder mischt sie ein (gewichteter Ø-Kaufkurs)."""
    ticker = ticker.strip().upper()
    holdings = load_holdings(cfg, user)
    for h in holdings:
        if h.ticker == ticker:                       # nachkaufen -> Ø-Einstand
            total_qty = h.qty + qty
            if total_qty != 0:
                h.buy_price = (h.qty * h.buy_price + qty * buy_price) / total_qty
            h.qty = total_qty
            break
    else:
        holdings.append(Holding(ticker, qty, buy_price))
    save_holdings(cfg, holdings, user)
    return holdings


def remove_holding(cfg: Config, ticker: str, user: str | None = None) -> bool:
    ticker = ticker.strip().upper()
    holdings = load_holdings(cfg, user)
    kept = [h for h in holdings if h.ticker != ticker]
    save_holdings(cfg, kept, user)
    return len(kept) != len(holdings)


def build_depot_report(cfg: Config, user: str | None = None) -> DepotReport:
    """Bewertet alle Depot-Positionen: Live-Kurs, G/V und KI-Einschätzung."""
    from stockai import pipeline
    from stockai.data.live import get_quote

    holdings = load_holdings(cfg, user)
    rep = DepotReport()
    if not holdings:
        return rep

    tickers = [h.ticker for h in holdings]
    analyses = {a.ticker: a for a in pipeline.analyze(cfg, universe_override=tickers)}

    for h in holdings:
        a = analyses.get(h.ticker)
        q = get_quote(h.ticker)
        price = q.price if q else (a.last_price if a else 0.0)
        pos = Position(
            ticker=h.ticker, qty=h.qty, buy_price=h.buy_price, price=price,
            asset_class=(a.asset_class if a else "Aktie"),
            action=(a.action if a else "HALTEN"),
            probability=(a.profit_probability if a else float("nan")),
            expected_return=(a.expected_return if a else None),
            timing=(a.timing if a else ""),
            source=(q.source if q else "Tageskurs"),
        )
        rep.positions.append(pos)
        rep.total_value += pos.value
        rep.total_cost += pos.cost

    # größte Risiken zuerst (Verkaufswarnungen, dann schwächste Wahrscheinlichkeit)
    rep.positions.sort(key=lambda p: (not p.sell_warning, p.probability))
    return rep


def depot_alert_text(cfg: Config, user: str | None = None) -> str | None:
    """Nur dann Text, wenn es etwas Handlungsrelevantes gibt (für Push-Alerts)."""
    rep = build_depot_report(cfg, user)
    flagged = [p for p in rep.positions if p.sell_warning]
    if not flagged:
        return None
    lines = ["🔔 Depot-Warnung: Die KI sieht Positionen kritisch"]
    for p in flagged:
        lines.append(f"  ⚠️ {p.ticker}: {p.action} – G/V {p.pnl_pct:+.1%}  "
                     f"(Chance {p.probability:.0%})")
    lines.append("\nℹ️ Keine Anlageberatung.")
    return "\n".join(lines)


def render_depot(rep: DepotReport) -> str:
    if not rep.positions:
        return ("💼 Dein Depot ist leer.\n"
                "Positionen hinzufügen: /depot add TICKER STÜCK KAUFKURS\n"
                "z.B.  /depot add NVDA 10 850")

    lines = ["💼 Dein Depot – KI-Bewertung & Gewinn/Verlust", ""]
    for p in rep.positions:
        gv = "🟢" if p.pnl >= 0 else "🔴"
        flag = "  ⚠️ KI: verkaufen/meiden" if p.sell_warning else ""
        er = (f" · erwartet {p.expected_return:+.1%}"
              if p.expected_return is not None else "")
        chance = f"{p.probability:.0%}" if p.probability == p.probability else "–"
        lines.append(
            f"{gv} {p.ticker} ({p.asset_class}) · {p.qty:g} Stk\n"
            f"   Kurs {p.price:.2f} (Einstand {p.buy_price:.2f}) · "
            f"G/V {p.pnl:+.2f} ({p.pnl_pct:+.1%})\n"
            f"   KI: {p.action} · Chance {chance}{er}{flag}"
        )
    lines.append("")
    sign = "🟢" if rep.total_pnl >= 0 else "🔴"
    lines.append(f"{sign} Gesamt: Wert {rep.total_value:.2f} · "
                 f"G/V {rep.total_pnl:+.2f} ({rep.total_pnl_pct:+.1%})")
    if any(p.sell_warning for p in rep.positions):
        lines.append("\n⚠️ Bei markierten Positionen ist die KI nicht mehr bullisch.")
    lines.append("\nℹ️ Keine Anlageberatung.")
    return "\n".join(lines)
