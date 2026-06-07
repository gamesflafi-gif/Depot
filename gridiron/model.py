"""Trainierbares Modell: Pass-oder-Lauf-Vorhersage je Situation.

Ein Gradient-Boosting-Klassifikator (HistGradientBoosting, scikit-learn) lernt
aus echten Plays, wie wahrscheinlich in einer Situation ein Pass kommt – inkl.
Team als Merkmal. Liefert dem Coach für eine konkrete Live-Situation:
„P(Pass) = …" plus einen Vorhersehbarkeits-Wert. Läuft komplett auf CPU.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import numpy as np

from gridiron.config import Config
from gridiron.features import NUMERIC_FEATURES, numeric_vector
from gridiron.storage import GridironStore

log = logging.getLogger(__name__)

_MODEL_FILE = "passrun.joblib"
_META_FILE = "passrun_meta.json"


@dataclass
class TrainResult:
    trained: bool = False
    n: int = 0
    accuracy: float = 0.0
    baseline: float = 0.0
    logloss: float = 0.0
    message: str = ""


def _load_matrix(cfg: Config) -> tuple[np.ndarray, np.ndarray, list[str]]:
    cols = ", ".join(NUMERIC_FEATURES)
    with GridironStore(cfg) as store:
        teams = store.teams()
        rows = store.con.execute(
            f"SELECT {cols}, posteam, is_pass FROM plays "
            "WHERE down IS NOT NULL").fetchall()
    tindex = {t: i for i, t in enumerate(teams)}
    nnum = len(NUMERIC_FEATURES)
    X = np.zeros((len(rows), nnum + len(teams)), dtype=np.float32)
    y = np.zeros(len(rows), dtype=np.int8)
    for i, r in enumerate(rows):
        for j in range(nnum):
            v = r[j]
            X[i, j] = float(v) if v is not None else 0.0
        ti = tindex.get(r[nnum])
        if ti is not None:
            X[i, nnum + ti] = 1.0
        y[i] = 1 if r[nnum + 1] else 0
    return X, y, teams


def train(cfg: Config, seed: int = 0) -> TrainResult:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import accuracy_score, log_loss

    X, y, teams = _load_matrix(cfg)
    if len(y) < 50 or len(set(y.tolist())) < 2:
        return TrainResult(False, len(y), message="Zu wenige/eintönige Daten.")

    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(y))
    cut = int(len(y) * 0.8)
    tr, te = idx[:cut], idx[cut:]

    clf = HistGradientBoostingClassifier(max_iter=200, max_depth=6,
                                         learning_rate=0.08, random_state=seed)
    clf.fit(X[tr], y[tr])
    proba = clf.predict_proba(X[te])[:, 1]
    pred = (proba >= 0.5).astype(int)
    acc = float(accuracy_score(y[te], pred))
    base = float(max(y[te].mean(), 1 - y[te].mean()))      # Mehrheitsklasse
    ll = float(log_loss(y[te], proba, labels=[0, 1]))

    import joblib
    cfg.ensure_dirs()
    joblib.dump(clf, cfg.model_dir / _MODEL_FILE)
    json.dump({"teams": teams, "numeric": NUMERIC_FEATURES,
               "accuracy": acc, "baseline": base, "n": int(len(y))},
              open(cfg.model_dir / _META_FILE, "w", encoding="utf-8"))
    log.info("Modell trainiert: n=%d acc=%.3f base=%.3f", len(y), acc, base)
    return TrainResult(True, len(y), acc, base, ll, "OK")


class Predictor:
    """Geladenes Modell für Live-Vorhersagen."""

    def __init__(self, cfg: Config) -> None:
        import joblib
        meta_path = cfg.model_dir / _META_FILE
        if not meta_path.exists():
            raise FileNotFoundError("Kein Modell – bitte erst 'train' ausführen.")
        self.meta = json.load(open(meta_path, encoding="utf-8"))
        self.teams = self.meta["teams"]
        self.tindex = {t: i for i, t in enumerate(self.teams)}
        self.clf = joblib.load(cfg.model_dir / _MODEL_FILE)

    def _vector(self, situation: dict) -> np.ndarray:
        num = numeric_vector(situation)
        vec = np.zeros(len(num) + len(self.teams), dtype=np.float32)
        vec[:len(num)] = num
        ti = self.tindex.get(situation.get("team") or situation.get("posteam"))
        if ti is not None:
            vec[len(num) + ti] = 1.0
        return vec.reshape(1, -1)

    def predict_pass_prob(self, situation: dict) -> float:
        return float(self.clf.predict_proba(self._vector(situation))[0, 1])

    def assess(self, situation: dict) -> dict:
        p = self.predict_pass_prob(situation)
        call = "PASS" if p >= 0.5 else "RUN"
        conf = abs(p - 0.5) * 2                       # 0 (unklar) .. 1 (sicher)
        return {"pass_prob": p, "run_prob": 1 - p, "likely": call,
                "predictability": conf}
