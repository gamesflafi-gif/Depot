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
    assert len(st["teams"]) == 8 and len(st["schedule"]) == 8 and [] in st["schedule"]  # 7 Spiele + 1 Bye
    assert st["teams"][0]["user"] and st["teams"][0]["name"] == "Berlin Adler"

    # Upgrade hebt die Stufe, kostet Budget
    before_ovr, before_budget = F.overall(st["teams"][0]), st["budget"]
    res = F.upgrade_unit(cfg, st, "QB")
    assert res["ok"] and st["budget"] < before_budget
    assert F.overall(st["teams"][0]) >= before_ovr

    # ganze Saison + Playoffs durchspielen
    guard = 0
    while st["phase"] != "done" and guard < 80:
        if st.get("week_done"):
            F.next_week(cfg, st)
        else:
            F.do_training(cfg, st, "team")
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

    client.post("/api/fr/train_week", params={"kind": "team"})           # Training Pflicht vor Spiel
    r = client.post("/api/fr/sim_week").json()
    assert r["result"]["games"] and r["view"]["week_done"] is True
    nw = client.post("/api/fr/next_week").json()
    assert nw["view"]["week"] == 1 and nw["view"]["week_done"] is False

    up = client.post("/api/fr/improve_coach", params={"role": "HC"}).json()
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
    F.do_training(cfg, st, "team")
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


def test_franchise_season_goals(tmp_path):
    """Saison-Ziele werden gesetzt, erfüllt und mit Budget belohnt."""
    from gridiron import franchise as F
    cfg = _cfg(tmp_path)
    st = F.new_franchise(cfg, "Adler", n_teams=6, seed=9)
    assert st["goals"] and any(g["key"] == "wins" for g in st["goals"])
    v = F.view(st)
    assert v["goals"][0]["done"] is False and "reward" in v["goals"][0]
    # Saison durchspielen -> mindestens das Sieg- oder Playoff-Ziel sollte fallen
    guard = 0
    while st["phase"] != "done" and guard < 80:
        if st.get("week_done"):
            F.next_week(cfg, st)
        else:
            F.do_training(cfg, st, "team")
            F.sim_week(cfg, st)
        guard += 1
    assert any(g["done"] for g in st["goals"])
    # neue Saison -> Ziele neu (nicht erfüllt)
    F.new_season(cfg, st)
    assert all(not g["done"] for g in st["goals"])


def test_franchise_weekly_training(tmp_path):
    """1× Training pro Woche, Bye-Week, Film-Bonus, Reset bei Wochenwechsel."""
    from gridiron import franchise as F
    cfg = _cfg(tmp_path)
    st = F.new_franchise(cfg, "Adler", n_teams=6, seed=5)
    assert st["week_trained"] is False and [] in st["schedule"]      # Bye vorhanden
    assert F.do_training(cfg, st, "team")["ok"] and st["week_trained"] is True
    assert F.do_training(cfg, st, "team").get("error")               # nur 1× pro Woche
    F.sim_week(cfg, st); F.next_week(cfg, st)
    assert st["week_trained"] is False                               # neue Woche -> wieder möglich
    F.do_training(cfg, st, "film")
    assert st["teams"][0]["game_bonus"] > 0
    F.sim_week(cfg, st); F.next_week(cfg, st)
    assert st["teams"][0]["game_bonus"] == 0                         # Bonus verbraucht
    v = F.view(st)
    assert len(v["trainings"]) >= 6 and "week_trained" in v and "is_bye" in v


def test_franchise_game_sim_options(tmp_path):
    """Interaktives Spiel: Drive simulieren bzw. Rest bis Ende simulieren."""
    from gridiron import franchise as F
    cfg = _cfg(tmp_path)
    st = F.new_franchise(cfg, "Adler", n_teams=6, seed=51)
    F.do_training(cfg, st, "team")
    F.start_game(cfg, st)
    r = F.game_sim_drive(cfg, st)
    assert ("game" in r) or ("result" in r)                # weiter ODER schon vorbei
    fin = F.game_sim_rest(cfg, st)
    assert fin["ok"] and fin["result"]["hs"] != fin["result"]["as"]
    assert fin["view"]["week_done"] is True and not F.load(cfg).get("active_game")
    nw = F.next_week(cfg, st)
    assert nw["view"]["week"] == 1


