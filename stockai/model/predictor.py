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
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import (
    GradientBoostingClassifier,
    HistGradientBoostingClassifier,
    RandomForestClassifier,
    VotingClassifier,
)
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import TimeSeriesSplit, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

# Modelltypen, die bei ``type: auto`` gegeneinander antreten.
AUTO_CANDIDATES = ["hist_gradient_boosting", "gradient_boosting", "random_forest", "logistic"]


@dataclass
class TrainResult:
    metrics: dict[str, float]
    n_train: int
    n_test: int
    feature_importance: dict[str, float] = field(default_factory=dict)
    cv_metrics: dict[str, float] = field(default_factory=dict)


def _build_estimator(model_type: str, random_state: int, params: dict | None = None):
    est = _build_estimator_base(model_type, random_state)
    if params:
        try:
            est.set_params(**params)
        except ValueError:
            pass  # inkompatible Parameter ignorieren statt zu scheitern
    return est


def _build_estimator_base(model_type: str, random_state: int):
    if model_type == "gradient_boosting":
        return GradientBoostingClassifier(random_state=random_state)
    if model_type == "hist_gradient_boosting":
        return HistGradientBoostingClassifier(
            random_state=random_state, learning_rate=0.06, max_iter=300,
            l2_regularization=1.0,
        )
    if model_type == "random_forest":
        return RandomForestClassifier(
            n_estimators=300, max_depth=8, min_samples_leaf=20,
            random_state=random_state, n_jobs=-1,
        )
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
    if model_type == "ensemble":
        return VotingClassifier(
            estimators=[
                ("hgb", HistGradientBoostingClassifier(
                    random_state=random_state, learning_rate=0.06, max_iter=300)),
                ("rf", RandomForestClassifier(
                    n_estimators=300, max_depth=8, min_samples_leaf=20,
                    random_state=random_state, n_jobs=-1)),
                ("lr", Pipeline([("scaler", StandardScaler()),
                                 ("clf", LogisticRegression(max_iter=1000))])),
            ],
            voting="soft",
        )
    raise ValueError(f"Unbekannter Modelltyp: {model_type}")


class Predictor:
    """Kapselt das ML-Modell inkl. Training, Bewertung und Vorhersage."""

    def __init__(
        self,
        feature_names: list[str],
        model_type: str = "gradient_boosting",
        random_state: int = 42,
        calibrate: bool = False,
        params: dict | None = None,
    ) -> None:
        self.feature_names = feature_names
        self.model_type = model_type
        self.random_state = random_state
        self.params = params or {}
        self.calibrate = calibrate and model_type != "sgd_online"
        self.base_estimator: Any = _build_estimator(model_type, random_state, self.params)
        # Kalibrierte Wahrscheinlichkeiten (verlässlichere P(Profit)) via
        # isotonischer Regression auf zeitlich sauberen CV-Folds.
        if self.calibrate:
            self.estimator: Any = CalibratedClassifierCV(
                self.base_estimator, method="isotonic", cv=TimeSeriesSplit(n_splits=3)
            )
        else:
            self.estimator = self.base_estimator
        self.is_fitted = False

    # ------------------------------------------------------------------ #
    def cross_validate(
        self, df: pd.DataFrame, target_col: str = "target", n_splits: int = 5
    ) -> dict[str, float]:
        """Ehrliche Präzisionsschätzung per zeitlicher Kreuzvalidierung.

        Trainiert auf wachsenden Vergangenheitsfenstern und bewertet jeweils auf
        dem darauffolgenden Block (``TimeSeriesSplit``). Liefert Mittelwert und
        Streuung der Out-of-Sample-Metriken – kein Blick in die Zukunft.
        """
        data = df.dropna(subset=self.feature_names + [target_col]).copy()
        if "date" in data.columns:
            data = data.sort_values("date")
        X = data[self.feature_names].values
        y = data[target_col].astype(int).values
        if len(data) < (n_splits + 1) * 10 or len(np.unique(y)) < 2:
            return {}

        accs, aucs, f1s = [], [], []
        for tr_idx, te_idx in TimeSeriesSplit(n_splits=n_splits).split(X):
            if len(np.unique(y[tr_idx])) < 2:
                continue
            est = _build_estimator(self.model_type, self.random_state)
            est.fit(X[tr_idx], y[tr_idx])
            preds = est.predict(X[te_idx])
            accs.append(accuracy_score(y[te_idx], preds))
            f1s.append(f1_score(y[te_idx], preds, zero_division=0))
            try:
                proba = est.predict_proba(X[te_idx])[:, 1]
                if len(np.unique(y[te_idx])) > 1:
                    aucs.append(roc_auc_score(y[te_idx], proba))
            except Exception:
                pass
        if not accs:
            return {}
        return {
            "cv_accuracy_mean": float(np.mean(accs)),
            "cv_accuracy_std": float(np.std(accs)),
            "cv_roc_auc_mean": float(np.mean(aucs)) if aucs else float("nan"),
            "cv_roc_auc_std": float(np.std(aucs)) if aucs else float("nan"),
            "cv_f1_mean": float(np.mean(f1s)),
            "cv_folds": len(accs),
        }

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

    def _importance_from(self, est) -> np.ndarray | None:
        """Versucht, Feature-Wichtigkeiten aus einem Schätzer zu lesen."""
        if hasattr(est, "feature_importances_"):
            return np.asarray(est.feature_importances_, dtype=float)
        if hasattr(est, "named_steps") and hasattr(est.named_steps.get("clf"), "coef_"):
            return np.abs(est.named_steps["clf"].coef_[0])
        if hasattr(est, "coef_"):
            return np.abs(est.coef_[0])
        return None

    def _feature_importance(self) -> dict[str, float]:
        est = self.estimator
        vals = self._importance_from(est)
        # Kalibriertes Modell: an die zugrunde liegenden Schätzer herangehen
        if vals is None and hasattr(est, "calibrated_classifiers_"):
            per = []
            for cc in est.calibrated_classifiers_:
                base = getattr(cc, "estimator", None)
                iv = self._importance_from(base) if base is not None else None
                if iv is not None:
                    per.append(iv)
            if per:
                vals = np.mean(per, axis=0)
        # Voting-Ensemble: Mittel über die Teil-Schätzer
        if vals is None and hasattr(est, "estimators_"):
            per = [self._importance_from(e) for e in est.estimators_]
            per = [p for p in per if p is not None]
            if per:
                vals = np.mean(per, axis=0)
        if vals is None or len(vals) != len(self.feature_names):
            return {}
        total = float(np.sum(vals)) or 1.0
        return {
            name: float(v) / total
            for name, v in sorted(
                zip(self.feature_names, vals), key=lambda kv: kv[1], reverse=True
            )
        }
