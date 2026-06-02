"""Sparplan-Generator (Core-Satellite) aus den KI-Analysen.

Erzeugt aus einem monatlichen Sparbetrag einen konkreten, wiederkehrenden
Investitionsplan:

    * **Core** – breite ETFs/Fonds als risikoärmere Basis (fester Anteil).
    * **Satelliten** – die aktuell aussichtsreichsten Einzelaktien laut Modell,
      gewichtet nach Profit-Wahrscheinlichkeit und Konfidenz, mit Obergrenze
      je Position zur Streuung.

Bei jeder Ausführung auf frischen Daten passt sich der Plan an: Aktien, die im
Ranking fallen, werden reduziert oder fallen raus, neue Favoriten rücken nach.
So entsteht ein „lebender" Sparplan.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from stockai.config import Config
from stockai.portfolio import _apply_cap, _apply_sector_cap


@dataclass
class PlanPosition:
    instrument: str
    kind: str            # "ETF" oder "Aktie"
    monthly: float       # €/Monat
    weight: float        # Anteil am Sparbetrag
    probability: float
    action: str
    reason: str


@dataclass
class SavingsPlan:
    monthly_amount: float
    core_share: float
    positions: list[PlanPosition] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def core_positions(self) -> list[PlanPosition]:
        return [p for p in self.positions if p.kind == "ETF"]

    @property
    def satellite_positions(self) -> list[PlanPosition]:
        return [p for p in self.positions if p.kind == "Aktie"]

    @property
    def crypto_positions(self) -> list[PlanPosition]:
        return [p for p in self.positions if p.kind == "Krypto"]


_BUY = {"BOOM", "KAUFEN"}

# Risiko-Profile: defensiver = mehr ETF-Core, weniger/kein Krypto, kleinere
# Einzelpositionen; offensiver = mehr Einzelaktien + Krypto, größere Positionen.
RISK_PRESETS = {
    "defensiv":   dict(core_share=0.75, crypto_share=0.0,  max_stocks=3,
                       max_stock_weight=0.10, max_crypto=1),
    "ausgewogen": dict(core_share=0.50, crypto_share=0.10, max_stocks=5,
                       max_stock_weight=0.15, max_crypto=2),
    "offensiv":   dict(core_share=0.30, crypto_share=0.20, max_stocks=7,
                       max_stock_weight=0.20, max_crypto=3),
}


def build_savings_plan(
    cfg: Config,
    monthly_amount: float = 100.0,
    core_share: float = 0.5,
    max_stock_weight: float = 0.15,
    max_stocks: int = 5,
    crypto_share: float = 0.10,
    max_crypto: int = 2,
    risk: str | None = None,
) -> SavingsPlan:
    """Erstellt einen Sparplan aus dem aktuellen Analyse-Ranking.

    Args:
        monthly_amount: monatlicher Sparbetrag in €.
        core_share: Anteil, der in breite ETFs (Core) fließt.
        max_stock_weight: maximaler Anteil einer Einzelaktie am Sparbetrag.
        max_stocks: maximale Anzahl Einzelaktien (Satelliten).
        crypto_share: maximaler Anteil für Krypto (höheres Risiko -> klein).
        max_crypto: maximale Anzahl Krypto-Positionen.
        risk: optionales Risiko-Profil (defensiv|ausgewogen|offensiv); überschreibt
            Core-/Krypto-Anteil und Streuungs-Grenzen passend zur Risikoneigung.
    """
    if risk and risk in RISK_PRESETS:
        p = RISK_PRESETS[risk]
        core_share, crypto_share = p["core_share"], p["crypto_share"]
        max_stocks, max_stock_weight = p["max_stocks"], p["max_stock_weight"]
        max_crypto = p["max_crypto"]

    from stockai import pipeline

    etfs = list(cfg.etfs)
    stocks = list(cfg.tickers)
    cryptos = list(getattr(cfg, "crypto", []))
    analyses = pipeline.analyze(cfg, universe_override=stocks + etfs + cryptos)
    by_ticker = {a.ticker: a for a in analyses}
    # Krypto reduziert den für Aktien-Satelliten verfügbaren Anteil
    crypto_share = crypto_share if cryptos else 0.0

    plan = SavingsPlan(monthly_amount=monthly_amount, core_share=core_share)

    # --- Core: ETFs gleichgewichtet (breite Streuung als Basis) ---------- #
    core_etfs = [t for t in etfs if t in by_ticker]
    core_budget = monthly_amount * core_share if core_etfs else 0.0
    for t in core_etfs:
        a = by_ticker[t]
        w = (core_share / len(core_etfs))
        plan.positions.append(PlanPosition(
            instrument=t, kind="ETF", monthly=round(monthly_amount * w, 2),
            weight=w, probability=a.profit_probability, action=a.action,
            reason="Breit gestreute Basis (Core)",
        ))
    if not core_etfs:
        plan.notes.append("Keine ETFs verfügbar – Core übersprungen.")
        core_share = 0.0

    # --- Satelliten: beste Aktien laut Modell ---------------------------- #
    # Regime-Bremse: in Abschwüngen weniger in Einzelaktien, mehr in den ETF-Core.
    from stockai.portfolio import _regime_exposure
    exposure = _regime_exposure(analyses)
    sat_budget_share = max(0.0, 1.0 - core_share - crypto_share)
    if exposure < 0.999 and core_etfs:
        defensiv = sat_budget_share * (1.0 - exposure)
        sat_budget_share -= defensiv
        # freigewordenen Anteil gleichmäßig in die ETFs umlenken
        for p in plan.core_positions:
            p.weight += defensiv / len(core_etfs)
            p.monthly = round(monthly_amount * p.weight, 2)
        plan.notes.append(
            f"Defensiv (Marktlage): {defensiv:.0%} von Aktien in ETF-Core verschoben.")
    candidates = [
        by_ticker[t] for t in stocks
        if t in by_ticker and by_ticker[t].action in _BUY
    ]
    candidates.sort(key=lambda a: a.profit_probability, reverse=True)
    candidates = candidates[:max_stocks]

    if candidates:
        # Gewichtung nach Profit-Wahrscheinlichkeit × Konfidenz und – falls
        # verfügbar – verstärkt durch die erwartete Rendite (Expected Return).
        def _score(a) -> float:
            base = max(1e-6, (a.profit_probability - 0.5)) * max(0.1, a.confidence)
            if a.expected_return is not None and a.expected_return > 0:
                base *= (1.0 + 10.0 * a.expected_return)
            return base

        raw = {a.ticker: _score(a) for a in candidates}
        total = sum(raw.values())
        weights = {t: (w / total) * sat_budget_share for t, w in raw.items()}
        # Obergrenze je Aktie, dann je Branche (Diversifikation der Satelliten)
        weights = _apply_cap(weights, max_stock_weight)
        if cfg.sectors:
            sector_cap = min(sat_budget_share, max(max_stock_weight, sat_budget_share * 0.6))
            weights = _apply_sector_cap(weights, cfg.sectors, sector_cap, max_stock_weight)
        for a in candidates:
            w = weights[a.ticker]
            if w <= 0:
                continue
            plan.positions.append(PlanPosition(
                instrument=a.ticker, kind="Aktie", monthly=round(monthly_amount * w, 2),
                weight=w, probability=a.profit_probability, action=a.action,
                reason=f"Top-Signal: P(Profit)={a.profit_probability:.0%}, "
                       f"Konfidenz {a.confidence:.0%}",
            ))
    else:
        plan.notes.append(
            "Aktuell keine überzeugenden Aktien-Signale – Satelliten-Anteil "
            "fließt in den ETF-Core (defensiv)."
        )
        # Restbudget in die ETFs umlenken
        if core_etfs:
            extra = sat_budget_share / len(core_etfs)
            for p in plan.core_positions:
                p.weight += extra
                p.monthly = round(monthly_amount * p.weight, 2)

    # --- Krypto-Topf: klein gehalten (höheres Risiko) -------------------- #
    if crypto_share > 0:
        crypto_cands = [
            by_ticker[t] for t in cryptos
            if t in by_ticker and by_ticker[t].action in _BUY
        ]
        crypto_cands.sort(key=lambda a: a.profit_probability, reverse=True)
        crypto_cands = crypto_cands[:max_crypto]
        if crypto_cands:
            craw = {a.ticker: max(1e-6, (a.profit_probability - 0.5)) * max(0.1, a.confidence)
                    for a in crypto_cands}
            ctotal = sum(craw.values())
            for a in crypto_cands:
                w = (craw[a.ticker] / ctotal) * crypto_share
                plan.positions.append(PlanPosition(
                    instrument=a.ticker, kind="Krypto",
                    monthly=round(monthly_amount * w, 2), weight=w,
                    probability=a.profit_probability, action=a.action,
                    reason=f"Krypto-Beimischung (höheres Risiko): "
                           f"P(Profit)={a.profit_probability:.0%}",
                ))
        else:
            plan.notes.append("Krypto: aktuell kein positives Signal – ausgelassen.")

    # Hinweis auf gemiedene Einzelaktien (ETFs bleiben bewusst Core/Cost-Averaging)
    avoid = [a.ticker for a in analyses
             if a.action in ("VERKAUFEN", "MEIDEN") and a.ticker in stocks]
    if avoid:
        plan.notes.append("Aktuell gemiedene Aktien (negatives Signal): " + ", ".join(avoid))

    invested = sum(p.monthly for p in plan.positions)
    if invested < monthly_amount - 0.01:
        plan.notes.append(
            f"{monthly_amount - invested:.2f}€ bleiben als Puffer/Cash (Obergrenzen)."
        )
    if risk and risk in RISK_PRESETS:
        plan.notes.insert(0, f"Risiko-Profil: {risk} (Core {core_share:.0%}, "
                             f"Krypto bis {crypto_share:.0%}).")
    return plan
