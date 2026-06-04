"""Semantischer Index & Suche (Phase 1).

Bettet alle Werke (Titel + Abstract) lokal ein und speichert die Vektoren auf
Platte. Die Suche bettet die Anfrage ein und findet per Cosinus-Ähnlichkeit die
nächsten Werke – **hybrid** mit einem leichten Stichwort-Bonus, damit exakte
Treffer (Begriffe/Autoren) nicht untergehen.

Für den Piloten (zehntausende bis wenige Hunderttausend Werke) ist eine
NumPy-Cosinus-Suche schnell genug (<100 ms) und abhängigkeitsfrei. Für Millionen
Werke wird in der Skalierungsphase ein ANN-Index (hnswlib/Qdrant) eingesetzt –
gleiche Schnittstelle. Siehe PROJECT_PLAN_SYNAPSE.md.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from synapse.config import Config
from synapse.embeddings import _tokenize, get_embedder
from synapse.storage import SynapseStore

log = logging.getLogger(__name__)


@dataclass
class SearchHit:
    id: str
    title: str
    year: int | None
    doi: str
    venue: str
    cited_by_count: int
    score: float


def _index_dir(cfg: Config) -> Path:
    p = Path(cfg.data_dir) / "index"
    p.mkdir(parents=True, exist_ok=True)
    return p


def build_index(cfg: Config, prefer: str = "auto", batch: int = 256,
                max_chars: int = 2000) -> int:
    """Erzeugt Embeddings für alle Werke und speichert den Index.

    Speicherschonend: bettet **in Batches** ein (nicht alles auf einmal -> sonst
    OOM bei vielen Werken) und kürzt überlange Texte auf ``max_chars`` (das Modell
    nutzt ohnehin nur die ersten ~512 Token).
    """
    with SynapseStore(cfg) as store:
        records = store.fetch_for_index()
    if not records:
        log.warning("Keine Werke zum Indizieren.")
        return 0

    embedder = get_embedder(prefer=prefer)
    texts = [(f"{r['title']}. {r['abstract']}").strip()[:max_chars] for r in records]
    log.info("Erzeuge Embeddings für %d Werke (%s, Batch %d) …",
             len(texts), embedder.name, batch)

    chunks: list[np.ndarray] = []
    for i in range(0, len(texts), batch):
        v = embedder.embed(texts[i:i + batch]).astype("float32")
        # L2-normieren (Cosinus = Skalarprodukt)
        v /= np.clip(np.linalg.norm(v, axis=1, keepdims=True), 1e-9, None)
        chunks.append(v)
        if (i // batch) % 10 == 0:
            log.info("  … %d/%d eingebettet", min(i + batch, len(texts)), len(texts))
    vecs = np.vstack(chunks)

    d = _index_dir(cfg)
    np.save(d / "vectors.npy", vecs)
    meta = [{k: r[k] for k in ("id", "title", "year", "doi", "venue", "cited_by_count")}
            for r in records]
    json.dump(meta, open(d / "meta.json", "w", encoding="utf-8"), ensure_ascii=False)
    json.dump({"embedder": embedder.name, "dim": int(vecs.shape[1]), "count": len(records)},
              open(d / "index.json", "w", encoding="utf-8"))
    log.info("Index gebaut: %d Werke, Dim %d, Embedder %s",
             len(records), vecs.shape[1], embedder.name)
    return len(records)


class SearchEngine:
    """Lädt den Index in den Speicher und beantwortet Suchanfragen.

    Ranking: semantische Ähnlichkeit + Stichwort + Zitationen + Aktualität,
    gewichtet vom Gehirn (gelernte Gewichte, sonst Cold-Start-Defaults).
    """

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        d = _index_dir(cfg)
        info = json.load(open(d / "index.json", encoding="utf-8"))
        self.vecs: np.ndarray = np.load(d / "vectors.npy")
        self.meta: list = json.load(open(d / "meta.json", encoding="utf-8"))
        self.embedder = get_embedder(prefer=info.get("embedder", "auto"))
        self._tokens = [set(_tokenize(m["title"])) for m in self.meta]
        from synapse.ranking import load_weights
        self.weights = load_weights(cfg.data_dir)

    def search(self, query: str, k: int = 10, candidates: int = 100) -> list[SearchHit]:
        from synapse.ranking import make_features, score
        qv = self.embedder.embed([query]).astype("float32")[0]
        n = np.linalg.norm(qv)
        if n > 0:
            qv = qv / n
        sims = self.vecs @ qv                       # Cosinus-Ähnlichkeit
        q_tokens = set(_tokenize(query))

        # nur die besten Kandidaten voll bewerten (schnell)
        n_cand = min(candidates, len(sims))
        cand_idx = np.argpartition(-sims, n_cand - 1)[:n_cand]

        scored = []
        for i in cand_idx:
            i = int(i)
            m = self.meta[i]
            kw = (len(q_tokens & self._tokens[i]) / len(q_tokens)) if q_tokens else 0.0
            feats = make_features(float(sims[i]), kw, m["cited_by_count"], m["year"])
            scored.append((score(feats, self.weights), i))

        scored.sort(key=lambda t: t[0], reverse=True)
        hits = []
        for sc, i in scored[:k]:
            m = self.meta[i]
            hits.append(SearchHit(
                id=m["id"], title=m["title"], year=m["year"], doi=m["doi"],
                venue=m["venue"], cited_by_count=m["cited_by_count"], score=float(sc)))
        return hits
