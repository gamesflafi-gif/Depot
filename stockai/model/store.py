"""Persistenz: Feature-Store, Modellspeicher und Lernhistorie.

Der Feature-Store sammelt über die Zeit Trainingsdaten an. Mit jedem Lauf
wächst die Datenbasis, das Modell wird neu trainiert und seine Out-of-Sample-
Güte in einer Lernhistorie protokolliert. So lässt sich nachvollziehen, dass
die KI mit mehr Erfahrung präziser wird.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd

from stockai.model.predictor import Predictor

_FEATURE_STORE_FILE = "feature_store.csv"
_MODEL_FILE = "model.joblib"
_HISTORY_FILE = "learning_history.json"


# --------------------------------------------------------------------------- #
# Feature-Store: wachsende Trainingsdatenbasis
# --------------------------------------------------------------------------- #
class FeatureStore:
    """Speichert über die Zeit gesammelte Feature-/Label-Zeilen als CSV."""

    def __init__(self, store_dir: Path) -> None:
        self.path = Path(store_dir) / _FEATURE_STORE_FILE

    def load(self) -> pd.DataFrame:
        if self.path.exists():
            return pd.read_csv(self.path)
        return pd.DataFrame()

    def update(self, new_rows: pd.DataFrame, key_cols: list[str]) -> pd.DataFrame:
        """Fügt neue Zeilen hinzu und dedupliziert nach ``key_cols``.

        Returns:
            Den vollständigen, aktualisierten Datenbestand.
        """
        existing = self.load()
        combined = pd.concat([existing, new_rows], ignore_index=True)
        combined = combined.drop_duplicates(subset=key_cols, keep="last")
        combined = combined.sort_values(key_cols).reset_index(drop=True)
        combined.to_csv(self.path, index=False)
        return combined


# --------------------------------------------------------------------------- #
# Modellspeicher + Lernhistorie
# --------------------------------------------------------------------------- #
class ModelStore:
    def __init__(self, model_dir: Path) -> None:
        self.model_dir = Path(model_dir)
        self.model_path = self.model_dir / _MODEL_FILE
        self.history_path = self.model_dir / _HISTORY_FILE

    def save_model(self, predictor: Predictor) -> None:
        joblib.dump(predictor, self.model_path)

    def load_model(self) -> Predictor | None:
        if self.model_path.exists():
            return joblib.load(self.model_path)
        return None

    # --- Lernhistorie ---------------------------------------------------- #
    def load_history(self) -> list[dict]:
        if self.history_path.exists():
            with open(self.history_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        return []

    def append_history(self, entry: dict) -> list[dict]:
        history = self.load_history()
        entry = {"timestamp": datetime.now(timezone.utc).isoformat(), **entry}
        history.append(entry)
        with open(self.history_path, "w", encoding="utf-8") as fh:
            json.dump(history, fh, indent=2)
        return history

    def best_metric(self, metric: str = "roc_auc") -> float | None:
        vals = [
            h["metrics"][metric]
            for h in self.load_history()
            if metric in h.get("metrics", {})
        ]
        return max(vals) if vals else None
