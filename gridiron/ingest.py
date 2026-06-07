"""Ingestion: nflverse -> Daten-Lake. Idempotent (Upsert über play_id),
robust (Batches), wiederholbar."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from gridiron.config import Config
from gridiron.sources import nflverse
from gridiron.storage import GridironStore

log = logging.getLogger(__name__)


@dataclass
class IngestResult:
    inserted: int = 0
    total_in_store: int = 0


def ingest(cfg: Config, seasons: list[int] | None = None,
           batch_size: int = 5000) -> IngestResult:
    seasons = seasons or cfg.seasons
    res = IngestResult()
    with GridironStore(cfg) as store:
        batch: list[dict] = []
        for play in nflverse.iter_plays(cfg, seasons):
            batch.append(play)
            if len(batch) >= batch_size:
                res.inserted += store.insert_plays(batch)
                batch = []
        if batch:
            res.inserted += store.insert_plays(batch)
        res.total_in_store = store.count_plays()
    log.info("Ingestion fertig: +%d, Bestand %d", res.inserted, res.total_in_store)
    return res
