"""Schwachstellen-Analyse: wo liegt das Modell am häufigsten daneben?

Per Walk-Forward werden echte Prognosen erzeugt und gegen das reale Ergebnis
gestellt – aufgeschlüsselt nach vielen Bedingungen (RSI-Zone, News-Sentiment,
Marktlage, Momentum, Volatilität, Anlageklasse). So sieht man, *unter welchen
Umständen* die KI falsch deutet, und kann gezielt nachbessern. Mit ``period``
lässt sich eine lange Historie analysieren, um mehr aus der Vergangenheit zu
lernen; die erkannten Schwächen werden als „Lektionen" gespeichert und dämpfen
ab dann die täglichen Empfehlungen.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from stockai.config import Config

_LESSONS_FILE = "lessons.json"
_FLAG = -0.03    # Trefferquote >3 %-Punkte unter Basis = Schwachstelle
_VOL_CUT = 0.03  # Tages-Volatilität: darüber = "hohe Schwankung"


@dataclass
class WeakSpots:
    n: int = 0
    segments: list = field(default_factory=list)   # {dim, group, kind, count, hit, base, gap}
    base_rate: float = float("nan")


# maschinenlesbare Prüfungen je Bedingung (für die tägliche Selbstkorrektur).
# ``f`` ist ein Feature-Dict des aktuellen Kandidaten – so lassen sich beliebig
# viele Dimensionen prüfen.
def _matches(kind: str, f: dict) -> bool:
    rsi = f.get("rsi", 50.0); sent = f.get("sent", 0.0); regime = f.get("regime", 0.0)
    vol = f.get("vol", 0.02); mom = f.get("mom", 0.0); cls = f.get("cls", "")
    if kind.startswith("class_"):
        return cls == kind[len("class_"):]
    return {
        "rsi_low":  rsi < 30,
        "rsi_mid":  30 <= rsi <= 70,
        "rsi_high": rsi > 70,
        "sent_neg": sent < -0.1,
        "sent_neu": -0.1 <= sent <= 0.1,
        "sent_pos": sent > 0.1,
        "regime_down": regime < 0,
        "regime_up":   regime >= 0,
        "vol_high": vol > _VOL_CUT,
        "vol_low":  vol <= _VOL_CUT,
        "mom_neg": mom < 0,
        "mom_pos": mom >= 0,
    }.get(kind, False)


def _segment(df: pd.DataFrame, dim: str, labels: dict) -> list:
    """labels: key -> (mask, kind) – kind macht die Bedingung später prüfbar."""
    out = []
    base = df["target"].mean()
    for key, (mask, kind) in labels.items():
        grp = df[mask]
        if len(grp) < 20:
            continue
        hit = float(grp["target"].mean())
        out.append({"dim": dim, "group": key, "kind": kind, "count": int(len(grp)),
                    "hit": hit, "base": float(base), "gap": hit - float(base)})
    return out


def analyze_weakspots(cfg: Config, train_frac: float = 0.4,
                      period: str | None = None) -> WeakSpots:
    """Walk-Forward über das Panel; segmentiert die Treffsicherheit der
    Kaufsignale nach vielen Bedingungen. ``period`` (z.B. "10y") analysiert eine
    längere Historie, um mehr aus der Vergangenheit zu lernen.
    """
    from stockai.strategy import _build_panel
    from stockai.pipeline import FEATURE_COLUMNS, resolve_model_type, asset_class
    from stockai.model.predictor import Predictor

    panel = _build_panel(cfg, period=period)
    res = WeakSpots()
    if panel.empty:
        return res
    cls_map = {t: asset_class(cfg, t) for t in panel["ticker"].unique()}
    horizon = cfg.horizon_days
    model_type, _ = resolve_model_type(cfg, panel, feature_names=FEATURE_COLUMNS)
    dates = np.sort(panel["date"].unique())
    rebal = dates[int(len(dates) * train_frac)::horizon]

    recs = []
    predictor = None
    for i, t in enumerate(rebal):
        train = panel[panel["date"] <= (t - np.timedelta64(horizon, "D"))]
        today = panel[panel["date"] == t]
        if len(train) < 50 or today.empty or train["target"].nunique() < 2:
            continue
        if predictor is None or i % 3 == 0:      # alle 3 Termine neu trainieren (schneller)
            predictor = Predictor(FEATURE_COLUMNS, model_type=model_type,
                                  random_state=int(cfg.model.get("random_state", 42)))
            predictor.estimator.fit(train[FEATURE_COLUMNS].values,
                                    train["target"].astype(int).values)
            predictor.is_fitted = True
        proba = predictor.predict_proba(today)
        for (_, r), p in zip(today.iterrows(), proba):
            recs.append({"proba": float(p), "target": float(r["target"]),
                         "rsi": r.get("rsi_14", 50.0), "sent": r.get("sent_mean", 0.0),
                         "regime": r.get("mkt_trend", 0.0), "vol": r.get("vol_20d", 0.02),
                         "mom": r.get("ret_5d", 0.0), "cls": cls_map.get(r["ticker"], "")})
    if len(recs) < 50:
        return res
    df = pd.DataFrame(recs)
    res.n = len(df)
    res.base_rate = float(df["target"].mean())

    seg = []
    # nur Fälle, in denen das Modell KAUFEN würde (proba hoch) – dort zählt's
    df["buy"] = df["proba"] >= 0.55
    b = df[df["buy"]]
    seg += _segment(b, "Kaufsignal × RSI", {
        "RSI<30 (überverkauft)": (b["rsi"] < 30, "rsi_low"),
        "RSI 30–70": ((b["rsi"] >= 30) & (b["rsi"] <= 70), "rsi_mid"),
        "RSI>70 (überkauft)": (b["rsi"] > 70, "rsi_high"),
    })
    seg += _segment(b, "Kaufsignal × Sentiment", {
        "News negativ": (b["sent"] < -0.1, "sent_neg"),
        "News neutral": ((b["sent"] >= -0.1) & (b["sent"] <= 0.1), "sent_neu"),
        "News positiv": (b["sent"] > 0.1, "sent_pos"),
    })
    seg += _segment(b, "Kaufsignal × Marktlage", {
        "Abschwung (Markt<SMA50)": (b["regime"] < 0, "regime_down"),
        "Aufschwung (Markt>SMA50)": (b["regime"] >= 0, "regime_up"),
    })
    seg += _segment(b, "Kaufsignal × Momentum", {
        "Momentum fallend (5T<0)": (b["mom"] < 0, "mom_neg"),
        "Momentum steigend (5T≥0)": (b["mom"] >= 0, "mom_pos"),
    })
    seg += _segment(b, "Kaufsignal × Schwankung", {
        "hohe Schwankung": (b["vol"] > _VOL_CUT, "vol_high"),
        "ruhig": (b["vol"] <= _VOL_CUT, "vol_low"),
    })
    # Anlageklasse (dynamisch, je nach vorhandenen Klassen)
    cls_labels = {c: (b["cls"] == c, f"class_{c}") for c in b["cls"].unique() if c}
    if cls_labels:
        seg += _segment(b, "Kaufsignal × Anlageklasse", cls_labels)

    res.segments = sorted(seg, key=lambda s: s["hit"])   # schlechteste zuerst
    return res


# --------------------------------------------------------------------------- #
# Selbstkorrektur: Schwachstellen als „Lektionen" speichern und täglich anwenden
# --------------------------------------------------------------------------- #
def _lessons_path(cfg: Config) -> Path:
    return Path(cfg.store_dir) / _LESSONS_FILE


def save_lessons(cfg: Config, w: WeakSpots) -> int:
    """Speichert die als schwach erkannten Bedingungen (gap < -3 %) als Lektionen.

    Diese werden bei der täglichen Empfehlung gelesen: Fällt ein Kaufkandidat in
    eine solche Bedingung, wird die KI vorsichtiger – sie *lernt* aus ihren
    Fehlern, statt sie zu wiederholen. Gibt die Anzahl gespeicherter Lektionen
    zurück.
    """
    lessons = [
        {"kind": s["kind"], "group": s["group"], "dim": s["dim"],
         "hit": round(s["hit"], 4), "gap": round(s["gap"], 4)}
        for s in w.segments
        if s.get("kind") and s["gap"] < _FLAG
    ]
    p = _lessons_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    json.dump({"base_rate": round(w.base_rate, 4) if w.base_rate == w.base_rate else None,
               "n": w.n, "lessons": lessons},
              open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return len(lessons)


def load_lessons(cfg: Config) -> list:
    """Lädt die gespeicherten Schwachstellen-Lektionen (leer, falls keine)."""
    p = _lessons_path(cfg)
    if not p.exists():
        return []
    try:
        return json.load(open(p, encoding="utf-8")).get("lessons", [])
    except Exception:
        return []


def caution_for(lessons: list, feats: dict) -> list[str]:
    """Liefert Klartext-Warnungen für die Bedingungen, in denen die KI hier
    historisch schwach war (für transparente Begründung der Empfehlung).

    ``feats`` ist ein Dict mit rsi/sent/regime/vol/mom/cls des Kandidaten.
    """
    out = []
    for le in lessons:
        if _matches(le.get("kind", ""), feats):
            out.append(f"{le['group']}: hier traf die KI zuletzt nur "
                       f"{le['hit']:.0%} ({le['gap']:+.0%} vs. Schnitt)")
    return out


def render_weakspots(w: WeakSpots) -> str:
    if w.n < 50:
        return ("Schwachstellen-Analyse: noch zu wenig Daten "
                "(Universum/Historie prüfen).")
    lines = [f"Schwachstellen-Analyse ({w.n} Prognosen, "
             f"Basisrate {w.base_rate:.0%})",
             "Trefferquote der Kaufsignale je Bedingung (niedrig = Schwachstelle):"]
    for s in w.segments:
        flag = "" if s["gap"] < -0.03 else ("" if s["gap"] > 0.03 else "  ")
        lines.append(f"  {flag} {s['dim']:24s} {s['group']:26s} "
                     f"{s['hit']:.0%} (n={s['count']}, {s['gap']:+.0%} vs Basis)")
    worst = w.segments[0] if w.segments else None
    if worst and worst["gap"] < -0.03:
        lines.append(f"\n→ Größte Schwäche: „{worst['group']}\" – hier liegt die KI "
                     f"{abs(worst['gap']):.0%} unter der Basisrate.")
    lines.append("\nKeine Anlageberatung.")
    return "\n".join(lines)
