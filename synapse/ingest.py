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
class SubmitResult:
    ok: bool = False
    message: str = ""
    title: str = ""
    id: str = ""


def submit_doi(cfg: Config, doi: str) -> SubmitResult:
    """Nimmt eine **belegte** Arbeit per DOI auf – nur wenn sie offiziell in
    OpenAlex/Crossref registriert ist (sonst Ablehnung). So kann niemand
    beliebige, ungeprüfte Inhalte hochladen."""
    from synapse.sources import openalex
    raw = openalex.fetch_by_doi(cfg, doi)
    if not raw:
        return SubmitResult(False, "Nicht gefunden: Diese DOI ist nicht offiziell "
                            "registriert (OpenAlex/Crossref). Nur belegte Arbeiten "
                            "mit gültiger DOI können aufgenommen werden.")
    try:
        work = Work.from_openalex(raw)
    except Exception as exc:  # noqa: BLE001
        return SubmitResult(False, f"Datensatz unbrauchbar: {exc}")

    with SynapseStore(cfg) as store:
        store.upsert_works([work])
        store.log_event("submit", query=doi, work_id=work.id)
    # in den Suchindex aufnehmen (inkrementell)
    from synapse.index import add_to_index
    rec = {"id": work.id, "title": work.title, "abstract": work.abstract,
           "year": work.year, "doi": work.doi, "venue": work.venue,
           "cited_by_count": work.cited_by_count}
    add_to_index(cfg, [rec])
    return SubmitResult(True, "Aufgenommen und durchsuchbar gemacht.",
                        title=work.title, id=work.id)


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
