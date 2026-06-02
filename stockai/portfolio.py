"""Portfolio-/Allokations-Engine.

Übersetzt das Analyse-Ranking in konkrete Positionsgrößen: *wohin* fließt
*wie viel* Kapital? Berücksichtigt werden die gelernte Profit-Wahrscheinlichkeit
und die Konfidenz der Empfehlung, begrenzt durch Risiko-Obergrenzen
(maximaler Anteil pro Position) zur Diversifikation.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Allocation:
    ticker: str
    action: str
    weight: float          # Kapitalanteil 0..1
    amount: float          # investierter Betrag in Kontowährung
    shares: float          # gerundete Stückzahl
    last_price: float
    reason: str


@dataclass
class Portfolio:
    capital: float
    allocations: list[Allocation]
    invested: float
    cash: float
    sells: list[str]       # Ticker mit Verkaufs-/Meiden-Signal


def _regime_exposure(analyses) -> float:
    """Investitionsgrad je Marktlage: 1.0 (bullisch) … 0.4 (tiefer Abschwung)."""
    if not analyses:
        return 1.0
    import statistics
    mom = statistics.mean(getattr(a, "momentum_5d", 0.0) for a in analyses)
    return min(1.0, max(0.4, 1.0 + 20.0 * mom))


def build_portfolio(
    analyses,
    capital: float = 10_000.0,
    max_position_pct: float = 0.25,
    buy_actions=("BOOM", "KAUFEN"),
    sectors: dict[str, str] | None = None,
    max_sector_pct: float = 0.40,
    risk_aware: bool = True,
) -> Portfolio:
    """Erzeugt einen Allokationsvorschlag aus Analyse-Ergebnissen.

    Args:
        analyses: Liste von ``TickerAnalysis`` (aus pipeline.analyze).
        capital: verfügbares Gesamtkapital.
        max_position_pct: maximaler Kapitalanteil je Einzelposition.
        buy_actions: welche Empfehlungen als Kaufkandidaten gelten.
        sectors: optionale Ticker->Branche-Zuordnung für die Sektor-Obergrenze.
        max_sector_pct: maximaler Kapitalanteil je Branche (Diversifikation).
        risk_aware: wenn True, werden Positionen invers zur Volatilität gewichtet
            (schwankungsärmere Werte bekommen mehr) und zusätzlich nach
            erwarteter Rendite getiltet.
    """
    sectors = sectors or {}
    candidates = [a for a in analyses if a.action in buy_actions]
    sells = [a.ticker for a in analyses if a.action in ("VERKAUFEN", "MEIDEN")]

    if not candidates:
        return Portfolio(capital=capital, allocations=[], invested=0.0,
                         cash=capital, sells=sells)

    # Rohgewichte: Wahrscheinlichkeits-Edge × Konfidenz …
    def _score(a) -> float:
        s = max(0.0, (a.profit_probability - 0.5)) * max(0.1, a.confidence)
        if risk_aware:
            # … invers zur Volatilität (Risikoparität-Tilt) …
            s /= max(getattr(a, "volatility", 0.02) or 0.02, 0.005)
            # … und verstärkt durch positive erwartete Rendite
            er = getattr(a, "expected_return", None)
            if er is not None and er > 0:
                s *= (1.0 + 8.0 * er)
        return s

    raw = {a.ticker: _score(a) for a in candidates}
    total = sum(raw.values())
    if total <= 0:
        weights = {t: 1.0 / len(candidates) for t in raw}
    else:
        weights = {t: w / total for t, w in raw.items()}

    # Obergrenze je Position, dann je Branche (Diversifikation)
    weights = _apply_cap(weights, max_position_pct)
    if sectors:
        weights = _apply_sector_cap(weights, sectors, max_sector_pct, max_position_pct)

    # Regime-Bremse: in Abschwungphasen weniger investieren (Rest = Cash)
    exposure = _regime_exposure(analyses)
    if exposure < 0.999:
        weights = {t: w * exposure for t, w in weights.items()}

    allocations: list[Allocation] = []
    invested = 0.0
    by_ticker = {a.ticker: a for a in candidates}
    # Sortierung nach Gewicht, bei Gleichstand nach Profit-Wahrscheinlichkeit
    order = sorted(
        weights.items(),
        key=lambda kv: (round(kv[1], 6), by_ticker[kv[0]].profit_probability),
        reverse=True,
    )
    for ticker, w in order:
        a = by_ticker[ticker]
        amount = capital * w
        shares = amount / a.last_price if a.last_price > 0 else 0.0
        invested += amount
        allocations.append(
            Allocation(
                ticker=ticker,
                action=a.action,
                weight=w,
                amount=round(amount, 2),
                shares=round(shares, 4),
                last_price=a.last_price,
                reason=(f"P(Profit)={a.profit_probability:.0%}, "
                        f"Konfidenz={a.confidence:.0%}, "
                        f"Vola={getattr(a, 'volatility', 0.0):.1%}"),
            )
        )

    return Portfolio(
        capital=capital,
        allocations=allocations,
        invested=round(invested, 2),
        cash=round(capital - invested, 2),
        sells=sells,
    )


def _apply_cap(weights: dict[str, float], cap: float) -> dict[str, float]:
    """Begrenzt jede Position auf ``cap`` und verteilt den Überhang um."""
    weights = dict(weights)
    for _ in range(20):  # wenige Iterationen genügen zur Konvergenz
        over = {t: w for t, w in weights.items() if w > cap + 1e-9}
        if not over:
            break
        excess = sum(w - cap for w in over.values())
        for t in over:
            weights[t] = cap
        receivers = {t: w for t, w in weights.items() if w < cap - 1e-9}
        room = sum(cap - w for w in receivers.values())
        if room <= 0:
            break  # alles am Cap -> Rest bleibt Cash
        for t, w in receivers.items():
            weights[t] = w + excess * ((cap - w) / room)
    return weights


def _apply_sector_cap(
    weights: dict[str, float], sectors: dict[str, str], cap: float, pos_cap: float
) -> dict[str, float]:
    """Begrenzt den Gesamtanteil je Branche auf ``cap`` (Diversifikation).

    Überhänge übergewichteter Branchen werden auf Positionen anderer Branchen
    umverteilt (bis zur Positions-Obergrenze). Was nicht untergebracht werden
    kann, bleibt Cash.
    """
    weights = dict(weights)
    for _ in range(40):
        sect_tot: dict[str, float] = {}
        for t, w in weights.items():
            sect_tot.setdefault(sectors.get(t, "Sonstige"), 0.0)
            sect_tot[sectors.get(t, "Sonstige")] += w
        over = {s for s, tot in sect_tot.items() if tot > cap + 1e-9}
        if not over:
            break
        excess = 0.0
        for s in over:
            scale = cap / sect_tot[s]
            for t in weights:
                if sectors.get(t, "Sonstige") == s:
                    new = weights[t] * scale
                    excess += weights[t] - new
                    weights[t] = new
        receivers = [
            t for t in weights
            if sectors.get(t, "Sonstige") not in over and weights[t] < pos_cap - 1e-9
        ]
        room = sum(pos_cap - weights[t] for t in receivers)
        if excess <= 1e-9 or room <= 0:
            break  # nicht unterbringbar -> bleibt Cash
        for t in receivers:
            weights[t] += excess * ((pos_cap - weights[t]) / room)
    return weights