def test_franchise_player_season_career_stats(tmp_path):
    """Spieler sammeln Saison- & Karrierestatistik; Saison-Reset behält Karriere."""
    from gridiron import franchise as F
    cfg = _cfg(tmp_path)
    st = F.new_franchise(cfg, "Adler", n_teams=6, seed=71)
    for _ in range(3):
        F.do_training(cfg, st, "team"); F.sim_week(cfg, st); F.next_week(cfg, st)
    team = st["teams"][0]
    assert any(p["season"]["games"] > 0 for p in team["roster"])
    assert all(p["career"]["games"] >= p["season"]["games"] for p in team["roster"])
    pr = F.view(st)["roster"][0]
    assert "season" in pr and "career" in pr and "games" in pr["season"]
    career_yds = sum(p["career"]["rush_yds"] for p in team["roster"])
    F.new_season(cfg, st)
    assert all(p["season"]["games"] == 0 for p in st["teams"][0]["roster"])
    assert sum(p["career"]["rush_yds"] for p in st["teams"][0]["roster"]) == career_yds


def test_franchise_box_scores(tmp_path):
    """Simuliertes Nutzer-Spiel erzeugt Box-Scores und vergibt Leistungs-EXP."""
    from gridiron import franchise as F
    cfg = _cfg(tmp_path)
    st = F.new_franchise(cfg, "Adler", n_teams=6, seed=21)
    F.do_training(cfg, st, "team")
    g = F.sim_week(cfg, st)["user_game"]
    assert g["box"] and len(g["box"]) >= 4
    assert any(s["pass_yds"] or s["rush_yds"] or s["rec_yds"] for s in g["box"])   # Offense
    assert any(s["tkl"] or s["sack"] or s["intc"] for s in g["box"])               # Defense
    assert any(p["exp"] > 0 or p["pts"] > 0 for p in st["teams"][0]["roster"])     # Leistungs-EXP


def test_franchise_events_injuries(tmp_path):
    """Verletzungen senken das Rating; Wochen erzeugen Events."""
    from gridiron import franchise as F
    cfg = _cfg(tmp_path)
    st = F.new_franchise(cfg, "Adler", n_teams=6, seed=11)
    team = st["teams"][0]
    ov0 = F.overall(team)
    q = next(p for p in team["roster"] if p["pos"] == "QB" and p["starter"])
    q["inj"] = 2
    F._sync_units(team)
    assert F.overall(team) <= ov0                               # verletzter Starter schwächt
    seen = set()
    for _ in range(8):
        F.do_training(cfg, st, "team")
        for e in F.sim_week(cfg, st).get("events", []):
            seen.add(e["type"])
        F.next_week(cfg, st)
    assert seen                                                 # Events sind aufgetreten
    assert "inj" in F.view(st)["roster"][0]


def test_franchise_transfers_and_draft(tmp_path):
    """Transfermarkt: entlassen, verpflichten; Saisonwechsel mit Ruhestand + neuer Klasse."""
    from gridiron import franchise as F
    cfg = _cfg(tmp_path)
    st = F.new_franchise(cfg, "Adler", n_teams=6, seed=41)
    st["budget"] = 300
    assert len(st["market_players"]) >= 10
    wr = next(p for p in st["teams"][0]["roster"] if p["pos"] == "WR")
    assert F.cut_player(cfg, st, wr["id"])["ok"]
    assert all(p["id"] != wr["id"] for p in st["teams"][0]["roster"])
    fa = next(p for p in st["market_players"] if p["pos"] == "WR")
    assert F.sign_player(cfg, st, fa["id"])["ok"]
    assert any(p["id"] == fa["id"] for p in st["teams"][0]["roster"])
    F.new_season(cfg, st)
    assert len(st["market_players"]) >= 10 and st["events"]
    v = F.view(st)
    assert v["market_players"] and v["slots"]


