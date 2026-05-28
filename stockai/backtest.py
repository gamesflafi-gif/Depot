"""Einfacher Walk-Forward-Backtest der gelernten Strategie.

Trainiert auf einem zeitlich frühen Teil der Historie und prüft auf dem
späteren Teil, ob die vom Modell als "profitabel" eingestuften Tage im Mittel
tatsächlich positive Folge-Renditen hatten. So wird messbar, ob die KI einen
echten Mehrwert gegenüber Zufall liefert.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from stockai.config import Config
from stockai.pipeline import FEATURE_COLUMNS, build_history_dataset
from stockai.model.predictor import Predictor


@dataclass
class BacktestResult:
    n_test: int
    accuracy: float
    base_rate: float          # Anteil profitabler Tage insgesamt
    selected_hit_rate: float  # Trefferquote unter den ausgewählten "Kauf"-Signalen
    edge: float               # selected_hit_rate - base_rate (Mehrwert)
    threshold: float


def run_backtest(cfg: Config, prob_threshold: float = 0.55, train_frac: float = 0.7) -> BacktestResult:
    data = build_history_dataset(cfg)
    if data.empty:
        raise RuntimeError("Keine Daten für den Backtest verfügbar.")

    data = data.sort_values(["date"]).reset_index(drop=True)
    split = int(len(data) * train_frac)
    train_df, test_df = data.iloc[:split], data.iloc[split:]

    predictor = Predictor(
        feature_names=FEATURE_COLUMNS,
        model_type=cfg.model.get("type", "gradient_boosting"),
        random_state=int(cfg.model.get("random_state", 42)),
    )
    # Auf dem frühen Teil trainieren (interner Split nur zur Kontrolle)
    predictor.train(train_df, target_col="target", test_size=0.15)

    proba = predictor.predict_proba(test_df)
    y_true = test_df["target"].astype(int).values
    preds = (proba >= 0.5).astype(int)

    selected = proba >= prob_threshold
    selected_hits = (
        float(np.mean(y_true[selected])) if selected.sum() > 0 else float("nan")
    )
    base_rate = float(np.mean(y_true))

    return BacktestResult(
        n_test=len(test_df),
        accuracy=float(np.mean(preds == y_true)),
        base_rate=base_rate,
        selected_hit_rate=selected_hits,
        edge=(selected_hits - base_rate) if selected.sum() > 0 else float("nan"),
        threshold=prob_threshold,
    )
