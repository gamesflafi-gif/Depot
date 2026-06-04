"""Das lernende Ranking-„Gehirn" (Phase 2).

Lernt aus den protokollierten **Klicks**, welche Signale wirklich relevante
Treffer ausmachen, und justiert die Ranking-Gewichte entsprechend. Methode:
schwach überwachtes Learning-to-Rank – angeklickte (Anfrage, Werk)-Paare sind
positive Beispiele, zufällige Werke negative. Eine logistische Regression über
die Ranking-Features liefert neue, datenbasierte Gewichte.

So wird die Suche mit jeder Nutzung besser – der eigentliche Burggraben. Bevor
genug Klicks gesammelt sind, bleiben die Cold-Start-Gewichte aktiv.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from synapse.config import Config
from synapse.embeddings import _tokenize
from synapse.ranking import DEFAULT_WEIGHTS, FEATURES, make_features, save_weights
from synapse.storage import SynapseStore

log = logging.getLogger(__name__)
_MIN_CLICKS = 15


@dataclass
class BrainResult:
    trained: bool = False
    n_clicks: int = 0
    weights: dict = None
    note: str = ""


def _load_clicks(cfg: Config) -> list[tuple[str, str]]:
    with SynapseStore(cfg) as store:
        rows = store.con.execute(
            "SELECT query, work_id FROM events WHERE event='click' "
            "AND query<>'' AND work_id<>''").fetchall()
    return [(r[0], r[1]) for r in rows]


def train(cfg: Config, prefer: str = "auto") -> BrainResult:
    """Trainiert die Ranking-Gewichte aus Klick-Feedback."""
    clicks = _load_clicks(cfg)
    res = BrainResult(n_clicks=len(clicks), weights=dict(DEFAULT_WEIGHTS))
    if len(clicks) < _MIN_CLICKS:
        res.note = (f"Noch zu wenig Klicks ({len(clicks)}/{_MIN_CLICKS}). "
                    "Cold-Start-Gewichte bleiben aktiv – kommt mit der Nutzung.")
        return res

    from synapse.index import _index_dir
    import json
    d = _index_dir(cfg)
    vecs = np.load(d / "vectors.npy")
    meta = json.load(open(d / "meta.json", encoding="utf-8"))
    from synapse.embeddings import get_embedder
    embedder = get_embedder(prefer=prefer)

    id2idx = {m["id"]: i for i, m in enumerate(meta)}
    tokens = [set(_tokenize(m["title"])) for m in meta]
    rng = np.random.default_rng(42)

    # eindeutige Anfragen einmal einbetten (Effizienz)
    queries = sorted({q for q, _ in clicks})
    qvecs = embedder.embed(queries).astype("float32")
    qvecs /= np.clip(np.linalg.norm(qvecs, axis=1, keepdims=True), 1e-9, None)
    qmap = {q: qvecs[i] for i, q in enumerate(queries)}

    X, y = [], []

    def _feat_row(qv, qtok, idx):
        sim = float(vecs[idx] @ qv)
        kw = (len(qtok & tokens[idx]) / len(qtok)) if qtok else 0.0
        f = make_features(sim, kw, meta[idx]["cited_by_count"], meta[idx]["year"])
        return [f[k] for k in FEATURES]

    for q, wid in clicks:
        if wid not in id2idx or q not in qmap:
            continue
        qv, qtok = qmap[q], set(_tokenize(q))
        X.append(_feat_row(qv, qtok, id2idx[wid])); y.append(1)        # positiv
        for _ in range(4):                                            # negative Stichprobe
            j = int(rng.integers(0, len(meta)))
            if meta[j]["id"] == wid:
                continue
            X.append(_feat_row(qv, qtok, j)); y.append(0)

    if len(set(y)) < 2:
        res.note = "Zu einseitige Daten – Cold-Start bleibt aktiv."
        return res

    from sklearn.linear_model import LogisticRegression
    model = LogisticRegression(max_iter=1000)
    model.fit(np.array(X, dtype="float32"), np.array(y))
    coefs = {f: float(model.coef_[0][j]) for j, f in enumerate(FEATURES)}

    # in nicht-negative, auf 'semantic' normierte Gewichte überführen
    pos = {f: max(0.0, coefs[f]) for f in FEATURES}
    if pos["semantic"] <= 0:
        res.note = "Lernen unschlüssig (semantic<=0) – Cold-Start bleibt aktiv."
        return res
    s = pos["semantic"]
    weights = {f: round(pos[f] / s, 3) for f in FEATURES}
    save_weights(cfg.data_dir, weights)
    res.trained = True
    res.weights = weights
    res.note = "Gewichte aus Klicks neu gelernt und gespeichert."
    log.info("Gehirn trainiert: %s", weights)
    return res
