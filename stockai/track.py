"""Live-Track-Record: echte Prognose vs. real eingetretenes Ergebnis.

Im Gegensatz zum Backtest (historische Simulation) nutzt dies die **tatsächlich
im Betrieb gesammelten** Snapshots: Beim täglichen Lauf wird die Modell-Prognose
(``pred_proba``) gespeichert; sobald der Horizont verstrichen ist, füllt das
Labeling das reale Ergebnis (``target``). Hier werten wir beides aus – die
ehrlichste Messung, ob die KI **live** trifft. Wächst mit der Zeit.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from stockai.config import Config
from stockai.model.store import FeatureStore


@dataclass
class TrackRecord:
    n_labeled: int = 0          # ausgewertete Live-Prognosen
    n_pending: int = 0          # noch nicht gelabelte Snapshots
    base_rate: float = float("nan")
    accuracy: float = float("nan")
    auc: float = float("nan")
    edge: float = float("nan")  # Trefferquote der P>=0.55-Auswahl minus Basisrate
    calibration: list = field(default_factory=list)
    since: str = ""
    until: str = ""
    scope: str = ""             # leer = gesamt, sonst z.B. "deine Depot-Werte"


def build_track_record(cfg: Config, prob_threshold: float = 0.55,
                       tickers: list[str] | None = None,
                       scope: str = "") -> TrackRecord:
    df = FeatureStore(cfg.store_dir).load()
    tr = TrackRecord(scope=scope)
    if df.empty or "pred_proba" not in df.columns or "target" not in df.columns:
        return tr
    if tickers and "ticker" in df.columns:
        df = df[df["ticker"].isin([t.upper() for t in tickers])]
        if df.empty:
            return tr
    tr.n_pending = int(df["target"].isna().sum())
    d = df.dropna(subset=["pred_proba", "target"])
    tr.n_labeled = int(len(d))
    if tr.n_labeled < 5:
        return tr
    if "date" in d.columns:
        tr.since, tr.until = str(d["date"].min()), str(d["date"].max())

    proba = d["pred_proba"].astype(float).values
    y = d["target"].astype(int).values
    tr.base_rate = float(np.mean(y))
    tr.accuracy = float(np.mean((proba >= 0.5).astype(int) == y))
    if len(np.unique(y)) > 1:
        from sklearn.metrics import roc_auc_score
        tr.auc = float(roc_auc_score(y, proba))
    sel = proba >= prob_threshold
    if sel.sum() > 0:
        tr.edge = float(np.mean(y[sel]) - tr.base_rate)

    # Kalibrierung: Wahrscheinlichkeits-Bins vs. reale Trefferquote
    bins = [0.0, 0.4, 0.5, 0.6, 0.7, 1.01]
    dd = pd.DataFrame({"p": proba, "y": y})
    dd["bin"] = pd.cut(dd["p"], bins=bins, right=False)
    for b, grp in dd.groupby("bin", observed=True):
        tr.calibration.append({
            "bin": f"{b.left:.0%}–{b.right:.0%}", "count": int(len(grp)),
            "predicted": float(grp["p"].mean()), "actual": float(grp["y"].mean()),
        })
    return tr


def render_track_record(tr: TrackRecord) -> str:
    title = "📒 Live-Track-Record (echte Prognosen vs. Ergebnis)"
    if tr.scope:
        title = f"📒 Track-Record · {tr.scope} (echte Prognosen vs. Ergebnis)"
    lines = [title]
    if tr.n_labeled < 5:
        extra = f" für {tr.scope}" if tr.scope else ""
        lines.append(f"\nNoch zu wenig gesammelt{extra}: {tr.n_labeled} ausgewertet, "
                     f"{tr.n_pending} laufen noch.\nKommt mit der Zeit – einfach "
                     "weiterlaufen lassen.")
        return "\n".join(lines)
    lines.append(f"Zeitraum: {tr.since} … {tr.until}")
    lines.append(f"Ausgewertet: {tr.n_labeled} Prognosen ({tr.n_pending} laufen noch)")
    lines.append(f"Basisrate (profitabel): {tr.base_rate:.1%}")
    lines.append(f"Accuracy: {tr.accuracy:.1%}" +
                 (f" | AUC: {tr.auc:.3f}" if tr.auc == tr.auc else ""))
    if tr.edge == tr.edge:
        lines.append(f"Mehrwert (P≥55% vs. Basis): {tr.edge:+.1%}")
    if tr.calibration:
        lines.append("\nKalibrierung (vorhergesagt → tatsächlich):")
        for c in tr.calibration:
            lines.append(f"  {c['bin']}: {c['predicted']:.0%} → {c['actual']:.0%} "
                         f"(n={c['count']})")
    lines.append("\n_Keine Anlageberatung._")
    return "\n".join(lines)