def test_franchise_coaches_and_facilities(tmp_path):
    from gridiron import franchise as F
    cfg = _cfg(tmp_path)
    st = F.new_franchise(cfg, "Adler", n_teams=6, seed=4)
    st["budget"] = 400
    team = st["teams"][0]
    # Trainer haben individuelle Stärken
    assert set(team["coaches"]) == {"HC", "OC", "DC"}
    assert team["coaches"]["OC"]["traits"] and team["coaches"]["OC"]["name"]
    # Verbessern hebt den schwächsten Trait
    r = F.improve_coach(cfg, st, "OC")
    assert r["ok"] and r["value"] >= 47
    # Markt: besten OC-Kandidaten anheuern
    mk = st["coach_market"]["OC"]
    best = max(range(len(mk)), key=lambda i: F.coach_rating(mk[i]))
    h = F.hire_coach(cfg, st, "OC", best)
    assert h["ok"] and team["coaches"]["OC"]["name"] == h["hired"]
    # Anlagen
    s = F.upgrade_unit(cfg, st, "stadium")
    assert s["ok"] and s["level"] == 2
    assert F.upgrade_unit(cfg, st, "quatsch").get("error")


def test_franchise_roster_attributes_exp(tmp_path):
    """Kader mit Attributen, EXP->Skillpunkte, Verteilung hebt Attribut & OVR."""
    from gridiron import franchise as F
    cfg = _cfg(tmp_path)
    st = F.new_franchise(cfg, "Adler", n_teams=6, seed=7)
    team = st["teams"][0]
    assert len(team["roster"]) == sum(F.ROSTER_SLOTS.values())
    p = team["roster"][0]
    assert p["attr"] and p["cap"] and "exp" in p and F.player_ovr(p) > 0
    for k in p["attr"]:
        assert p["cap"][k] >= p["attr"][k]                          # Cap nie unter Wert
    assert team["units"] == F._units_from_roster(team["roster"])    # Units aus Kader
    # Skillpunkt verteilen hebt Attribut + Units
    p["pts"] = 1
    attr = next(k for k in p["attr"] if p["attr"][k] < p["cap"][k])
    before = p["attr"][attr]
    r = F.alloc(cfg, st, p["id"], attr)
    assert r["ok"] and p["attr"][attr] == before + 1
    assert team["units"] == F._units_from_roster(team["roster"])
    # Auto-verteilen, Starter-Toggle, Fokus
    p["pts"] = 4
    assert F.alloc_auto(cfg, st, p["id"])["ok"]
    assert "starter" in F.depth_toggle(cfg, st, p["id"])
    assert F.set_focus(cfg, st, "QB")["focus"] == "QB"
    # EXP durch Wochentraining (Pflicht) + Spiel
    F.do_training(cfg, st, "team")
    F.sim_week(cfg, st)
    assert any(x["exp"] > 0 or x["pts"] > 0 for x in team["roster"])
    v = F.view(st)
    assert v["roster"][0]["attrs"] and "skillpoints" in v


def test_franchise_interactive_game(tmp_path):
    """Selbst spielen: Plays callen bis Spielende, Ergebnis wird gewertet."""
    import random
    from gridiron import franchise as F
    cfg = _cfg(tmp_path)
    st = F.new_franchise(cfg, "Adler", n_teams=6, seed=5)
    F.do_training(cfg, st, "team")
    g = F.start_game(cfg, st)["game"]
    assert g["awaiting"] in ("offense", "defense") and g["options"]
    guard = 0
    while not g["over"] and guard < 300:
        g = F.game_play(cfg, st, g["options"][0]["key"])["game"]
        guard += 1
    assert g["over"] and g["drive"] >= F.MAX_DRIVES
    fin = F.finish_game(cfg, st)
    assert fin["ok"] and fin["view"]["week_done"] is True    # Woche ausgewertet
    assert not F.load(cfg).get("active_game")                # Spiel abgeschlossen
    # Selbst-Ergebnis steht in der Tabelle (Bilanz Summe 1 Spiel)
    me = next(t for t in fin["view"]["standings"] if t["user"])
    assert me["w"] + me["l"] == 1
    assert F.next_week(cfg, st)["view"]["week"] == 1         # erst Klick schreitet fort


def test_franchise_game_web(tmp_path):
    from fastapi.testclient import TestClient
    from gridiron.web import create_app
    client = TestClient(create_app(_cfg(tmp_path)))
    client.post("/api/fr/new", params={"team": "FC", "teams": 6})
    client.post("/api/fr/train_week", params={"kind": "team"})           # Training Pflicht vor Spiel
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
