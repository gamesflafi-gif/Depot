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


def test_accounts_security():
    """Passwort-Hashing ist sicher (scrypt, salted, nicht umkehrbar)."""
    from synapse import accounts
    h = accounts.hash_pw("geheim123")
    assert h.startswith("scrypt$") and "geheim123" not in h
    assert accounts.verify_pw("geheim123", h) is True
    assert accounts.verify_pw("falsch", h) is False
    assert accounts.hash_pw("x") != accounts.hash_pw("x")        # unterschiedliche Salts


def test_accounts_and_gating(tmp_path):
    """Konto: Registrierung/Login/Profil + Login-Pflicht für Projekte/Beiträge."""
    from fastapi.testclient import TestClient
    from synapse.web import create_app
    cfg = _cfg(tmp_path)
    client = TestClient(create_app(cfg))

    # ohne Login: Projekt anlegen verboten
    assert client.post("/api/projects", json={"title": "Geheimprojekt"}).status_code == 401
    assert client.get("/api/me").json()["user"] is None

    # Registrierung (ohne ORCID -> keine Netzwerk-Prüfung) meldet direkt an
    r = client.post("/api/register", json={"username": "dr_mueller", "password": "supersicher1",
                                           "name": "Dr. Müller"}).json()
    assert r["ok"]
    me = client.get("/api/me").json()["user"]
    assert me and me["username"] == "dr_mueller" and me["orcid_verified"] is False

    # jetzt eingeloggt: Projekt + Beitrag laufen, Autor = Profil
    pc = client.post("/api/projects", json={"title": "Forschung zu Schlafstörungen",
                                            "area": "Neuro"}).json()
    assert pc["ok"]
    pid = pc["data"]["id"]
    cc = client.post("/api/projects/contribute", params={"id": pid},
                     json={"kind": "progress", "title": "Erste Messreihe",
                           "body": "Vorläufige Daten."}).json()
    assert cc["ok"]
    d = client.get("/api/projects/get", params={"id": pid}).json()
    assert d["owner_name"] == "Dr. Müller"
    assert d["contributions"][0]["contributor_name"] == "Dr. Müller"

    # doppelter Nutzername abgelehnt; falsches Passwort -> 401
    assert client.post("/api/register", json={"username": "dr_mueller",
                                              "password": "anders12"}).status_code == 400
    client.post("/api/logout", json={})
    assert client.post("/api/login", json={"username": "dr_mueller",
                                           "password": "falsch"}).status_code == 401
    assert client.post("/api/login", json={"username": "dr_mueller",
                                           "password": "supersicher1"}).json()["ok"]
    assert client.get("/konto").status_code == 200


def test_password_policy():
    """Passwort-Richtlinie wehrt schwache Passwörter ab, lässt starke zu."""
    from synapse.accounts import validate_password
    assert validate_password("kurz")                       # zu kurz
    assert validate_password("passwort", "x")              # zu verbreitet
    assert validate_password("aaaaaaaaaaaa")               # zu wenig Varianz
    assert validate_password("lena12345", "lena12345")     # = Nutzername
    assert validate_password("Sicher-2026!xy") == ""       # stark -> akzeptiert


def test_login_brute_force_lockout(tmp_path):
    """Nach zu vielen Fehlversuchen wird der Login kurz gesperrt –
    auch ein dann korrektes Passwort wird abgewiesen."""
    from fastapi.testclient import TestClient
    from synapse.web import create_app
    cfg = _cfg(tmp_path)
    client = TestClient(create_app(cfg))
    client.post("/api/register", json={"username": "opfer", "password": "richtig-passwort-9"})
    client.post("/api/logout", json={})

    for _ in range(5):                                     # 5 Fehlversuche
        assert client.post("/api/login", json={"username": "opfer",
                                               "password": "falsch-falsch"}).status_code == 401
    # nun gesperrt: selbst das korrekte Passwort wird (vorübergehend) blockiert
    r = client.post("/api/login", json={"username": "opfer", "password": "richtig-passwort-9"})
    assert r.status_code == 401
    assert "Fehlversuche" in r.json()["message"] or "warten" in r.json()["message"]


