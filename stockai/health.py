"""Selbstüberwachung: Wird die KI besser oder schlechter?

Wöchentlich macht die KI einen „Gesundheits-Check": Sie misst ihre aktuelle
Treffsicherheit, schreibt sie in einen Verlauf und **vergleicht mit dem letzten
Mal**. Verschlechtert sie sich spürbar (oder trifft schlechter als die
Basisrate), schlägt sie Alarm – so merkst du früh, wenn etwas aus dem Ruder
läuft, statt es erst spät zu bemerken.

Bevorzugt wird die **echte Live-Treffsicherheit** (Track-Record) genutzt; solange
davon noch zu wenig gesammelt ist, dient die Modellgüte (Holdout-AUC aus dem
letzten Training) als Ersatzsignal.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from stockai.config import Config

_HISTORY_FILE = "health_history.json"
_POSTURE_FILE = "posture.json"
_MIN_LIVE = 30        # ab so vielen Live-Prognosen zählt der Track-Record
_DROP = 0.03          # Verschlechterung > 3 %-Punkte = Warnung
_GAIN = 0.03          # Verbesserung > 3 %-Punkte = Lob
_STEP = 0.02          # Schrittweite der Vorsichts-Anpassung
_MAX_OFFSET = 0.06    # max. Anhebung der Kaufschwelle (defensiv gedeckelt)


@dataclass
class HealthReport:
    status: str = "🟡 zu wenig Daten"
    source: str = ""              # "live" oder "modell"
    metric_name: str = ""         # "Accuracy" oder "AUC"
    current: float = float("nan")
    previous: float = float("nan")
    base_rate: float = float("nan")
    n: int = 0
    warnings: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    posture: float = 0.0          # aktuelle Anhebung der Kaufschwelle (0..0.06)
    posture_change: float = 0.0   # Änderung in diesem Lauf (+ strenger / − lockerer)


def _path(cfg: Config) -> Path:
    return Path(cfg.store_dir) / _HISTORY_FILE


def _posture_path(cfg: Config) -> Path:
    return Path(cfg.store_dir) / _POSTURE_FILE


def load_posture(cfg: Config) -> float:
    """Aktuelle Vorsichts-Anhebung der Kaufschwelle (0 = normal)."""
    p = _posture_path(cfg)
    if not p.exists():
        return 0.0
    try:
        return float(json.load(open(p, encoding="utf-8")).get("buy_offset", 0.0))
    except Exception:
        return 0.0


def save_posture(cfg: Config, offset: float, reason: str) -> None:
    p = _posture_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    json.dump({"buy_offset": round(offset, 4), "reason": reason,
               "updated": datetime.now(timezone.utc).isoformat()},
              open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def _load(cfg: Config) -> list:
    p = _path(cfg)
    if not p.exists():
        return []
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return []


def _append(cfg: Config, snap: dict) -> None:
    p = _path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    hist = _load(cfg)
    hist.append({"timestamp": datetime.now(timezone.utc).isoformat(), **snap})
    json.dump(hist, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def _last_model_auc(cfg: Config) -> float | None:
    """Holt die jüngste Holdout-Güte (roc_auc, sonst accuracy) aus der Lern-Historie."""
    from stockai.model.store import ModelStore
    for h in reversed(ModelStore(cfg.model_dir).load_history()):
        m = h.get("metrics", {})
        if "roc_auc" in m and m["roc_auc"] == m["roc_auc"]:
            return float(m["roc_auc"])
        if "accuracy" in m and m["accuracy"] == m["accuracy"]:
            return float(m["accuracy"])
    return None


def assess_health(cfg: Config, record: bool = True) -> HealthReport:
    """Erstellt einen Gesundheits-Check, vergleicht mit dem letzten und warnt."""
    from stockai import track as tk

    rep = HealthReport()
    tr = tk.build_track_record(cfg)

    # Quelle wählen: echte Live-Treffer, sonst Modellgüte
    if tr.n_labeled >= _MIN_LIVE:
        rep.source = "live"
        rep.metric_name = "Accuracy"
        rep.current = tr.accuracy
        rep.base_rate = tr.base_rate
        rep.n = tr.n_labeled
        if tr.edge == tr.edge:
            rep.notes.append(f"Mehrwert der Auswahl (P≥55%): {tr.edge:+.1%}")
    else:
        auc = _last_model_auc(cfg)
        if auc is None:
            rep.notes.append("Noch kein Trainings-/Live-Ergebnis vorhanden.")
            return rep
        rep.source = "modell"
        rep.metric_name = "AUC"
        rep.current = auc
        rep.notes.append(f"Erst {tr.n_labeled} Live-Prognosen – nutze Modellgüte, "
                         "bis genug live gesammelt ist.")

    # vorherigen Snapshot gleicher Quelle finden
    prev = next((s for s in reversed(_load(cfg)) if s.get("source") == rep.source), None)
    if prev:
        rep.previous = float(prev.get("metric", float("nan")))

    if record:
        _append(cfg, {"source": rep.source, "metric": round(rep.current, 4),
                      "metric_name": rep.metric_name, "n": rep.n})

    # Bewertung -----------------------------------------------------------
    if rep.previous == rep.previous:                 # nicht NaN
        delta = rep.current - rep.previous
        if delta <= -_DROP:
            rep.status = "⚠️ schlechter"
            rep.warnings.append(
                f"{rep.metric_name} fiel {abs(delta):.1%} (von {rep.previous:.1%} "
                f"auf {rep.current:.1%}).")
        elif delta >= _GAIN:
            rep.status = "📈 besser"
        else:
            rep.status = "✅ stabil"
    else:
        rep.status = "✅ erster Messpunkt"

    # harte Warnungen (unabhängig vom Trend)
    if rep.source == "live":
        if rep.base_rate == rep.base_rate and rep.current < rep.base_rate - 0.01:
            rep.warnings.append(
                f"Trifft schlechter als die Basisrate ({rep.current:.1%} < "
                f"{rep.base_rate:.1%}) – Empfehlungen mit Vorsicht genießen.")
        if rep.current < 0.5:
            rep.warnings.append("Live-Accuracy unter 50 % – kein verlässlicher Vorteil.")
    elif rep.current < 0.5:
        rep.warnings.append("Modell-AUC unter 0.5 – schlechter als Zufall.")

    if rep.warnings:
        rep.status = "⚠️ schlechter"

    # --- Automatisches Gegensteuern (Selbst-Regulierung) ------------------
    # Verschlechtert sich die KI, wird sie vorsichtiger (höhere Kaufschwelle);
    # erholt sie sich, lockert sie schrittweise wieder. Gedeckelt & reversibel.
    rep.posture = load_posture(cfg)
    if rep.warnings:                                  # strenger werden
        new_off = min(_MAX_OFFSET, rep.posture + _STEP)
    elif rep.status.startswith("📈") or (             # lockern, wenn wieder gut
            rep.source == "live" and rep.base_rate == rep.base_rate
            and rep.current >= rep.base_rate):
        new_off = max(0.0, rep.posture - _STEP)
    else:
        new_off = rep.posture                         # stabil: halten
    rep.posture_change = round(new_off - rep.posture, 4)
    if record and new_off != rep.posture:
        save_posture(cfg, new_off, reason=rep.status)
    rep.posture = new_off
    return rep


def render_health(rep: HealthReport) -> str:
    lines = ["🩺 Selbstcheck der KI"]
    if rep.current != rep.current:                   # NaN
        lines.append("\nNoch keine Messung möglich – einfach weiterlaufen lassen.")
        for n in rep.notes:
            lines.append(f"• {n}")
        return "\n".join(lines)

    lines.append(f"Status: {rep.status}")
    src = "Live-Treffsicherheit" if rep.source == "live" else "Modellgüte (Holdout)"
    extra = f" über {rep.n} Prognosen" if rep.n else ""
    lines.append(f"Quelle: {src}{extra}")
    cur = f"{rep.metric_name}: {rep.current:.1%}"
    if rep.previous == rep.previous:
        arrow = "↗︎" if rep.current >= rep.previous else "↘︎"
        cur += f"  ({arrow} vorher {rep.previous:.1%})"
    lines.append(cur)
    if rep.base_rate == rep.base_rate:
        lines.append(f"Basisrate: {rep.base_rate:.1%}")

    for n in rep.notes:
        lines.append(f"• {n}")
    if rep.warnings:
        lines.append("")
        for w in rep.warnings:
            lines.append(f"⚠️ {w}")

    # Selbst-Regulierung transparent machen
    if rep.posture_change > 0:
        lines.append(f"\n🛡️ Gegensteuern: Kaufschwelle wird strenger "
                     f"(+{rep.posture:.0%} statt +{rep.posture - rep.posture_change:.0%}).")
    elif rep.posture_change < 0:
        lines.append(f"\n✅️ Erholung: Kaufschwelle wird gelockert "
                     f"(jetzt +{rep.posture:.0%}).")
    elif rep.posture > 0:
        lines.append(f"\n🛡️ Aktuell vorsichtiger: Kaufschwelle +{rep.posture:.0%} "
                     "(bis sich die Treffsicherheit erholt).")

    lines.append("\nℹ️ Keine Anlageberatung.")
    return "\n".join(lines)
