"""Recommendation-Scorecard – die KI bewertet ihre eigene Treffsicherheit.

Per Walk-Forward über die Historie wird zu jedem Termin eine Empfehlung erzeugt
(genau wie im Live-Betrieb: Modell auf Vergangenheit trainiert → Empfehlung) und
anschließend gegen die real eingetretene Folge-Rendite bewertet. Ausgewertet
werden:

    * Trefferquote je Aktion (BOOM/KAUFEN/HALTEN/VERKAUFEN/MEIDEN)
    * Durchschnittliche Folge-Rendite je Aktion
    * Kalibrierung: vorhergesagte P(Profit) vs. tatsächliche Trefferquote

So wird transparent und ehrlich, *wie gut* die Empfehlungen wirklich sind.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from stockai.advisor import recommend
from stockai.config import Config
from stockai.model.predictor import Predictor


@dataclass
class Scorecard:
    n_recommendations: int
    by_action: dict[str, dict]          # Aktion -> {count, hit_rate, avg_return}
    calibration: list[dict] = field(default_factory=list)  # Bins: pred vs. real
    overall_hit_rate: float = 0.0
    buy_avg_return: float = float("nan")
    sell_avg_return: float = float("nan")


_BUY = {"BOOM", "KAUFEN"}
_SELL = {"VERKAUFEN", "MEIDEN"}


def evaluate_recommendations(
    cfg: Config, train_frac: float = 0.4, prob_threshold: float = 0.55
) -> Scorecard:
    """Erzeugt und bewertet historische Empfehlungen per Walk-Forward."""
    from stockai.strategy import _build_panel
    from stockai.pipeline import FEATURE_COLUMNS, resolve_model_type

    panel = _build_panel(cfg)
    if panel.empty:
        raise RuntimeError("Keine Daten für die Scorecard verfügbar.")

    horizon = cfg.horizon_days
    model_type, _ = resolve_model_type(cfg, panel, feature_names=FEATURE_COLUMNS)
    all_dates = np.sort(panel["date"].unique())
    start_idx = int(len(all_dates) * train_frac)
    rebal_dates = all_dates[start_idx::horizon]

    recs: list[dict] = []
    for t in rebal_dates:
        train = panel[panel["date"] <= (t - np.timedelta64(horizon, "D"))]
        today = panel[panel["date"] == t]
        if len(train) < 50 or today.empty or train["target"].nunique() < 2:
            continue
        predictor = Predictor(
            feature_names=FEATURE_COLUMNS, model_type=model_type,
            random_state=int(cfg.model.get("random_state", 42)),
        )
        predictor.estimator.fit(
            train[FEATURE_COLUMNS].values, train["target"].astype(int).values
        )
        predictor.is_fitted = True
        proba = predictor.predict_proba(today)

        for (_, row), p in zip(today.iterrows(), proba):
            rec = recommend(
                profit_probability=float(p),
                rsi_14=row.get("rsi_14", 50.0),
                momentum_5d=row.get("ret_5d", 0.0),
                price_vs_high_20=row.get("price_vs_high_20", 1.0),
                macd_hist=row.get("macd_hist", 0.0),
                sentiment_mean=row.get("sent_mean", 0.0),
            )
            fwd = float(row["fwd_ret"])
            recs.append({"action": rec.action, "proba": float(p), "fwd_ret": fwd})

    if not recs:
        raise RuntimeError("Zu wenige Empfehlungen für eine Auswertung.")

    df = pd.DataFrame(recs)

    # Trefferdefinition: Kauf -> Rendite > Schwelle; Verkauf -> Rendite <= 0
    def _hit(r) -> float:
        if r["action"] in _BUY:
            return float(r["fwd_ret"] > cfg.profit_threshold)
        if r["action"] in _SELL:
            return float(r["fwd_ret"] <= 0.0)
        return float(abs(r["fwd_ret"]) <= 0.01)  # HALTEN: Seitwärts = "richtig"

    df["hit"] = df.apply(_hit, axis=1)

    by_action: dict[str, dict] = {}
    for action, grp in df.groupby("action"):
        by_action[action] = {
            "count": int(len(grp)),
            "hit_rate": float(grp["hit"].mean()),
            "avg_return": float(grp["fwd_ret"].mean()),
        }

    # Kalibrierung: Wahrscheinlichkeits-Bins vs. reale "Profit"-Quote
    bins = [0.0, 0.4, 0.5, 0.6, 0.7, 1.01]
    df["profit"] = (df["fwd_ret"] > cfg.profit_threshold).astype(float)
    df["bin"] = pd.cut(df["proba"], bins=bins, right=False)
    calibration = []
    for b, grp in df.groupby("bin", observed=True):
        calibration.append({
            "bin": f"{b.left:.0%}–{b.right:.0%}",
            "count": int(len(grp)),
            "predicted": float(grp["proba"].mean()),
            "actual": float(grp["profit"].mean()),
        })

    buy = df[df["action"].isin(_BUY)]
    sell = df[df["action"].isin(_SELL)]
    # Gesamt-Trefferquote über handlungsrelevante Signale (HALTEN ausgenommen,
    # da "richtig halten" nicht sinnvoll definierbar ist).
    actionable = df[df["action"] != "HALTEN"]
    overall = float(actionable["hit"].mean()) if not actionable.empty else float("nan")
    return Scorecard(
        n_recommendations=len(df),
        by_action=by_action,
        calibration=calibration,
        overall_hit_rate=overall,
        buy_avg_return=float(buy["fwd_ret"].mean()) if not buy.empty else float("nan"),
        sell_avg_return=float(sell["fwd_ret"].mean()) if not sell.empty else float("nan"),
    )
