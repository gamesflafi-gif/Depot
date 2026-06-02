"""Entscheidungs-/Advisor-Schicht der KI.

Aus dem gelernten Modell (Profitabilitäts-Wahrscheinlichkeit) plus technischem
Zustand und News-Sentiment leitet die KI eigenständig eine Handlungsempfehlung
ab: Welche Aktien könnten *boomen*, was sollte man *halten*, und *wann* ist es
sinnvoll zu *verkaufen* (Gewinnmitnahme / Risiko).

Die Regeln sind bewusst transparent und nachvollziehbar (erklärbare KI),
statt einer Blackbox-Empfehlung. Sie kombinieren das gelernte Signal mit
klassischen Timing-Heuristiken (RSI-Überkauft, Momentum, Abstand zum Hoch).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Recommendation:
    action: str           # BOOM, KAUFEN, HALTEN, VERKAUFEN, MEIDEN
    confidence: float     # 0..1
    reasons: list[str]    # nachvollziehbare Begründungen
    timing: str           # Hinweis zum Zeitpunkt (v.a. fürs Verkaufen)


def recommend(
    profit_probability: float,
    rsi_14: float,
    momentum_5d: float,
    price_vs_high_20: float,
    macd_hist: float,
    sentiment_mean: float,
    expected_return: float | None = None,
    weak_conditions: list[str] | None = None,
) -> Recommendation:
    """Leitet eine Handlungsempfehlung ab.

    Args:
        profit_probability: gelernte Wahrscheinlichkeit, dass die Aktie über
            den Horizont profitabel wird (0..1).
        rsi_14: Relative-Strength-Index (Überkauft > 70, Überverkauft < 30).
        momentum_5d: Rendite der letzten 5 Tage.
        price_vs_high_20: Kurs relativ zum 20-Tage-Hoch (1.0 = am Hoch).
        macd_hist: MACD minus Signallinie (> 0 = Aufwärtsmomentum).
        sentiment_mean: durchschnittliches News-Sentiment (-1..1).
        expected_return: optionale erwartete Folge-Rendite (vom Regressor).
            Ist sie klar negativ, wird trotz positiver Wahrscheinlichkeit kein
            Kaufsignal gegeben (Konsistenz beider Modelle).
        weak_conditions: Klartext-Warnungen aus der Schwachstellen-Analyse
            (``weakspots``). Trifft die aktuelle Lage auf eine Bedingung, in der
            die KI historisch danebenlag, wird ein Kaufsignal um eine Stufe
            gedämpft (BOOM→KAUFEN, KAUFEN→HALTEN) – die KI lernt aus Fehlern.
    """
    reasons: list[str] = []

    # --- Verkaufs-/Timing-Signale (haben Vorrang vor Kaufsignalen) ------- #
    overbought = rsi_14 >= 70
    near_high = price_vs_high_20 >= 0.98
    momentum_fading = macd_hist < 0 and momentum_5d < 0

    if overbought:
        reasons.append(f"RSI {rsi_14:.0f} ≥ 70 → überkauft, Rücksetzer-Risiko")
    if near_high:
        reasons.append("Kurs am 20-Tage-Hoch → Gewinnmitnahme erwägen")
    if momentum_fading:
        reasons.append("MACD dreht negativ + fallendes Momentum → Schwäche")
    if sentiment_mean < -0.15:
        reasons.append(f"Negatives News-Sentiment ({sentiment_mean:+.2f})")

    # Verkaufslogik: hoch gelaufen + Erschöpfung – ABER nur, wenn das Modell
    # nicht mehr bullisch ist. (Echtdaten zeigten: rein technische Verkäufe im
    # Aufwärtstrend trafen nur ~16 % – wir verkaufen daher keine Gewinner mehr,
    # die das Modell weiter positiv sieht.)
    model_bearish = profit_probability < 0.52 or (
        expected_return is not None and expected_return < 0.0)
    if (overbought or near_high) and (momentum_fading or sentiment_mean < -0.1) \
            and model_bearish:
        return Recommendation(
            action="VERKAUFEN",
            confidence=min(0.9, 0.5 + abs(macd_hist) + (rsi_14 - 70) / 100 if overbought else 0.55),
            reasons=(reasons or ["Erschöpfungssignale nach Aufwärtsbewegung"]) +
                    [f"Modell nicht mehr bullisch (P {profit_probability:.0%})"],
            timing="Jetzt / in Stärke verkaufen – Aufwärtstrend zeigt Ermüdung.",
        )

    # --- Kauf-/Boom-Signale --------------------------------------------- #
    strong_signal = profit_probability >= 0.62
    momentum_up = macd_hist > 0 and momentum_5d > 0.01
    positive_news = sentiment_mean > 0.15
    not_overheated = rsi_14 < 68
    # Kein Kauf, wenn die erwartete Rendite klar negativ ist (Modell-Konsens)
    er_negative = expected_return is not None and expected_return < -0.005
    if er_negative:
        reasons.append(f"Erwartete Rendite {expected_return:+.1%} negativ → kein Kauf")

    # Aus Fehlern gelernt: in historisch schwachen Bedingungen eine Stufe
    # vorsichtiger werden (transparent begründet).
    weak = bool(weak_conditions)
    if weak:
        for w in weak_conditions:
            reasons.append(f"⚠️ Schwachstelle gelernt – {w}")

    if strong_signal and momentum_up and not_overheated and not er_negative:
        if positive_news:
            reasons.append(f"Positives News-Sentiment ({sentiment_mean:+.2f})")
        reasons.append(f"Modell: {profit_probability:.0%} Profit-Wahrscheinlichkeit")
        reasons.append("Aufwärtsmomentum (MACD+ & 5T-Rendite+)")
        if weak:   # BOOM → KAUFEN herabstufen
            return Recommendation(
                action="KAUFEN", confidence=profit_probability * 0.9, reasons=reasons,
                timing="Einstieg möglich, aber vorsichtig: ähnliche Lagen liefen "
                       "zuletzt unterdurchschnittlich. Klein starten.",
            )
        return Recommendation(
            action="BOOM",
            confidence=profit_probability,
            reasons=reasons,
            timing="Früh im Trend – Einstieg/Aufstockung sinnvoll, solange RSI < 70.",
        )

    if profit_probability >= 0.55 and not_overheated and not er_negative:
        reasons.append(f"Modell: {profit_probability:.0%} Profit-Wahrscheinlichkeit")
        if weak:   # KAUFEN → HALTEN: in schwacher Lage lieber abwarten
            return Recommendation(
                action="HALTEN", confidence=0.5, reasons=reasons,
                timing="Abwarten – Signal ok, aber in dieser Lage lag die KI "
                       "zuletzt häufiger daneben.",
            )
        return Recommendation(
            action="KAUFEN",
            confidence=profit_probability,
            reasons=reasons,
            timing="Einstieg möglich; Position klein halten und Momentum beobachten.",
        )

    if profit_probability <= 0.42:
        reasons.append(f"Modell: nur {profit_probability:.0%} Profit-Wahrscheinlichkeit")
        return Recommendation(
            action="MEIDEN",
            confidence=1.0 - profit_probability,
            reasons=reasons,
            timing="Kein Einstieg – Signallage negativ.",
        )

    reasons.append(f"Modell: {profit_probability:.0%} – kein klares Signal")
    return Recommendation(
        action="HALTEN",
        confidence=0.5,
        reasons=reasons,
        timing="Abwarten – kein eindeutiges Kauf-/Verkaufssignal.",
    )
