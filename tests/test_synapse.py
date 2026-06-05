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

    n = build_index(cfg, prefer="hash", batch=2)   # Batch < Anzahl: Chunking testen
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


def test_web_api(tmp_path):
    """Web-API liefert Suchtreffer und protokolliert Klick-Feedback (offline)."""
    from fastapi.testclient import TestClient
    from synapse.ingest import ingest
    from synapse.index import build_index
    from synapse.web import create_app
    from synapse.storage import SynapseStore
    cfg = _cfg(tmp_path)
    ingest(cfg, max_records=100)
    build_index(cfg, prefer="hash")

    client = TestClient(create_app(cfg))
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/").status_code == 200

    r = client.get("/api/search", params={"q": "protein structure neural network", "k": 3})
    data = r.json()
    assert data["results"] and data["results"][0]["id"] == "W1001"

    # Klick-Feedback wird geloggt (Grundlage fürs Gehirn)
    fb = client.post("/api/feedback", params={"q": "protein", "work_id": "W1001", "rank": 0})
    assert fb.json()["ok"] is True
    with SynapseStore(cfg) as store:
        assert store.count_events("click") == 1 and store.count_events("search") >= 1


def test_add_to_index_incremental(tmp_path):
    """Belegte Arbeit nachträglich in den Index aufnehmen (ohne Neu-Bau)."""
    from synapse.ingest import ingest
    from synapse.index import build_index, add_to_index, SearchEngine
    cfg = _cfg(tmp_path)
    ingest(cfg, max_records=100)
    build_index(cfg, prefer="hash")

    new = {"id": "W9999", "title": "Quantum error correction with surface codes",
           "abstract": "We demonstrate fault tolerant quantum error correction.",
           "year": 2024, "doi": "10.9/qec", "venue": "Nature", "cited_by_count": 5}
    assert add_to_index(cfg, [new]) == 1
    assert add_to_index(cfg, [new]) == 0          # idempotent (kein Duplikat)

    eng = SearchEngine(cfg)                         # lädt erweiterten Index
    hits = eng.search("quantum error correction surface codes", k=3)
    assert any(h.id == "W9999" for h in hits)


def test_assistant_no_markdown(tmp_path):
    """Verdikt enthält kein rohes Markdown (kein '**')."""
    from synapse import assistant
    from synapse.ingest import ingest
    from synapse.index import build_index
    cfg = _cfg(tmp_path)
    ingest(cfg, max_records=100)
    build_index(cfg, prefer="hash")
    b = assistant.analyze(cfg, "deep learning")
    assert "**" not in b.verdict
    assert assistant._keywords("Gibt es Forschung zu Schlaf und Gedächtnis?") == "schlaf gedächtnis"


def test_assistant_briefing(tmp_path):
    """Forschungs-Assistent: liefert Einordnung, Themen, Top-/neueste Arbeiten."""
    from synapse import assistant
    from synapse.ingest import ingest
    from synapse.index import build_index
    from fastapi.testclient import TestClient
    from synapse.web import create_app
    cfg = _cfg(tmp_path)
    ingest(cfg, max_records=100)
    build_index(cfg, prefer="hash")

    b = assistant.analyze(cfg, "protein structure prediction with neural networks")
    assert b.local_count >= 1 and b.verdict
    assert "Deep learning" in b.themes
    assert b.top_works and b.top_works[0]["cited_by_count"] >= 0
    assert "Frage:" in assistant.render(b)

    # Web-Endpoint /api/ask liefert dieselbe Struktur
    client = TestClient(create_app(cfg))
    d = client.get("/api/ask", params={"q": "attention sequence modeling"}).json()
    assert d["verdict"] and isinstance(d["results"], list) and d["results"]


def test_connections_cross_field(tmp_path):
    """Verbindungs-Entdeckung: verwandte Arbeiten + Feld-Brücken markieren."""
    from synapse.ingest import ingest
    from synapse.index import build_index, SearchEngine
    from fastapi.testclient import TestClient
    from synapse.web import create_app
    cfg = _cfg(tmp_path)
    ingest(cfg, max_records=100)
    build_index(cfg, prefer="hash")

    eng = SearchEngine(cfg)
    res = eng.connections("W1001", k=5)        # Deep-Learning-Protein-Paper
    assert res is not None
    field, conns = res
    assert field == "Deep learning"            # primäres Feld aus Konzepten
    assert conns                                # Nachbarn vorhanden
    # mind. eine Verbindung aus einem anderen Feld ist als Brücke markiert
    assert any(c.cross_field for c in conns)
    assert eng.connections("DOES_NOT_EXIST") is None

    # Web-Endpoint liefert dieselben Daten
    client = TestClient(create_app(cfg))
    d = client.get("/api/related", params={"id": "W1001", "k": 5}).json()
    assert d["field"] == "Deep learning" and d["related"]


def test_brain_learns_from_clicks(tmp_path):
    """Phase 2: aus Klicks werden Ranking-Gewichte gelernt und angewandt."""
    from synapse import brain
    from synapse.ingest import ingest
    from synapse.index import build_index, SearchEngine
    from synapse.storage import SynapseStore
    from synapse.ranking import load_weights
    cfg = _cfg(tmp_path)
    ingest(cfg, max_records=100)
    build_index(cfg, prefer="hash")

    # zu wenig Klicks -> Cold-Start bleibt
    assert brain.train(cfg, prefer="hash").trained is False

    # genug Klick-Feedback protokollieren (thematisch passend angeklickt)
    with SynapseStore(cfg) as store:
        for _ in range(8):
            store.log_event("click", "protein structure neural network", "W1001", 0)
            store.log_event("click", "attention sequence modeling", "W1002", 0)

    res = brain.train(cfg, prefer="hash")
    assert res.n_clicks >= 16 and res.trained is True
    w = load_weights(cfg.data_dir)
    assert w["semantic"] == 1.0 and set(w) == {"semantic", "keyword", "citations", "recency"}

    # Suche nutzt die gelernten Gewichte und bleibt sinnvoll
    eng = SearchEngine(cfg)
    assert eng.search("protein structure prediction", k=3)[0].id == "W1001"


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
