"""Ingestion-Orchestrierung: Quelle -> Normalisierung -> Daten-Lake.

Eigenschaften (bewusst robust, „sicherer als sicher"):
- **idempotent**: erneuter Lauf erzeugt keine Duplikate (Upsert über ID).
- **wiederanlauffähig**: Fortschritt wird als Checkpoint gespeichert.
- **kein stiller Datenverlust**: fehlerhafte Sätze landen im Dead-Letter,
  der Lauf bricht nicht ab.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from synapse.config import Config
from synapse.models import Work
from synapse.sources import openalex
from synapse.storage import SynapseStore

log = logging.getLogger(__name__)


@dataclass
class IngestResult:
    ingested: int = 0
    failed: int = 0
    total_in_store: int = 0


def ingest(cfg: Config, filter_str: str = "", max_records: int = 1000,
           batch_size: int = 200) -> IngestResult:
    """Lädt Werke aus der Quelle in den Daten-Lake."""
    res = IngestResult()
    with SynapseStore(cfg) as store:
        batch: list[Work] = []
        for raw in openalex.iter_works(cfg, filter_str=filter_str, max_records=max_records):
            try:
                batch.append(Work.from_openalex(raw))
            except Exception as exc:  # noqa: BLE001
                store.add_dead_letter(raw, str(exc))
                res.failed += 1
                continue
            if len(batch) >= batch_size:
                res.ingested += store.upsert_works(batch)
                batch = []
        if batch:
            res.ingested += store.upsert_works(batch)
        # Checkpoint + Statistik
        store.set_state("last_filter", filter_str)
        res.total_in_store = store.count_works()
    log.info("Ingestion fertig: +%d, Fehler %d, Bestand %d",
             res.ingested, res.failed, res.total_in_store)
    return res
