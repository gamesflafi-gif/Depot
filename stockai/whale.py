"""Whale-Signale: auffällig hohes Volumen als Smart-Money-Spur.

Große Adressen/Fonds („Whales") hinterlassen eine Spur: **ungewöhnlich hohes
Handelsvolumen**. Dieses Modul scannt alle beobachteten Werte und meldet, wo das
Volumen deutlich über dem Schnitt liegt – und ob es eher nach **Akkumulation**
(Volumen + steigender Kurs) oder **Distribution** (Volumen + fallender Kurs)
aussieht.

Ehrlich eingeordnet: Mit frei verfügbaren Kursdaten sehen wir den *Fußabdruck*
(das Volumen), nicht die einzelne Wallet. Das ist ein nützliches Frühsignal,
keine Garantie – und keine Anlageberatung.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from stockai.config import Config


@dataclass
class WhaleSignal:
    ticker: str
    asset_class: str
    rel_volume: float          # Volumen / 20-Tage-Schnitt (>1 = überdurchschnittlich)
    price_change: float        # Tagesrendite (ret_1d)
    direction: str             # "Akkumulation" | "Distribution" | "neutral"

    @property
    def strength(self) -> float:
        # Stärke = wie ungewöhnlich das Volumen, gewichtet mit der Kursreaktion
        return self.rel_volume * (1.0 + min(abs(self.price_change), 0.2) * 5)


@dataclass
class WhaleScan:
    signals: list = field(default_factory=list)
    n_scanned: int = 0


def scan_whales(cfg: Config, min_rel: float = 2.0, top_n: int = 10) -> WhaleScan:
    """Sucht Werte mit ungewöhnlich hohem Volumen (rel. Volumen ≥ ``min_rel``)."""
    from stockai import pipeline
    from stockai.data import provider
    from stockai.features.technical import add_technical_features

    scan = WhaleScan()
    for ticker in pipeline.universe(cfg):
        try:
            prices = provider.get_prices(cfg, ticker)
            if prices.empty or len(prices) < 25:
                continue
            feat = add_technical_features(prices)
            last = feat.iloc[-1]
        except Exception:
            continue
        scan.n_scanned += 1
        rel = float(last.get("rel_volume", float("nan")))
        chg = float(last.get("ret_1d", 0.0) or 0.0)
        if rel != rel or rel < min_rel:                # NaN oder unter Schwelle
            continue
        if chg > 0.005:
            direction = "Akkumulation"
        elif chg < -0.005:
            direction = "Distribution"
        else:
            direction = "neutral"
        scan.signals.append(WhaleSignal(
            ticker=ticker, asset_class=pipeline.asset_class(cfg, ticker),
            rel_volume=rel, price_change=chg, direction=direction))

    scan.signals.sort(key=lambda s: s.strength, reverse=True)
    scan.signals = scan.signals[:top_n]
    return scan


def whale_alert_text(cfg: Config, min_rel: float = 2.5) -> str | None:
    """Nur Text, wenn es starke Whale-Signale gibt (für tägliche Push-Meldung)."""
    scan = scan_whales(cfg, min_rel=min_rel)
    if not scan.signals:
        return None
    return render_whales(scan)


def render_whales(scan: WhaleScan) -> str:
    if not scan.signals:
        return ("Keine auffälligen Volumen-Signale gerade "
                f"({scan.n_scanned} Werte geprüft).")
    lines = ["Whale-Radar – auffälliges Volumen (mögliche Smart-Money-Aktivität)", ""]
    for s in scan.signals:
        icon = {"Akkumulation": "+", "Distribution": "-", "neutral": "•"}[s.direction]
        lines.append(f"{icon} {s.ticker} ({s.asset_class}) · {s.rel_volume:.1f}× Volumen · "
                     f"{s.price_change:+.1%} · {s.direction}")
    lines.append("\nAkkumulation = Volumen + steigender Kurs · "
                 "Distribution = Volumen + fallender Kurs")
    lines.append("Fußabdruck im Volumen, keine Garantie. Keine Anlageberatung.")
    return "\n".join(lines)
