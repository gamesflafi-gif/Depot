"""Sektor-Rotation: wohin fließt das Geld – über ganze Branchen hinweg.

Statt nur Einzelwerte zu ranken, fasst dieses Modul die KI-Analysen je **Branche**
zusammen (Tech, Financials, Energy …) und zeigt, welche Sektoren gerade führen
und welche zurückfallen. Das ist „Markt-Abdeckung aus der Vogelperspektive": ein
real belegter Effekt (Sektor-Momentum/Rotation) und ein Frühindikator dafür,
wo sich Chancen häufen. Keine Anlageberatung.
"""
from __future__ import annotations

from dataclasses import dataclass

from stockai.config import Config

_BUY = {"BOOM", "KAUFEN"}


@dataclass
class SectorStat:
    sector: str
    n: int
    mean_conviction: float
    mean_momentum: float
    pct_bullish: float
    top_ticker: str = ""
    top_conviction: float = float("nan")


def sector_rotation(cfg: Config, analyses=None, use_cache: bool = False) -> list[SectorStat]:
    """Aggregiert die Analysen je Branche und sortiert nach Stärke (Conviction)."""
    from stockai import pipeline
    if analyses is None:
        analyses = pipeline.analyze(cfg, use_cache=use_cache)

    buckets: dict[str, list] = {}
    for a in analyses:
        sector = cfg.sectors.get(a.ticker)
        if not sector:                       # nur klassifizierte Einzelaktien
            continue
        buckets.setdefault(sector, []).append(a)

    stats: list[SectorStat] = []
    for sector, group in buckets.items():
        convs = [a.conviction for a in group if a.conviction == a.conviction]
        if not convs:
            continue
        top = max(group, key=lambda a: (a.conviction if a.conviction == a.conviction else 0))
        stats.append(SectorStat(
            sector=sector, n=len(group),
            mean_conviction=sum(convs) / len(convs),
            mean_momentum=sum(a.momentum_5d for a in group) / len(group),
            pct_bullish=sum(1 for a in group if a.action in _BUY) / len(group),
            top_ticker=top.ticker, top_conviction=top.conviction,
        ))
    stats.sort(key=lambda s: s.mean_conviction, reverse=True)
    return stats


def render_sectors(stats: list[SectorStat]) -> str:
    if not stats:
        return "🧭 Sektor-Rotation: noch keine Daten (Universum/Sektoren prüfen)."
    lines = ["🧭 Sektor-Rotation – wohin fließt das Geld", ""]
    for i, s in enumerate(stats):
        if i == 0:
            mark = "🥇"
        elif i == len(stats) - 1 and len(stats) > 2:
            mark = "🐌"
        else:
            mark = "  "
        lines.append(
            f"{mark} {s.sector:18s} 🎯 {s.mean_conviction:4.0f} · "
            f"Mom {s.mean_momentum:+.1%} · {s.pct_bullish:.0%} bullisch · "
            f"Top: {s.top_ticker}")
    lead = stats[0]
    lines.append(f"\n→ Stärkste Branche: {lead.sector} (Top-Wert {lead.top_ticker}, "
                 f"🎯 {lead.top_conviction:.0f}).")
    lines.append("ℹ️ Keine Anlageberatung.")
    return "\n".join(lines)