def test_change_password_and_session_invalidation(tmp_path):
    """Passwort ändern: altes muss stimmen, neues wird gehärtet; danach gilt
    nur noch das neue Passwort."""
    from fastapi.testclient import TestClient
    from synapse.web import create_app
    cfg = _cfg(tmp_path)
    client = TestClient(create_app(cfg))
    client.post("/api/register", json={"username": "wechsler", "password": "altes-passwort-1"})

    # falsches altes Passwort -> abgelehnt
    assert client.post("/api/password", json={"old_password": "stimmt-nicht",
                                              "new_password": "neues-passwort-2"}).status_code == 400
    # zu schwaches neues Passwort -> abgelehnt
    assert client.post("/api/password", json={"old_password": "altes-passwort-1",
                                              "new_password": "kurz"}).status_code == 400
    # gültiger Wechsel
    assert client.post("/api/password", json={"old_password": "altes-passwort-1",
                                              "new_password": "neues-passwort-2"}).json()["ok"]

    # aktuelle Sitzung bleibt aktiv (keep_token)
    assert client.get("/api/me").json()["user"]["username"] == "wechsler"
    client.post("/api/logout", json={})
    # altes Passwort gilt nicht mehr, neues schon
    assert client.post("/api/login", json={"username": "wechsler",
                                           "password": "altes-passwort-1"}).status_code == 401
    assert client.post("/api/login", json={"username": "wechsler",
                                           "password": "neues-passwort-2"}).json()["ok"]


