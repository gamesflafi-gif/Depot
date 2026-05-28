"""Das lernende Vorhersagemodell.

Sagt die Wahrscheinlichkeit voraus, dass eine Aktie über den konfigurierten
Horizont profitabel wird (Klassifikation: Rendite > Schwelle).

Unterstützte Modelltypen:
    * ``gradient_boosting`` – kräftiges Baummodell, volles Re-Training
    * ``logistic``          – lineares Baseline-Modell
    * ``sgd_online``        – echtes inkrementelles Lernen via ``partial_fit``

"Lernende Basis": Das Modell wird bei jedem Lauf auf dem stetig wachsenden
Feature-Store neu trainiert bzw. (bei sgd_online) inkrementell weiter trainiert.
Die Bewertung erfolgt out-of-sample, sodass Fortschritt messbar ist.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


@dataclass
class TrainResult:
    metrics: dict[str, float]
    n_train: int
    n_test: int
    feature_importance: dict[str, float] = field(default_factory=dict)


def _build_estimator(model_type: str, random_state: int):
    if model_type == "gradient_boosting":
        return GradientBoostingClassifier(random_state=random_state)
    if model_type == "logistic":
        return Pipeline(
            [
                ("scaler", StandardScaler()),
                ("clf", LogisticRegression(max_iter=1000)),
            ]
        )
    if model_type == "sgd_online":
        return Pipeline(
            [
                ("scaler", StandardScaler()),
                (
                    "clf",
                    SGDClassifier(
                        loss="log_loss",
                        random_state=random_state,
                        warm_start=True,
                    ),
                ),
            ]
        )
    raise ValueError(f"Unbekannter Modelltyp: {model_type}")


class Predictor:
    """Kapselt das ML-Modell inkl. Training, Bewertung und Vorhersage."""

    def __init__(
        self,
        feature_names: list[str],
        model_type: str = "gradient_boosting",
        random_state: int = 42,
    ) -> None:
        self.feature_names = feature_names
        self.model_type = model_type
        self.random_state = random_state
        self.estimator: Any = _build_estimator(model_type, random_state)
        self.is_fitted = False

    # ------------------------------------------------------------------ #
    def train(
        self,
        df: pd.DataFrame,
        target_col: str = "target",
        test_size: float = 0.2,
    ) -> TrainResult:
        """Trainiert das Modell und bewertet es out-of-sample.

        Bei Zeitreihen wird zeitlich gesplittet (kein Shuffle), damit die
        Bewertung nicht aus der Zukunft "spickt".
        """
        data = df.dropna(subset=self.feature_names + [target_col]).copy()
        X = data[self.feature_names].values
        y = data[target_col].astype(int).values

        if len(data) < 30 or len(np.unique(y)) < 2:
            raise ValueError(
                "Zu wenige bzw. einseitige Daten zum Trainieren "
                f"(n={len(data)}, Klassen={np.unique(y).tolist()})."
            )

        # Zeitlicher Split: ältere Daten -> Training, jüngste -> Test
        split = int(len(data) * (1 - test_size))
        X_train, X_test = X[:split], X[split:]
        y_train, y_test = y[:split], y[split:]

        if len(np.unique(y_train)) < 2:
            # Fallback: zufälliger, stratifizierter Split
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=test_size, random_state=self.random_state,
                stratify=y,
            )

        self.estimator.fit(X_train, y_train)
        self.is_fitted = True

        metrics = self._evaluate(X_test, y_test)
        return TrainResult(
            metrics=metrics,
            n_train=len(X_train),
            n_test=len(X_test),
            feature_importance=self._feature_importance(),
        )

    def partial_train(self, df: pd.DataFrame, target_col: str = "target") -> None:
        """Inkrementelles Lernen (nur für ``sgd_online``).

        Trainiert das bestehende Modell mit neuen Daten weiter, ohne von vorne
        zu beginnen – das ist "Lernen im Betrieb".
        """
        if self.model_type != "sgd_online":
            raise ValueError("partial_train ist nur für model_type 'sgd_online' verfügbar.")
        data = df.dropna(subset=self.feature_names + [target_col]).copy()
        X = data[self.feature_names].values
        y = data[target_col].astype(int).values
        clf = self.estimator.named_steps["clf"]
        scaler = self.estimator.named_steps["scaler"]
        X = scaler.fit_transform(X) if not self.is_fitted else scaler.transform(X)
        clf.partial_fit(X, y, classes=np.array([0, 1]))
        self.is_fitted = True

    # ------------------------------------------------------------------ #
    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        """Wahrscheinlichkeit der Klasse 'profitabel' (1)."""
        if not self.is_fitted:
            raise RuntimeError("Modell ist noch nicht trainiert.")
        X = df[self.feature_names].values
        proba = self.estimator.predict_proba(X)
        return proba[:, 1]

    # ------------------------------------------------------------------ #
    def _evaluate(self, X_test: np.ndarray, y_test: np.ndarray) -> dict[str, float]:
        preds = self.estimator.predict(X_test)
        metrics = {
            "accuracy": float(accuracy_score(y_test, preds)),
            "precision": float(precision_score(y_test, preds, zero_division=0)),
            "recall": float(recall_score(y_test, preds, zero_division=0)),
            "f1": float(f1_score(y_test, preds, zero_division=0)),
        }
        try:
            proba = self.estimator.predict_proba(X_test)[:, 1]
            if len(np.unique(y_test)) > 1:
                metrics["roc_auc"] = float(roc_auc_score(y_test, proba))
        except Exception:
            pass
        return metrics

    def _feature_importance(self) -> dict[str, float]:
        est = self.estimator
        if hasattr(est, "feature_importances_"):
            vals = est.feature_importances_
        elif hasattr(est, "named_steps") and hasattr(
            est.named_steps.get("clf"), "coef_"
        ):
            vals = np.abs(est.named_steps["clf"].coef_[0])
        elif hasattr(est, "coef_"):
            vals = np.abs(est.coef_[0])
        else:
            return {}
        total = float(np.sum(vals)) or 1.0
        return {
            name: float(v) / total
            for name, v in sorted(
                zip(self.feature_names, vals), key=lambda kv: kv[1], reverse=True
            )
        }
