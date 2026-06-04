"""Datenmodell: ein normalisiertes Forschungs-„Werk" (Work).

Wandelt rohe OpenAlex-JSON-Datensätze in eine flache, stabile Form um, die in
DuckDB/Parquet liegt. Bewusst robust: fehlende Felder -> sinnvolle Defaults,
keine Exceptions bei unvollständigen Daten (die landen sonst im Dead-Letter).
"""
from __future__ import annotations

from dataclasses import dataclass, field


def reconstruct_abstract(inverted_index: dict | None) -> str:
    """OpenAlex liefert Abstracts als inverted index {wort: [positionen]}.
    Hier wird daraus wieder lesbarer Fließtext gebaut."""
    if not inverted_index:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort(key=lambda p: p[0])
    return " ".join(w for _, w in positions)


def _short_id(openalex_id: str | None) -> str:
    """'https://openalex.org/W123' -> 'W123'."""
    if not openalex_id:
        return ""
    return openalex_id.rstrip("/").rsplit("/", 1)[-1]


@dataclass
class Work:
    id: str
    title: str = ""
    abstract: str = ""
    doi: str = ""
    year: int | None = None
    cited_by_count: int = 0
    is_oa: bool = False
    oa_url: str = ""
    venue: str = ""
    authors: list = field(default_factory=list)            # Namen
    concepts: list = field(default_factory=list)           # [{name, score}]
    referenced_works: list = field(default_factory=list)   # Zitations-Graph (IDs)
    updated_date: str = ""

    @classmethod
    def from_openalex(cls, raw: dict) -> "Work":
        """Parst einen OpenAlex-Datensatz. Wirft KeyError nur bei fehlender ID
        (dann gehört der Satz ins Dead-Letter)."""
        wid = _short_id(raw["id"])                # ID ist Pflicht
        loc = raw.get("primary_location") or {}
        src = (loc.get("source") or {}) if isinstance(loc, dict) else {}
        oa = raw.get("open_access") or {}
        return cls(
            id=wid,
            title=(raw.get("title") or raw.get("display_name") or "").strip(),
            abstract=reconstruct_abstract(raw.get("abstract_inverted_index")),
            doi=(raw.get("doi") or "").replace("https://doi.org/", ""),
            year=raw.get("publication_year"),
            cited_by_count=int(raw.get("cited_by_count") or 0),
            is_oa=bool(oa.get("is_oa", False)),
            oa_url=oa.get("oa_url") or "",
            venue=(src.get("display_name") or "") if isinstance(src, dict) else "",
            authors=[(a.get("author") or {}).get("display_name", "")
                     for a in (raw.get("authorships") or [])
                     if (a.get("author") or {}).get("display_name")],
            concepts=[{"name": c.get("display_name", ""),
                       "score": float(c.get("score") or 0.0)}
                      for c in (raw.get("concepts") or [])],
            referenced_works=[_short_id(r) for r in (raw.get("referenced_works") or [])],
            updated_date=raw.get("updated_date") or "",
        )
