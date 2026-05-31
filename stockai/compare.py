"""Vergleich verschiedener Bar-Intervalle (z.B. Tagesdaten vs. Intraday).

Baut für jedes Intervall denselben Trainingsdatensatz und bewertet ihn ehrlich
per zeitlicher Kreuzvalidierung. So lässt sich datenbasiert entscheiden, ob
Intraday-Daten beim eigenen Setup tatsächlich präziser sind – statt es nur
anzunehmen.
"""
from __future__ import annotations

import dataclasses


def compare_intervals(cfg, intervals: list[str]) -> list[dict]:
    """Liefert je Intervall: Anzahl Samples, CV-AUC und CV-Accuracy."""
    from stockai import pipeline
    from stockai.model.predictor import Predictor

    out: list[dict] = []
    for iv in intervals:
        c = dataclasses.replace(cfg, history_interval=iv)
        try:
            data = pipeline._combined_training_data(c)
        except Exception as exc:
            out.append({"interval": iv, "n": 0, "auc": float("nan"),
                        "acc": float("nan"), "error": str(exc)})
            continue
        if data.empty or len(data) < 60:
            out.append({"interval": iv, "n": int(len(data)), "auc": float("nan"),
                        "acc": float("nan")})
            continue
        mt, _ = pipeline.resolve_model_type(c, data)
        cv = Predictor(pipeline.FEATURE_COLUMNS, model_type=mt,
                       random_state=int(cfg.model.get("random_state", 42))).cross_validate(data)
        out.append({
            "interval": iv,
            "n": int(len(data)),
            "auc": cv.get("cv_roc_auc_mean", float("nan")),
            "acc": cv.get("cv_accuracy_mean", float("nan")),
        })
    return out