def test_security_headers(tmp_path):
    """Jede Antwort trägt Schutz-Header (Clickjacking/MIME/CSP)."""
    from fastapi.testclient import TestClient
    from synapse.web import create_app
    cfg = _cfg(tmp_path)
    h = TestClient(create_app(cfg)).get("/").headers
    assert h["x-frame-options"] == "DENY"
    assert h["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in h["content-security-policy"]
    assert "frame-ancestors 'none'" in h["content-security-policy"]


def test_student_account_and_project_type(tmp_path):
    """Studierende ohne ORCID können mitforschen – ehrlich als „Student:in"
    gekennzeichnet; Projekt-Typ (Forschung/Studienprojekt) wird mitgeführt."""
    from fastapi.testclient import TestClient
    from synapse.web import create_app
    cfg = _cfg(tmp_path)
    client = TestClient(create_app(cfg))

    # Registrierung als Student:in (keine ORCID nötig)
    r = client.post("/api/register", json={"username": "studi_lena", "password": "lernen12345",
                                           "name": "Lena", "account_type": "student",
                                           "affiliation": "Uni Köln"}).json()
    assert r["ok"]
    me = client.get("/api/me").json()["user"]
    assert me["account_type"] == "student" and me["orcid_verified"] is False
    assert me["affiliation"] == "Uni Köln"

    # Studienprojekt anlegen (ptype=student)
    pc = client.post("/api/projects", json={"title": "Studienprojekt Lernverhalten",
                                            "area": "Psychologie", "ptype": "student"}).json()
    assert pc["ok"]
    pid = pc["data"]["id"]
    client.post("/api/projects/contribute", params={"id": pid},
                json={"kind": "progress", "title": "Vorläufige Umfrage",
                      "body": "Erste Ergebnisse."})

    d = client.get("/api/projects/get", params={"id": pid}).json()
    assert d["ptype"] == "student"
    c0 = d["contributions"][0]
    assert c0["author_type"] == "student" and c0["author_affiliation"] == "Uni Köln"
    assert c0["author_verified"] is False

    # Profil-Update kann den Konto-Typ ändern (z.B. nach Abschluss)
    upd = client.post("/api/profile", json={"account_type": "researcher"}).json()
    assert upd["ok"]
    assert client.get("/api/me").json()["user"]["account_type"] == "researcher"

    # ungültiger Typ fällt auf „other" zurück
    client.post("/api/register", json={"username": "rando_x", "password": "passwort123",
                                       "account_type": "blödsinn"})
    assert client.get("/api/me").json()["user"]["account_type"] == "other"


def test_collab_projects(tmp_path):
    """Kollaborative Forschung: Projekt anlegen, Beiträge mit Vertrauens-Stufen,
    Melden→Flag, Owner-Moderation per Token."""
    from synapse import projects
    cfg = _cfg(tmp_path)

    # Projekt anlegen -> Owner-Token zurück
    r = projects.create_project(cfg, "Forschung zu Schlafstörungen",
                                area="Neurowissenschaften", owner_name="Dr. X")
    assert r.ok and r.data["owner_token"]
    pid, token = r.data["id"], r.data["owner_token"]
    assert projects.create_project(cfg, "abc").ok is False     # Titel zu kurz

    # Beiträge mit unterschiedlichen Vertrauens-Stufen
    c_comm = projects.add_contribution(cfg, pid, "progress", "Zwischenstand Woche 1",
                                       body="Erste Auswertung der Schlafdaten.")
    assert c_comm.ok and c_comm.data["trust_level"] == "community"
    c_pre = projects.add_contribution(cfg, pid, "dataset", "Rohdaten",
                                      link="https://zenodo.org/record/123")
    assert c_pre.data["trust_level"] == "preprint"             # anerkanntes Repo

    # Auflisten + Detail
    lst = projects.list_projects(cfg)
    assert lst and lst[0]["id"] == pid and lst[0]["contributions"] == 2
    d = projects.get_project(cfg, pid)
    assert d["title"].startswith("Forschung zu") and len(d["contributions"]) == 2

    # Melden -> Beitrag wird geflaggt
    cid = c_comm.data["id"]
    assert projects.report(cfg, cid, "Spam").ok
    d2 = projects.get_project(cfg, pid)
    assert next(c for c in d2["contributions"] if c["id"] == cid)["status"] == "flagged"

    # Moderation: falscher Token verboten, richtiger entfernt
    assert projects.moderate(cfg, pid, "falsch", cid, "remove").ok is False
    assert projects.moderate(cfg, pid, token, cid, "remove").ok
    d3 = projects.get_project(cfg, pid)
    assert all(c["id"] != cid for c in d3["contributions"])    # entfernt nicht mehr sichtbar

    # archiviert -> keine neuen Beiträge
    assert projects.archive(cfg, pid, token, True).ok
    assert projects.add_contribution(cfg, pid, "finding", "Neuer Beitrag").ok is False


def test_collab_web(tmp_path):
    """Web-API der Projekte: anlegen, Detail, Beitrag, melden."""
    from fastapi.testclient import TestClient
    from synapse.web import create_app
    cfg = _cfg(tmp_path)
    client = TestClient(create_app(cfg))
    client.post("/api/register", json={"username": "forscher_a", "password": "passwort123",
                                       "name": "A"})        # Login nötig zum Anlegen

    r = client.post("/api/projects", json={"title": "Offene Krebs-Datenbasis",
                                           "area": "Onkologie"}).json()
    assert r["ok"] and r["data"]["owner_token"]
    pid = r["data"]["id"]

    c = client.post("/api/projects/contribute", params={"id": pid},
                    json={"kind": "finding", "title": "Beobachtung zu Tumorwachstum",
                          "body": "Hinweis auf Zusammenhang."}).json()
    assert c["ok"] and "Stufe: community" in c["message"]
    # sensibles Thema -> Warnhinweis im Text
    assert "unbestätigt" in c["message"] or "Beratung" in c["message"]

    d = client.get("/api/projects/get", params={"id": pid}).json()
    assert d["contributions"] and d["contributions"][0]["trust_level"] == "community"
    assert client.get("/projekte").status_code == 200


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
