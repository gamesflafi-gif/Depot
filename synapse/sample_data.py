"""Offline-Beispieldaten im OpenAlex-Format (für Tests/Demo ohne Netzwerk).

Enthält bewusst auch einen fehlerhaften Satz (ohne ID), damit die
Dead-Letter-Behandlung getestet wird.
"""
from __future__ import annotations


def _inv(text: str) -> dict:
    """Baut einen OpenAlex-„abstract_inverted_index" aus normalem Text."""
    idx: dict[str, list[int]] = {}
    for i, word in enumerate(text.split()):
        idx.setdefault(word, []).append(i)
    return idx


SAMPLE_WORKS: list[dict] = [
    {
        "id": "https://openalex.org/W1001",
        "title": "Deep learning for protein structure prediction",
        "abstract_inverted_index": _inv(
            "We present a neural network that predicts protein structures from sequence."),
        "doi": "https://doi.org/10.1000/abc1",
        "publication_year": 2021, "cited_by_count": 1500,
        "open_access": {"is_oa": True, "oa_url": "https://example.org/w1001.pdf"},
        "primary_location": {"source": {"display_name": "Nature"}},
        "authorships": [{"author": {"display_name": "A. Smith"}},
                        {"author": {"display_name": "B. Lee"}}],
        "concepts": [{"display_name": "Deep learning", "score": 0.9},
                     {"display_name": "Proteins", "score": 0.8}],
        "referenced_works": ["https://openalex.org/W1002"],
        "updated_date": "2023-01-01",
    },
    {
        "id": "https://openalex.org/W1002",
        "title": "Attention is all you need",
        "abstract_inverted_index": _inv(
            "A new architecture based solely on attention mechanisms for sequence modeling."),
        "doi": "https://doi.org/10.1000/abc2",
        "publication_year": 2017, "cited_by_count": 90000,
        "open_access": {"is_oa": True, "oa_url": "https://example.org/w1002.pdf"},
        "primary_location": {"source": {"display_name": "NeurIPS"}},
        "authorships": [{"author": {"display_name": "C. Vaswani"}}],
        "concepts": [{"display_name": "Attention", "score": 0.95}],
        "referenced_works": [],
        "updated_date": "2023-02-01",
    },
    {
        "id": "https://openalex.org/W1003",
        "title": "Graphene-based supercapacitors for energy storage",
        "abstract_inverted_index": _inv(
            "High-capacity energy storage using graphene electrodes and novel electrolytes."),
        "doi": "https://doi.org/10.1000/abc3",
        "publication_year": 2020, "cited_by_count": 320,
        "open_access": {"is_oa": False, "oa_url": ""},
        "primary_location": {"source": {"display_name": "Advanced Materials"}},
        "authorships": [{"author": {"display_name": "D. Müller"}}],
        "concepts": [{"display_name": "Energy storage", "score": 0.88},
                     {"display_name": "Graphene", "score": 0.85}],
        "referenced_works": ["https://openalex.org/W1001"],
        "updated_date": "2023-03-01",
    },
    {   # fehlerhaft: keine ID -> Dead-Letter
        "title": "Broken record without id",
        "publication_year": 2019,
    },
]
