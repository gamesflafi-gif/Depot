"""Phase-0-Tests für Synapse (offline, ohne Netzwerk)."""
from __future__ import annotations

from synapse.config import Config
from synapse.models import Work, reconstruct_abstract
from synapse.storage import SynapseStore


def _cfg(tmp_path) -> Config:
    cfg = Config()
    cfg.data_dir = str(tmp_path)
    cfg.source_mode = "sample"
    return cfg


def test_openalex_filter_url_keeps_colons():
    """OpenAlex-Filter müssen ':' und ',' wörtlich enthalten (sonst HTTP 400)."""
    import urllib.parse
    params = {"per-page": 200, "cursor": "*",
              "filter": "concepts.id:C154945302,from_publication_date:2024-01-01"}
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params, safe=":,*")
    assert "concepts.id:C154945302,from_publication_date:2024-01-01" in url
    assert "%3A" not in url and "%2C" not in url


def test_reconstruct_abstract():
    inv = {"Hallo": [0, 2], "Welt": [1]}
    assert reconstruct_abstract(inv) == "Hallo Welt Hallo"
    assert reconstruct_abstract(None) == ""


def test_work_from_openalex():
    raw = {
        "id": "https://openalex.org/W42",
        "title": "Test",
        "abstract_inverted_index": {"a": [0], "b": [1]},
        "doi": "https://doi.org/10.1/x",
        "publication_year": 2022, "cited_by_count": 7,
        "open_access": {"is_oa": True, "oa_url": "u"},
        "primary_location": {"source": {"display_name": "Venue"}},
        "authorships": [{"author": {"display_name": "X Y"}}],
        "concepts": [{"display_name": "AI", "score": 0.9}],
        "referenced_works": ["https://openalex.org/W7"],
    }
    w = Work.from_openalex(raw)
    assert w.id == "W42" and w.year == 2022 and w.cited_by_count == 7
    assert w.doi == "10.1/x" and w.abstract == "a b" and w.is_oa
    assert w.authors == ["X Y"] and w.referenced_works == ["W7"]


def test_semantic_search_offline(tmp_path):
    """Phase 1: Index bauen + Suche findet das thematisch passende Werk (offline)."""
    from synapse.ingest import ingest
    from synapse.index import build_index, SearchEngine
    cfg = _cfg(tmp_path)
    ingest(cfg, max_records=100)

    n = build_index(cfg, prefer="hash")        # Offline-Hash-Embedder
    assert n == 3

    eng = SearchEngine(cfg)
    # „protein structure neural network" -> W1001 (Deep learning for protein structure)
    hits = eng.search("protein structure prediction neural network", k=3)
    assert hits and hits[0].id == "W1001"
    # „attention sequence model" -> W1002 (Attention is all you need)
    hits2 = eng.search("attention mechanism for sequence modeling", k=3)
    assert hits2[0].id == "W1002"
    # „energy storage graphene" -> W1003
    hits3 = eng.search("graphene supercapacitor energy storage", k=3)
    assert hits3[0].id == "W1003"


def test_ingest_sample_idempotent(tmp_path):
    """Sample laden -> 3 gültige Werke + 1 Dead-Letter; erneuter Lauf = keine Duplikate."""
    from synapse.ingest import ingest
    cfg = _cfg(tmp_path)

    res = ingest(cfg, max_records=100)
    assert res.ingested == 3 and res.failed == 1 and res.total_in_store == 3

    # zweiter Lauf: idempotent -> Bestand bleibt 3
    res2 = ingest(cfg, max_records=100)
    assert res2.total_in_store == 3

    with SynapseStore(cfg) as store:
        s = store.stats()
        assert s["works"] == 3 and s["dead_letter"] == 2     # DLQ wächst, works nicht
        assert s["open_access"] == 2 and s["with_abstract"] == 3
        assert s["year_min"] == 2017 and s["year_max"] == 2021
        # Parquet-Export funktioniert
        path = store.export_parquet()
        assert path.endswith(".parquet")
