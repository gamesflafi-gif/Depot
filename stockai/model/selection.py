"""Automatische Modellauswahl per zeitlicher Kreuzvalidierung.

Lässt mehrere Modelltypen auf denselben Daten gegeneinander antreten und wählt
das mit der besten mittleren Out-of-Sample-ROC-AUC. Das erhöht die Präzision,
ohne dass man den Modelltyp von Hand raten muss.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from stockai.model.predictor import AUTO_CANDIDATES, Predictor


@dataclass
class SelectionResult:
    best_type: str
    ranking: list[tuple[str, float]]   # (Modelltyp, mittlere CV-AUC), absteigend
    cv_metrics: dict[str, float]


def select_best_model(
    df: pd.DataFrame,
    feature_names: list[str],
    candidates: list[str] | None = None,
    random_state: int = 42,
    n_splits: int = 5,
) -> SelectionResult:
    """Wählt den Modelltyp mit der besten CV-AUC (Fallback: Accuracy)."""
    candidates = candidates or AUTO_CANDIDATES
    scored: list[tuple[str, float, dict]] = []
    for model_type in candidates:
        probe = Predictor(feature_names, model_type=model_type, random_state=random_state)
        cv = probe.cross_validate(df, n_splits=n_splits)
        if not cv:
            continue
        score = cv.get("cv_roc_auc_mean")
        if score is None or score != score:  # NaN
            score = cv.get("cv_accuracy_mean", 0.0)
        scored.append((model_type, float(score), cv))

    if not scored:
        # Fallback: robustes Standardmodell
        return SelectionResult("hist_gradient_boosting", [], {})

    scored.sort(key=lambda t: t[1], reverse=True)
    best_type, _, best_cv = scored[0]
    return SelectionResult(
        best_type=best_type,
        ranking=[(t, s) for t, s, _ in scored],
        cv_metrics=best_cv,
    )
