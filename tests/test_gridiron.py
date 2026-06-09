"""Offline-Tests für Gridiron (Sample-Modus, ohne Netzwerk)."""
from __future__ import annotations

from gridiron.config import Config


def _cfg(tmp_path) -> Config:
    cfg = Config()
    cfg.data_dir = str(tmp_path)
    cfg.source_mode = "sample"
    return cfg


def test_features_buckets():
    from gridiron.features import dist_bucket, field_zone, numeric_vector, NUMERIC_FEATURES
    assert dist_bucket(2) == "kurz" and dist_bucket(5) == "mittel" and dist_bucket(12) == "lang"
    assert field_zone(10) == "Red Zone" and field_zone(95) == "tief eigene Hälfte"
    v = numeric_vector({"down": 3, "ydstogo": 8, "shotgun": True})
    assert len(v) == len(NUMERIC_FEATURES) and v[0] == 3.0 and v[6] == 1.0  # shotgun->1


def test_ingest_sample_idempotent(tmp_path):
    from gridiron.ingest import ingest
    from gridiron.storage import GridironStore
    cfg = _cfg(tmp_path)
    res = ingest(cfg)
    assert res.inserted > 500 and res.total_in_store == res.inserted
    # zweiter Lauf: idempotent (kein Wachstum)
    res2 = ingest(cfg)
    assert res2.total_in_store == res.total_in_store
    with GridironStore(cfg) as store:
        s = store.stats()
        assert s["pass_plays"] > 0 and s["run_plays"] > 0
        assert set(["RUN", "AIR", "BAL", "MIX"]).issubset(set(store.teams()))


def test_tendencies_detect_run_vs_pass_team(tmp_path):
    """Das lauflastige Team muss eine niedrigere Pass-Rate haben als das passlastige."""
    from gridiron.ingest import ingest
    from gridiron.tendencies import scout, render
    cfg = _cfg(tmp_path)
    ingest(cfg)
    run_team = scout(cfg, "RUN")
    air_team = scout(cfg, "AIR")
    assert run_team.n_plays > 100 and air_team.n_plays > 100
    assert run_team.pass_rate < air_team.pass_rate            # Tendenz erkannt
    # Vergleich zur Liga: RUN unter, AIR über dem Schnitt
    assert run_team.pass_rate < run_team.league_pass_rate
    assert air_team.pass_rate > air_team.league_pass_rate
    txt = render(run_team)
    assert "Scouting-Report: RUN" in txt and "Pass" in txt
    assert run_team.by_down_dist                              # Aufschlüsselung vorhanden


def test_tells_are_predictable(tmp_path):
    """3rd & lang sollte als vorhersehbare Pass-Situation auftauchen."""
    from gridiron.ingest import ingest
    from gridiron.tendencies import scout
    cfg = _cfg(tmp_path)
    ingest(cfg)
    rep = scout(cfg, "AIR", min_n=5)
    # mind. ein Tell mit klarer Pass-Tendenz
    assert any(t["pass_rate"] >= 0.75 for t in rep.tells)


def test_model_trains_and_beats_baseline(tmp_path):
    from gridiron.ingest import ingest
    from gridiron.model import train, Predictor
    cfg = _cfg(tmp_path)
    ingest(cfg)
    r = train(cfg)
    assert r.trained and r.n > 500
    assert r.accuracy >= r.baseline                          # nicht schlechter als Raten

    pred = Predictor(cfg)
    # 3rd & lang aus Shotgun -> hohe Pass-Wahrscheinlichkeit
    a = pred.assess({"team": "AIR", "down": 3, "ydstogo": 12, "yardline_100": 60,
                     "qtr": 2, "shotgun": True})
    b = pred.assess({"team": "RUN", "down": 1, "ydstogo": 10, "yardline_100": 5,
                     "qtr": 1, "shotgun": False})
    assert a["pass_prob"] > b["pass_prob"]                   # plausible Ordnung
    assert 0.0 <= a["predictability"] <= 1.0


def test_predictor_missing_model(tmp_path):
    from gridiron.model import Predictor
    import pytest
    with pytest.raises(FileNotFoundError):
        Predictor(_cfg(tmp_path))


