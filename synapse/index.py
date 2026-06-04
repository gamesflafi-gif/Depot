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
    """Lädt den Index in den Speicher und beantwortet Suchanfragen."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        d = _index_dir(cfg)
        info = json.load(open(d / "index.json", encoding="utf-8"))
        self.vecs: np.ndarray = np.load(d / "vectors.npy")
        self.meta: list = json.load(open(d / "meta.json", encoding="utf-8"))
        self.embedder = get_embedder(prefer=info.get("embedder", "auto"))
        # Token-Mengen für den Stichwort-Bonus (hybrid)
        self._tokens = [set(_tokenize(f"{m['title']}")) for m in self.meta]

    def search(self, query: str, k: int = 10) -> list[SearchHit]:
        qv = self.embedder.embed([query]).astype("float32")[0]
        n = np.linalg.norm(qv)
        if n > 0:
            qv = qv / n
        sims = self.vecs @ qv                      # Cosinus-Ähnlichkeit

        # leichter Hybrid-Bonus: Stichwort-Überlappung im Titel
        q_tokens = set(_tokenize(query))
        if q_tokens:
            overlap = np.array([
                len(q_tokens & t) / len(q_tokens) for t in self._tokens
            ], dtype="float32")
            scores = 0.85 * sims + 0.15 * overlap
        else:
            scores = sims

        top = np.argsort(-scores)[:k]
        hits = []
        for i in top:
            m = self.meta[int(i)]
            hits.append(SearchHit(
                id=m["id"], title=m["title"], year=m["year"], doi=m["doi"],
                venue=m["venue"], cited_by_count=m["cited_by_count"],
                score=float(scores[int(i)])))
        return hits
