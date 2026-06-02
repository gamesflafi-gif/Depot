"""Schwachstellen-Analyse: wo liegt das Modell am häufigsten daneben?

Per Walk-Forward werden echte Prognosen erzeugt und gegen das reale Ergebnis
gestellt – aufgeschlüsselt nach Bedingungen (Wahrscheinlichkeits-Bereich,
RSI-Zone, News-Sentiment, Marktlage, Anlageklasse). So sieht man, *unter welchen
Umständen* die KI falsch deutet, und kann gezielt nachbessern.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from stockai.config import Config


@dataclass
class WeakSpots:
    n: int = 0
    segments: list = field(default_factory=list)   # {dim, group, count, hit, base, gap}
    base_rate: float = float("nan")


def _segment(df: pd.DataFrame, dim: str, labels: dict) -> list:
    out = []
    base = df["target"].mean()
    for key, mask in labels.items():
        grp = df[mask]
        if len(grp) < 20:
            continue
        hit = float(grp["target"].mean())
        out.append({"dim": dim, "group": key, "count": int(len(grp)),
                    "hit": hit, "base": float(base), "gap": hit - float(base)})
    return out


def analyze_weakspots(cfg: Config, train_frac: float = 0.4) -> WeakSpots:
    from stockai.strategy import _build_panel
    from stockai.pipeline import FEATURE_COLUMNS, resolve_model_type
    from stockai.model.predictor import Predictor

    panel = _build_panel(cfg)
    res = WeakSpots()
    if panel.empty:
        return res
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
                         "regime": r.get("mkt_trend", 0.0)})
    if len(recs) < 50:
        return res
    df = pd.DataFrame(recs)
    res.n = len(df)
    res.base_rate = float(df["target"].mean())

    seg = []
    # nur Fälle, in denen das Modell KAUFEN würde (proba hoch) – dort zählt's
    df["buy"] = df["proba"] >= 0.55
    seg += _segment(df[df["buy"]], "Kaufsignal × RSI", {
        "RSI<30 (überverkauft)": df[df["buy"]]["rsi"] < 30,
        "RSI 30–70": (df[df["buy"]]["rsi"] >= 30) & (df[df["buy"]]["rsi"] <= 70),
        "RSI>70 (überkauft)": df[df["buy"]]["rsi"] > 70,
    })
    seg += _segment(df[df["buy"]], "Kaufsignal × Sentiment", {
        "News negativ": df[df["buy"]]["sent"] < -0.1,
        "News neutral": (df[df["buy"]]["sent"] >= -0.1) & (df[df["buy"]]["sent"] <= 0.1),
        "News positiv": df[df["buy"]]["sent"] > 0.1,
    })
    seg += _segment(df[df["buy"]], "Kaufsignal × Marktlage", {
        "Abschwung (Markt<SMA50)": df[df["buy"]]["regime"] < 0,
        "Aufschwung (Markt>SMA50)": df[df["buy"]]["regime"] >= 0,
    })
    res.segments = sorted(seg, key=lambda s: s["hit"])   # schlechteste zuerst
    return res


def render_weakspots(w: WeakSpots) -> str:
    if w.n < 50:
        return ("🔍 Schwachstellen-Analyse: noch zu wenig Daten "
                "(Universum/Historie prüfen).")
    lines = [f"🔍 Schwachstellen-Analyse ({w.n} Prognosen, "
             f"Basisrate {w.base_rate:.0%})",
             "Trefferquote der Kaufsignale je Bedingung (niedrig = Schwachstelle):"]
    for s in w.segments:
        flag = "⚠️" if s["gap"] < -0.03 else ("✅" if s["gap"] > 0.03 else "  ")
        lines.append(f"  {flag} {s['dim']:24s} {s['group']:26s} "
                     f"{s['hit']:.0%} (n={s['count']}, {s['gap']:+.0%} vs Basis)")
    worst = w.segments[0] if w.segments else None
    if worst and worst["gap"] < -0.03:
        lines.append(f"\n→ Größte Schwäche: „{worst['group']}\" – hier liegt die KI "
                     f"{abs(worst['gap']):.0%} unter der Basisrate.")
    lines.append("\n_Keine Anlageberatung._")
    return "\n".join(lines)