def test_web_endpoints(tmp_path):
    """Web liefert Teams, Scouting-Report und Vorhersage; Seiten laden."""
    from fastapi.testclient import TestClient
    from gridiron.ingest import ingest
    from gridiron.model import train
    from gridiron.web import create_app
    cfg = _cfg(tmp_path)
    ingest(cfg)
    train(cfg)
    client = TestClient(create_app(cfg))

    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/").status_code == 200
    assert client.get("/report").status_code == 200

    t = client.get("/api/teams").json()
    assert "AIR" in t["teams"] and t["seasons"]

    rep = client.get("/api/scout", params={"team": "AIR"}).json()
    assert rep["n_plays"] > 100 and rep["pass_rate"] > rep["league_pass_rate"]
    assert rep["by_down_dist"]

    pr = client.get("/api/predict", params={"team": "AIR", "down": 3, "ydstogo": 12,
                                            "yardline": 60, "shotgun": 1}).json()
    assert 0.0 <= pr["pass_prob"] <= 1.0 and pr["likely"] in ("PASS", "RUN")


def test_simulator_football_logic():
    """Deterministische Engine bildet bekannte Matchups korrekt ab."""
    from gridiron.simulator import simulate, list_concepts, list_coverages
    assert len(list_concepts()) == 19 and len(list_coverages()) == 8
    sit = {"down": 3, "ydstogo": 8, "yardline_100": 60}
    # Four Verts schlagen Single-High (Cover 3) deutlich besser als Quarters (Cover 4)
    verts3 = simulate(None, "Four Verts", "Cover 3", sit)
    verts4 = simulate(None, "Four Verts", "Cover 4", sit)
    assert verts3.expected_epa > verts4.expected_epa
    # Mesh (Mann-Killer) gegen Cover 0 (Mann) besser als gegen Quarters-Zone
    assert simulate(None, "Mesh", "Cover 0", sit).expected_epa > \
           simulate(None, "Mesh", "Cover 4", sit).expected_epa
    # Verteilung normiert, Raten im gültigen Bereich
    assert abs(sum(b["pct"] for b in verts3.hist) - 1.0) < 0.02
    assert 0.0 <= verts3.success_rate <= 1.0 and verts3.verdict


def test_simulator_advisors():
    from gridiron.simulator import best_concepts, stopping_coverages, matrix
    sit = {"down": 1, "ydstogo": 10, "yardline_100": 60}
    best = best_concepts(None, "Cover 3", sit, top=5)
    assert len(best) == 5
    assert best[0].expected_epa >= best[-1].expected_epa          # absteigend sortiert
    stop = stopping_coverages(None, "Four Verts", sit)
    assert len(stop) == 8 and stop[0].expected_epa <= stop[-1].expected_epa
    m = matrix(None, sit)
    assert len(m["rows"]) == 19 and len(m["coverages"]) == 8
    assert all(len(row["epa"]) == 8 for row in m["rows"])


def test_simulator_invalid():
    from gridiron.simulator import simulate
    import pytest
    with pytest.raises(ValueError):
        simulate(None, "Gibt-es-nicht", "Cover 3", {})
    with pytest.raises(ValueError):
        simulate(None, "Mesh", "Cover 99", {})


def test_sim_web_endpoints(tmp_path):
    from fastapi.testclient import TestClient
    from gridiron.web import create_app
    client = TestClient(create_app(_cfg(tmp_path)))   # ohne Daten: Defaults
    assert len(client.get("/api/sim/meta").json()["concepts"]) == 19
    r = client.get("/api/sim/run", params={"concept": "Four Verts", "coverage": "Cover 3"}).json()
    assert r["verdict"] and -1.5 <= r["expected_epa"] <= 1.5
    assert len(client.get("/api/sim/matrix").json()["rows"]) == 19
    assert client.get("/api/sim/run", params={"concept": "X", "coverage": "Cover 3"}).status_code == 400
    assert "Play-Simulator" in client.get("/").text


