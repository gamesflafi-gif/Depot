"""Kuratierter Aufbau eines Start-Korpus für die Fokusfelder.

Statt „alles" zu laden (für 8 GB RAM unrealistisch), holen wir gezielt
hochwertige Arbeiten aus mehreren Themenfeldern – aktuell, mit Abstract,
optional zitationsstark. Ergebnis: ein dichter, relevanter Index, der genau
zu den Beispiel-Fragen der Startseite passt und sich später erweitern lässt.

OpenAlex-Filter (aktuelle Syntax, „sicherer als sicher"):
  title_and_abstract.search:<begriffe>   -> präzise thematisch
  has_abstract:true                      -> nur mit Abstract (für Embeddings)
  from_publication_date:JJJJ-01-01       -> Aktualität
  type:article                           -> Artikel statt Editorials etc.
  cited_by_count:>N                      -> (optional) Mindest-Einfluss
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from synapse.config import Config
from synapse.ingest import ingest

log = logging.getLogger(__name__)

# Themenfeld -> OpenAlex-Suchbegriffe (deckt die Startseiten-Beispiele ab).
THEMES: dict[str, str] = {
    "Schlaf & Gedächtnis":        "sleep memory consolidation",
    "KI in der Medizin":          "machine learning clinical diagnosis",
    "Mikroplastik & Gesundheit":  "microplastics human health",
    "CRISPR / Genom-Editierung":  "CRISPR gene editing",
    "Klima & Landwirtschaft":     "climate change agriculture",
    "Erneuerbare Energie":        "renewable energy solar photovoltaic",
    "Energiespeicher / Batterie": "battery energy storage",
    "Neurowissenschaften":        "neuroscience brain imaging",
    "Onkologie":                  "cancer treatment immunotherapy",
    "Antibiotikaresistenz":       "antibiotic resistance bacteria",
}


def build_filter(query: str, since: int, min_citations: int) -> str:
    parts = [
        f"title_and_abstract.search:{query}",
        "has_abstract:true",
        f"from_publication_date:{since}-01-01",
        "type:article",
    ]
    if min_citations > 0:
        parts.append(f"cited_by_count:>{min_citations}")
    return ",".join(parts)


@dataclass
class CorpusResult:
    per_theme: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)
    total_ingested: int = 0
    total_in_store: int = 0


def load_corpus(cfg: Config, per_theme: int = 2000, since: int = 2015,
                min_citations: int = 0, themes: dict[str, str] | None = None,
                progress=lambda *_: None) -> CorpusResult:
    """Lädt für jedes Themenfeld bis zu ``per_theme`` Arbeiten in den Daten-Lake.
    Ein Fehler in einem Feld (z.B. Filter/Netz) stoppt nicht den Gesamtlauf –
    das Feld wird übersprungen und am Ende berichtet."""
    themes = themes or THEMES
    res = CorpusResult()
    for name, query in themes.items():
        flt = build_filter(query, since, min_citations)
        progress(f"[{name}] lade bis {per_theme} … ({query})")
        try:
            r = ingest(cfg, filter_str=flt, max_records=per_theme)
        except RuntimeError as exc:               # ungültiger Filter / Netzfehler
            res.skipped[name] = str(exc).splitlines()[0][:160]
            progress(f"[{name}] übersprungen: {res.skipped[name]}")
            continue
        res.per_theme[name] = r.ingested
        res.total_ingested += r.ingested
        res.total_in_store = r.total_in_store
        progress(f"[{name}] +{r.ingested} (Bestand {r.total_in_store})")
    return res
