"""Ranking-„Gehirn" (Phase 2): kombiniert mehrere Signale zu einer Trefferwertung.

Statt nur semantischer Ähnlichkeit fließen mehrere Belege ein:
- **semantic**  – Vektor-Ähnlichkeit Anfrage↔Werk
- **keyword**   – Stichwort-Überlappung (Titel)
- **citations** – Wirkung (log-normierte Zitationszahl)
- **recency**   – Aktualität (Publikationsjahr)

Die Gewichte starten mit sinnvollen Defaults (Cold Start) und werden vom
**lernenden Gehirn** (``brain.py``) aus echten Klicks neu justiert. Transparente,
nachvollziehbare Aggregation – kein Black-Box-Score.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

FEATURES = ["semantic", "keyword", "citations", "recency"]

# Cold-Start-Gewichte (bevor das Gehirn aus Klicks gelernt hat)
DEFAULT_WEIGHTS = {"semantic": 1.0, "keyword": 0.30, "citations": 0.15, "recency": 0.10}


def make_features(sim: float, keyword: float, cited_by_count: int,
                  year: int | None, now_year: int = 2026) -> dict:
    """Normalisiert die Roh-Signale auf vergleichbare Skalen (~0..1)."""
    cites = min(1.0, math.log1p(max(0, cited_by_count)) / 12.0)   # log1p(160k)≈12
    if year:
        recency = min(1.0, max(0.0, (year - 1990) / 40.0))
    else:
        recency = 0.4
    return {"semantic": float(sim), "keyword": float(keyword),
            "citations": cites, "recency": recency}


def score(feats: dict, weights: dict) -> float:
    return sum(weights.get(k, 0.0) * feats.get(k, 0.0) for k in FEATURES)


def weights_path(data_dir: str) -> Path:
    return Path(data_dir) / "index" / "weights.json"


def load_weights(data_dir: str) -> dict:
    p = weights_path(data_dir)
    if p.exists():
        try:
            w = json.load(open(p, encoding="utf-8"))
            return {k: float(w.get(k, DEFAULT_WEIGHTS[k])) for k in FEATURES}
        except Exception:
            pass
    return dict(DEFAULT_WEIGHTS)


def save_weights(data_dir: str, weights: dict) -> None:
    p = weights_path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    json.dump(weights, open(p, "w", encoding="utf-8"), indent=2)