def test_franchise_full_season(tmp_path):
    """Franchise: gründen, Kader verbessern, ganze Saison bis zum Meister."""
    from gridiron import franchise as F
    cfg = _cfg(tmp_path)
    st = F.new_franchise(cfg, "Berlin Adler", n_teams=8, difficulty="normal", seed=1)
    assert len(st["teams"]) == 8 and len(st["schedule"]) == 7
    assert st["teams"][0]["user"] and st["teams"][0]["name"] == "Berlin Adler"

    # Upgrade hebt die Stufe, kostet Budget
    before_ovr, before_budget = F.overall(st["teams"][0]), st["budget"]
    res = F.upgrade_unit(cfg, st, "QB")
    assert res["ok"] and st["budget"] < before_budget
    assert F.overall(st["teams"][0]) >= before_ovr

    # ganze Saison + Playoffs durchspielen
    guard = 0
    while st["phase"] != "done" and guard < 40:
        F.sim_week(cfg, st)
        guard += 1
    assert st["phase"] == "done" and st["champion"]
    tbl = F.standings(st)
    assert tbl[0]["rank"] == 1 and tbl[0]["w"] >= tbl[-1]["w"]    # sortiert
    assert st["history"] and st["history"][-1]["champion"] == st["champion"]

    # Persistenz + neue Saison
    assert F.load(cfg)["season"] == 1
    F.new_season(cfg, st)
    assert st["season"] == 2 and st["week"] == 0 and st["phase"] == "regular"
    assert st["teams"][0]["w"] == 0


def test_franchise_web(tmp_path):
    from fastapi.testclient import TestClient
    from gridiron.web import create_app
    client = TestClient(create_app(_cfg(tmp_path)))
    assert client.get("/api/fr/state").json()["exists"] is False
    assert "Manager" in client.get("/").text

    v = client.post("/api/fr/new", params={"team": "Test FC", "teams": 6}).json()
    assert v["team_name"] == "Test FC" and len(v["standings"]) == 6
    assert client.get("/api/fr/state").json()["exists"] is True

    r = client.post("/api/fr/sim_week").json()
    assert r["view"]["week"] == 1 and r["result"]["games"]

    up = client.post("/api/fr/upgrade", params={"unit": "WR"}).json()
    assert up["result"].get("ok") or up["result"].get("error")
    assert client.post("/api/fr/reset").json()["ok"]
    assert client.get("/api/fr/state").json()["exists"] is False


def test_playviz_diagram():
    from gridiron.playviz import diagram
    import pytest
    d = diagram("Four Verts", "Cover 3")
    assert d["kind"] == "pass" and len(d["offense"]) == 11 and len(d["defense"]) == 11
    assert any(o.get("target") for o in d["offense"]) and d["ball_target"]
    # Defense hat Rollen; Front stürmt, Zone-Coverage hat Zonen-Drops
    roles = [p["role"] for p in d["defense"]]
    assert roles.count("rush") == 4 and "zone" in roles
    # Mann-Coverage: Verteidiger decken konkrete Receiver
    man_cov = diagram("Mesh", "Cover 0")["defense"]
    assert any(p["role"] == "man" and p.get("cover") for p in man_cov)
    assert sum(p["role"] == "rush" for p in man_cov) >= 5      # All-Out-Blitz
    # alle Koordinaten im Feld
    for o in d["offense"]:
        assert 0 <= o["x"] <= d["width"]
    r = diagram("Power", "Cover 1")
    assert r["kind"] == "run"
    carrier = [o for o in r["offense"] if o.get("carry")]
    assert len(carrier) == 1 and len(carrier[0]["route"]) >= 2
    with pytest.raises(ValueError):
        diagram("Nope", "Cover 3")


def test_franchise_detailed_game(tmp_path):
    """Nutzer-Spiel liefert ein vollständiges Play-by-Play für die Übertragung."""
    from gridiron import franchise as F
    cfg = _cfg(tmp_path)
    st = F.new_franchise(cfg, "Adler", n_teams=6, seed=2)
    out = F.sim_week(cfg, st)
    g = out.get("user_game")
    assert g and g["plays"] and "Adler" in (g["home"], g["away"])
    assert g["hs"] != g["as"]                                   # kein Unentschieden
    assert any(p["score"] for p in g["plays"])                  # es wurde gepunktet
    for p in g["plays"]:
        assert 0 <= p["x"] <= 100 and p["q"] in (1, 2, 3, 4)
    assert F.view(st)["has_last_game"]
    # Endpoint-Form
    from fastapi.testclient import TestClient
    from gridiron.web import create_app
    client = TestClient(create_app(cfg))
    assert client.get("/api/fr/last_game").json()["game"]["hs"] == g["hs"]
    dia = client.get("/api/sim/diagram", params={"concept": "Mesh", "coverage": "Cover 2"}).json()
    assert len(dia["offense"]) == 11


