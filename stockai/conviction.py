"""Conviction-Score: alle Signale der KI in *einer* transparenten Kennzahl.

Statt nur die Modell-Wahrscheinlichkeit zu zeigen, bündelt der Conviction-Score
mehrere unabhängige Belege zu einer Gesamt-Überzeugung (0–100):

    * Modell-Wahrscheinlichkeit (Hauptfaktor)
    * Übereinstimmung über mehrere Horizonte (1/5/20 Tage)
    * erwartete Rendite (Regressor)
    * News-Sentiment
    * Volumen-Bestätigung (Whale-/Smart-Money-Spur)
    * Abzug, wenn die Lage in einer gelernten Schwachstelle liegt

Das ist eine **transparente Aggregation** (kein separates Black-Box-Modell): Die
Beiträge werden offen ausgewiesen, damit nachvollziehbar bleibt, *warum* die KI
überzeugt ist – oder eben nicht. Keine Anlageberatung.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Conviction:
    score: float = 50.0          # 0..100, 50 = neutral
    label: str = "moderat"
    parts: list = field(default_factory=list)   # (Name, Beitrag in Punkten)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def compute_conviction(a) -> Conviction:
    """Berechnet den Conviction-Score aus einer ``TickerAnalysis``."""
    parts: list[tuple[str, float]] = []

    # 1) Modell-Wahrscheinlichkeit – Hauptfaktor (-40 .. +40)
    model = _clamp((a.profit_probability - 0.5) * 80, -40, 40)
    parts.append(("Modell-Wahrscheinlichkeit", model))

    # 2) Mehr-Horizont-Übereinstimmung (-10 .. +10)
    hz = getattr(a, "horizon_probs", None) or {}
    if hz:
        mean_h = sum(hz.values()) / len(hz)
        horizon = _clamp((mean_h - 0.5) * 40, -10, 10)
        # Bonus, wenn ALLE Horizonte in dieselbe Richtung zeigen
        if all(p >= 0.5 for p in hz.values()) and a.profit_probability >= 0.5:
            horizon = min(10, horizon + 3)
        elif all(p < 0.5 for p in hz.values()) and a.profit_probability < 0.5:
            horizon = max(-10, horizon - 3)
        parts.append(("Horizont-Übereinstimmung", horizon))

    # 3) Erwartete Rendite (-10 .. +10)
    if a.expected_return is not None:
        er = _clamp(a.expected_return * 200, -10, 10)
        parts.append(("Erwartete Rendite", er))

    # 4) News-Sentiment (-6 .. +6)
    sent = _clamp(a.sentiment_mean * 20, -6, 6)
    if abs(sent) >= 1:
        parts.append(("News-Sentiment", sent))

    # 5) Volumen-Bestätigung (Whale-Spur): viel Volumen + steigender Kurs = Rückenwind
    rel_vol = getattr(a, "rel_volume", 1.0) or 1.0
    if rel_vol >= 1.5:
        vol = _clamp((rel_vol - 1.0) * 6, 0, 8)
        if a.momentum_5d < 0:
            vol = -vol                    # Volumen + fallender Kurs = Gegenwind
        parts.append(("Volumen-Bestätigung", vol))

    # 6) Schwachstellen-Abzug: in einer gelernten Schwäche vorsichtiger
    if getattr(a, "weak_segment", False):
        parts.append(("Gelernte Schwachstelle", -10.0))

    score = _clamp(50.0 + sum(p for _, p in parts), 0, 100)
    return Conviction(score=score, label=_label(score), parts=parts)


def _label(score: float) -> str:
    if score >= 72:
        return "sehr hoch"
    if score >= 60:
        return "hoch"
    if score >= 50:
        return "moderat"
    if score >= 40:
        return "schwach"
    return "sehr schwach"


def _bar(score: float) -> str:
    filled = int(round(score / 10))
    return "█" * filled + "░" * (10 - filled)


def render_conviction(a, conv: Conviction | None = None) -> str:
    """Erklärbarer Conviction-Block für die Einzelanalyse."""
    conv = conv or compute_conviction(a)
    lines = [f"🎯 Conviction: {conv.score:.0f}/100 ({conv.label})  {_bar(conv.score)}",
             "Beiträge:"]
    for name, pts in sorted(conv.parts, key=lambda kv: abs(kv[1]), reverse=True):
        icon = "➕" if pts > 0 else ("➖" if pts < 0 else "·")
        lines.append(f"  {icon} {name}: {pts:+.0f}")
    return "\n".join(lines)
