"""Hyperparameter-Tuning per zeitlicher Kreuzvalidierung.

Sucht für einen Modelltyp die besten Hyperparameter (GridSearch mit
``TimeSeriesSplit`` und ROC-AUC). Bewusst kleine Gitter, damit die Suche in
vertretbarer Zeit läuft. Das Ergebnis kann persistiert und beim Training
automatisch angewandt werden.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.model_selection import GridSearchCV, TimeSeriesSplit

from stockai.model.predictor import _build_estimator

# Kleine, sinnvolle Suchräume je Modelltyp (Pipeline-Schritte mit ``clf__``).
PARAM_GRIDS: dict[str, dict] = {
    "hist_gradient_boosting": {
        "learning_rate": [0.03, 0.06, 0.1],
        "max_iter": [200, 400],
        "max_leaf_nodes": [15, 31],
    },
    "gradient_boosting": {
        "learning_rate": [0.03, 0.1],
        "n_estimators": [100, 200],
        "max_depth": [2, 3],
    },
    "random_forest": {
        "n_estimators": [200, 400],
        "max_depth": [6, 10],
        "min_samples_leaf": [10, 30],
    },
    "logistic": {
        "clf__C": [0.1, 1.0, 10.0],
    },
}


@dataclass
class TuningResult:
    model_type: str
    best_params: dict
    best_score: float
    n_candidates: int


def tune_model(
    df: pd.DataFrame,
    feature_names: list[str],
    model_type: str,
    target_col: str = "target",
    random_state: int = 42,
    n_splits: int = 4,
) -> TuningResult:
    """Findet die besten Hyperparameter für ``model_type`` (oder leeres Ergebnis)."""
    grid = PARAM_GRIDS.get(model_type)
    if not grid:
        return TuningResult(model_type, {}, float("nan"), 0)

    data = df.dropna(subset=feature_names + [target_col]).copy()
    if "date" in data.columns:
        data = data.sort_values("date")
    X = data[feature_names].values
    y = data[target_col].astype(int).values
    if len(data) < (n_splits + 1) * 15 or len(np.unique(y)) < 2:
        return TuningResult(model_type, {}, float("nan"), 0)

    search = GridSearchCV(
        _build_estimator(model_type, random_state),
        grid,
        scoring="roc_auc",
        cv=TimeSeriesSplit(n_splits=n_splits),
        n_jobs=-1,
    )
    search.fit(X, y)
    n = int(np.prod([len(v) for v in grid.values()]))
    return TuningResult(
        model_type=model_type,
        best_params=dict(search.best_params_),
        best_score=float(search.best_score_),
        n_candidates=n,
    )