def test_simulator_outcomes_and_sampler():
    from gridiron.simulator import simulate, play_outcome
    import numpy as np
    r = simulate(None, "Four Verts", "Cover 0", {"down": 3, "ydstogo": 8, "yardline_100": 60})
    assert abs(sum(o["pct"] for o in r.outcomes) - 1.0) < 0.02
    assert 0 <= r.completion_rate <= 1 and 0 <= r.int_rate <= 1 and r.sack_rate > 0
    rng = np.random.default_rng(0)
    kinds = set()
    for _ in range(400):
        kinds.add(play_outcome("Four Verts", "Cover 0", {"yardline_100": 60}, rng)["kind"])
    assert {"complete", "incomplete"} & kinds


def test_franchise_upgrades_staff_stadium(tmp_path):
    from gridiron import franchise as F
    cfg = _cfg(tmp_path)
    st = F.new_franchise(cfg, "Adler", n_teams=6, seed=4)
    st["budget"] = 200
    ov0 = F.overall(st["teams"][0])
    assert F.upgrade_unit(cfg, st, "OC")["ok"]
    assert F.upgrade_unit(cfg, st, "DC")["ok"]
    assert F.overall(st["teams"][0]) >= ov0                     # Coaches heben OVR
    s = F.upgrade_unit(cfg, st, "stadium")
    assert s["ok"] and s["level"] == 2
    assert F.upgrade_unit(cfg, st, "quatsch").get("error")


def test_franchise_roster_training(tmp_path):
    """Kader mit Spielern, Training hebt OVR, Units bleiben konsistent."""
    from gridiron import franchise as F
    cfg = _cfg(tmp_path)
    st = F.new_franchise(cfg, "Adler", n_teams=6, seed=7)
    team = st["teams"][0]
    assert len(team["roster"]) == sum(F.ROSTER_SLOTS.values())
    assert team["units"] == F._units_from_roster(team["roster"])   # synchron
    team["tp"] = 99
    p = next(x for x in team["roster"] if x["ovr"] < x["pot"])
    before = p["ovr"]
    res = F.train_player(cfg, st, p["id"])
    assert res["ok"] and p["ovr"] == before + 1
    assert team["units"] == F._units_from_roster(team["roster"])   # nach Training synchron
    # Equipment + Stadion sind Budget-Verbesserungen
    st["budget"] = 200
    assert F.upgrade_unit(cfg, st, "equipment")["ok"]
    v = F.view(st)
    assert v["roster"] and v["tp"] and v["equipment"]["level"] == 2


def test_franchise_interactive_game(tmp_path):
    """Selbst spielen: Plays callen bis Spielende, Ergebnis wird gewertet."""
    import random
    from gridiron import franchise as F
    cfg = _cfg(tmp_path)
    st = F.new_franchise(cfg, "Adler", n_teams=6, seed=5)
    g = F.start_game(cfg, st)["game"]
    assert g["awaiting"] in ("offense", "defense") and g["options"]
    guard = 0
    while not g["over"] and guard < 300:
        g = F.game_play(cfg, st, g["options"][0]["key"])["game"]
        guard += 1
    assert g["over"] and g["drive"] >= F.MAX_DRIVES
    fin = F.finish_game(cfg, st)
    assert fin["ok"] and fin["view"]["week"] == 1            # Woche fortgeschritten
    assert not F.load(cfg).get("active_game")                # Spiel abgeschlossen
    # Selbst-Ergebnis steht in der Tabelle (Bilanz Summe 1 Spiel)
    me = next(t for t in fin["view"]["standings"] if t["user"])
    assert me["w"] + me["l"] == 1


def test_franchise_game_web(tmp_path):
    from fastapi.testclient import TestClient
    from gridiron.web import create_app
    client = TestClient(create_app(_cfg(tmp_path)))
    client.post("/api/fr/new", params={"team": "FC", "teams": 6})
    g = client.post("/api/fr/game/start").json()["game"]
    assert g["options"]
    r = client.post("/api/fr/game/play", params={"choice": g["options"][0]["key"]}).json()
    assert r["ok"] and "game" in r
    assert client.post("/api/fr/upgrade", params={"unit": "HC"}).json()["result"]


def test_web_predict_without_model(tmp_path):
    """Ohne trainiertes Modell antwortet /api/predict sauber mit 503."""
    from fastapi.testclient import TestClient
    from gridiron.ingest import ingest
    from gridiron.web import create_app
    cfg = _cfg(tmp_path)
    ingest(cfg)
    client = TestClient(create_app(cfg))
    r = client.get("/api/predict", params={"team": "AIR"})
    assert r.status_code == 503 and "Modell" in r.json()["error"]
