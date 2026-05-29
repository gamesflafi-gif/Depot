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


def build_portfolio(
    analyses,
    capital: float = 10_000.0,
    max_position_pct: float = 0.25,
    buy_actions=("BOOM", "KAUFEN"),
) -> Portfolio:
    """Erzeugt einen Allokationsvorschlag aus Analyse-Ergebnissen.

    Args:
        analyses: Liste von ``TickerAnalysis`` (aus pipeline.analyze).
        capital: verfügbares Gesamtkapital.
        max_position_pct: maximaler Kapitalanteil je Einzelposition.
        buy_actions: welche Empfehlungen als Kaufkandidaten gelten.
    """
    candidates = [a for a in analyses if a.action in buy_actions]
    sells = [a.ticker for a in analyses if a.action in ("VERKAUFEN", "MEIDEN")]

    if not candidates:
        return Portfolio(capital=capital, allocations=[], invested=0.0,
                         cash=capital, sells=sells)

    # Rohgewichte: Überschuss der Wahrscheinlichkeit über 0.5, skaliert mit Konfidenz
    raw = {
        a.ticker: max(0.0, (a.profit_probability - 0.5)) * max(0.1, a.confidence)
        for a in candidates
    }
    total = sum(raw.values())
    if total <= 0:
        # Gleichgewichtung, falls keine klare Differenzierung
        weights = {t: 1.0 / len(candidates) for t in raw}
    else:
        weights = {t: w / total for t, w in raw.items()}

    # Risiko-Cap je Position + iterative Umverteilung des Überhangs
    weights = _apply_cap(weights, max_position_pct)

    allocations: list[Allocation] = []
    invested = 0.0
    by_ticker = {a.ticker: a for a in candidates}
    for ticker, w in sorted(weights.items(), key=lambda kv: kv[1], reverse=True):
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
                reason=f"P(Profit)={a.profit_probability:.0%}, Konfidenz={a.confidence:.0%}",
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
