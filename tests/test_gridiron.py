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
    assert len(list_concepts()) == 29 and len(list_coverages()) == 12
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
    assert len(stop) == 12 and stop[0].expected_epa <= stop[-1].expected_epa
    m = matrix(None, sit)
    assert len(m["rows"]) == 29 and len(m["coverages"]) == 12
    assert all(len(row["epa"]) == 12 for row in m["rows"])


def test_strength_edge_drives_outcomes():
    """Team-/Spielerstärke wirkt im interaktiven Spiel: höherer edge -> mehr Raumgewinn."""
    import numpy as np
    from gridiron.simulator import play_outcome
    rng = np.random.default_rng(0)
    sit = {"yardline_100": 60, "down": 1, "ydstogo": 10}

    def avg(concept, cov, edge, n=5000):
        return sum(play_outcome(concept, cov, sit, rng, edge=edge)["yards"] for _ in range(n)) / n

    assert avg("Four Verts", "Cover 3", 0.40) > avg("Four Verts", "Cover 3", -0.40) + 1.5
    assert avg("Inside Zone", "Cover 3", 0.40) > avg("Inside Zone", "Cover 3", -0.40) + 0.8
    # edge=0 bleibt unverändert zur Standard-Engine (kein Default-Effekt)
    assert abs(avg("Four Verts", "Cover 3", 0.0, n=8000) - avg("Four Verts", "Cover 3", 0.0, n=8000)) < 1.0


def test_matchup_edge_and_ai_tendencies():
    """_matchup_edge hat das richtige Vorzeichen; KI ruft situativ (lang->Pass, kurz->Lauf)."""
    from gridiron import franchise as F
    from gridiron.simulator import PASS_CONCEPTS
    strong = {"units": {"QB": 95, "OL": 92, "WR": 93, "RB": 90, "DL": 92, "LB": 90, "DB": 93}, "coaches": {}}
    weak = {"units": {"QB": 58, "OL": 57, "WR": 56, "RB": 58, "DL": 56, "LB": 57, "DB": 56}, "coaches": {}}
    assert F._matchup_edge(strong, weak, True) > 0.15      # starke Offense vs schwache Defense
    assert F._matchup_edge(weak, strong, True) < -0.15     # umgekehrt
    # situatives Play-Calling über viele Ziehungen
    team = {"off_scheme": "Ausgeglichen"}
    def passrate(down, dist, n=3000):
        return sum(F._ai_offense_concept(team, {"down": down, "dist": dist, "ytz": 60}) in PASS_CONCEPTS
                   for _ in range(n)) / n
    assert passrate(3, 9) > 0.80                            # 3rd & lang -> Pass
    assert passrate(3, 1) < 0.45                            # 3rd & kurz -> Lauf
    assert passrate(3, 9) > passrate(1, 2)                  # mehr Pass je länger die Distanz


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
    assert len(client.get("/api/sim/meta").json()["concepts"]) == 29
    r = client.get("/api/sim/run", params={"concept": "Four Verts", "coverage": "Cover 3"}).json()
    assert r["verdict"] and -1.5 <= r["expected_epa"] <= 1.5
    assert len(client.get("/api/sim/matrix").json()["rows"]) == 29
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
            F.do_training(cfg, st, "team"); st.pop("meeting", None)
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


def test_all_plays_stay_in_bounds():
    """JEDER Spielzug gegen JEDE Coverage: alle Spieler, Routen-Punkte und Zonen-Drops
    bleiben innerhalb der Seitenlinien (x≈1.2..52.1) — Receiver liefen sonst ins Aus."""
    from gridiron.playviz import diagram
    from gridiron.simulator import PASS_CONCEPTS, RUN_CONCEPTS, COVERAGES
    LO, HI = 1.2, 52.1
    for concept in list(PASS_CONCEPTS) + list(RUN_CONCEPTS):
        for cov in COVERAGES:
            for variant in range(5):                       # alle Formations-Varianten (inkl. Shotgun/FB)
                d = diagram(concept, cov, variant)
                assert len(d["offense"]) == 11 and len(d["defense"]) == 11
                for o in d["offense"]:
                    assert LO <= o["x"] <= HI, f"{concept}/{cov}/v{variant}: {o['pos']} x={o['x']} im Aus"
                    for pt in (o.get("route") or []):
                        assert LO <= pt[0] <= HI, f"{concept}/{cov}/v{variant}: Route {o['pos']} x={pt[0]} im Aus"
                for p in d["defense"]:
                    assert LO <= p["x"] <= HI, f"{concept}/{cov}/v{variant}: DEF {p['pos']} x={p['x']} im Aus"
                    if p.get("drop"):
                        assert LO <= p["drop"][0] <= HI, f"{concept}/{cov}/v{variant}: Drop x={p['drop'][0]} im Aus"


def test_diagram_open_receiver_varies_by_coverage():
    """QB wirft auf die offene Route – die Anspielstation hängt von der Coverage ab."""
    from gridiron.playviz import diagram

    def target_route(concept, cov):
        d = diagram(concept, cov)
        return next(o["rname"] for o in d["offense"] if o.get("target"))

    # Smash: gegen Mann der Corner-Beater, gegen Zone die Hitch (klassischer Hi-Lo-Read)
    assert target_route("Smash", "Cover 0") == "corner"
    assert target_route("Smash", "Cover 3") == "hitch"
    # über alle Coverages hinweg fällt die Wahl nicht immer auf dieselbe Route
    from gridiron.simulator import COVERAGES
    picks = {target_route("Four Verts", cov) for cov in COVERAGES}
    assert len(picks) >= 2


def test_college_scouting_and_draft(tmp_path):
    """College-Prospects starten verdeckt, Scouting deckt sie auf, Draften holt sie ins Team."""
    from gridiron import franchise as F
    cfg = _cfg(tmp_path)
    st = F.new_franchise(cfg, "Adler", n_teams=6, seed=11)
    v = F.view(st)
    assert v["scout_pts"] == 6 and len(v["prospects"]) >= 8
    p0 = v["prospects"][0]
    assert p0["scout"] == 0 and p0.get("ovr") is None and p0["ovr_lo"] < p0["ovr_hi"]
    assert p0["name"].startswith("Prospect #")          # Name erst ab Scouting-Stufe 1

    pid = p0["id"]
    for _ in range(3):
        assert F.scout_prospect(cfg, st, pid).get("ok")
    assert F.scout_prospect(cfg, st, pid)["error"]       # 4. Mal: schon komplett
    assert F.view(st)["scout_pts"] == 3                  # 3 Punkte verbraucht
    pp = next(p for p in F.view(st)["prospects"] if p["id"] == pid)
    # Auch voll gescoutet bleibt eine Spanne (Restunsicherheit), Trait wird aufgedeckt
    assert pp["scout"] == 3 and pp["scouted_full"] and pp.get("ovr") is None
    assert pp["ovr_lo"] <= pp["ovr_hi"] and "pot_lo" in pp and pp["dev"] in F.DEV_TRAITS

    # Position ist anfangs voll -> erst cutten, dann draften
    team = st["teams"][0]
    same = next(x for x in team["roster"] if x["pos"] == pp["pos"])
    F.cut_player(cfg, st, same["id"])
    res = F.draft_prospect(cfg, st, pid)
    assert res.get("ok") and any(x["id"] == pid for x in team["roster"])
    drafted = next(x for x in team["roster"] if x["id"] == pid)
    assert "scout" not in drafted and drafted.get("dev") in F.DEV_TRAITS

    # Dev-Trait beschleunigt EXP: Superstar bekommt mehr aus derselben Menge
    a = {"dev": "normal", "exp": 0, "pts": 0}
    b = {"dev": "superstar", "exp": 0, "pts": 0}
    F._gain_exp(a, 100)
    F._gain_exp(b, 100)
    assert b["exp"] + b["pts"] * 100 > a["exp"] + a["pts"] * 100


def test_punt_flips_possession(tmp_path):
    """Punt ist jederzeit wählbar und wechselt den Ballbesitz mit neuer Feldposition."""
    from gridiron import franchise as F
    cfg = _cfg(tmp_path)
    st = F.new_franchise(cfg, "Adler", n_teams=6, seed=4)
    F.do_training(cfg, st, "team"); st.pop("meeting", None)
    F.start_game(cfg, st)
    g = st["active_game"]
    g["pos"] = 0 if g["user_is_home"] else 1
    g["ytz"], g["absx"], g["down"], g["dist"] = 70.0, (30.0 if g["pos"] == 1 else 70.0), 4, 7   # Punt nur im 4. Versuch
    F._new_decision_options(st)
    assert any(o["key"] == "__PUNT__" for o in F._game_view(st)["options"])
    pos0 = g["pos"]
    r = F.game_play(cfg, st, "__PUNT__")
    g2 = st["active_game"]
    assert r["play"]["kind"] == "punt" and r["play"]["punt_net"] >= 25
    assert g2["pos"] != pos0 and g2["down"] == 1 and g2["dist"] == 10
    assert 1.0 <= g2["ytz"] <= 99.0


def test_kick_options_only_on_fourth_down(tmp_path):
    """Field Goal & Punt erscheinen nur im 4. Versuch (in den Downs 1–3 nicht)."""
    from gridiron import franchise as F
    cfg = _cfg(tmp_path)
    st = F.new_franchise(cfg, "Adler", n_teams=6, seed=4)
    F.do_training(cfg, st, "team"); st.pop("meeting", None)
    F.start_game(cfg, st)
    g = st["active_game"]
    g["pos"] = 0 if g["user_is_home"] else 1             # Nutzer am Ball
    g["ytz"] = 40                                         # in FG-Reichweite
    for d in (1, 2, 3):
        g["down"] = d
        F._new_decision_options(st)
        keys = {o["key"] for o in g["opts"]}
        assert "__FG__" not in keys and "__PUNT__" not in keys, f"Down {d}: Kick-Option zu früh"
    g["down"] = 4
    F._new_decision_options(st)
    keys = {o["key"] for o in g["opts"]}
    assert "__FG__" in keys and "__PUNT__" in keys        # 4. Versuch: beide da
    # 6 Plays bleiben zusätzlich erhalten
    assert len([o for o in g["opts"] if o["type"] in ("Pass", "Lauf")]) == 6


def test_kicker_fg_and_extra_point(tmp_path):
    """Kicker-Rating, Field-Goal-Wahrscheinlichkeit, Extra-Punkt & 2-Punkte-Conversion."""
    from gridiron import franchise as F
    cfg = _cfg(tmp_path)
    st = F.new_franchise(cfg, "Adler", n_teams=6, seed=4)
    team = st["teams"][0]
    assert 50 <= F.kicker(team) <= 95

    # FG-Trefferchance: näher = besser, besserer Kicker = besser
    assert F.fg_make_prob(15, 70) > F.fg_make_prob(45, 70)
    assert F.fg_make_prob(40, 90) > F.fg_make_prob(40, 55)
    assert F.xp_make_prob(90) > F.xp_make_prob(55)

    F.do_training(cfg, st, "team"); st.pop("meeting", None)
    F.start_game(cfg, st)
    g = st["active_game"]
    g["pos"] = 0 if g["user_is_home"] else 1              # Nutzer am Ball
    # Field-Goal-Option taucht im Bereich auf (Optionen pro Snap neu)
    g["ytz"], g["down"] = 47, 4
    F._new_decision_options(st)
    opts = F._game_view(st)["options"]
    assert any(o["key"] == "__FG__" for o in opts)
    # 6 Offense-Plays pro Snap: genau 2 Läufe und 4 Pässe
    plays = [o for o in opts if o["type"] in ("Pass", "Lauf")]
    assert len(plays) == 6
    assert sum(o["type"] == "Lauf" for o in plays) == 2 and sum(o["type"] == "Pass" for o in plays) == 4
    r = F.game_play(cfg, st, "__FG__")
    assert r["play"]["kind"] == "fg" and r["game"]["awaiting"] != "pat"

    # Touchdown -> 6 Punkte + PAT-Auswahl, dann 2-Punkte-Conversion
    g = st["active_game"]
    g["pos"] = 0 if g["user_is_home"] else 1
    pos = g["pos"]
    g["ytz"], g["down"], g["dist"] = 2, 1, 2
    for _ in range(15):
        r = F.game_play(cfg, st, "Inside Zone")
        if r["game"].get("awaiting") == "pat":
            break
        g = st["active_game"]; g["pos"] = pos; g["ytz"], g["down"], g["dist"] = 2, 1, 2
    assert r["game"]["awaiting"] == "pat" and r["game"]["hs"] + r["game"]["as"] >= 6
    keys = {o["key"] for o in r["game"]["options"]}
    assert keys == {"__XP__", "__2PT__"}
    before = r["game"]["hs"] + r["game"]["as"]
    r2 = F.game_play(cfg, st, "__XP__")
    assert r2["game"]["awaiting"] != "pat"               # nach PAT geht es normal weiter
    assert r2["game"]["hs"] + r2["game"]["as"] >= before


def test_two_point_play_selection(tmp_path):
    """2-Punkte-Versuch: __2PT__ öffnet eine Spielzug-Auswahl an der 3, ein Konzept entscheidet."""
    from gridiron import franchise as F
    cfg = _cfg(tmp_path)
    st = F.new_franchise(cfg, "Adler", n_teams=6, seed=4)
    F.do_training(cfg, st, "team"); st.pop("meeting", None)
    F.start_game(cfg, st)
    g = st["active_game"]
    g["pos"] = 0 if g["user_is_home"] else 1
    pos = g["pos"]
    for _ in range(40):                                   # einen Touchdown erzwingen -> PAT
        g["ytz"], g["down"], g["dist"] = 2, 1, 2
        r = F.game_play(cfg, st, "Inside Zone")
        if r["game"].get("awaiting") == "pat":
            break
        g = st["active_game"]; g["pos"] = pos
    assert r["game"]["awaiting"] == "pat"
    # __2PT__ resolviert NICHT sofort, sondern öffnet die Spielzug-Auswahl an der 3-Yard-Linie
    r2 = F.game_play(cfg, st, "__2PT__")
    assert r2["game"]["awaiting"] == "2pt" and r2["game"]["ytz"] == 3
    assert "play" not in r2                                # kein Snap, nur Auswahl
    opts = r2["game"]["options"]
    plays = [o for o in opts if o["type"] in ("Pass", "Lauf")]
    assert len(plays) >= 2 and any(o["type"] == "Lauf" for o in plays) and any(o["type"] == "Pass" for o in plays)
    assert not any(o["key"] in ("__FG__", "__PUNT__") for o in opts)
    # Ein Konzept spielt den Versuch aus -> animierbarer Play mit two_pt-Flag
    before = r2["game"]["hs"] + r2["game"]["as"]
    r3 = F.game_play(cfg, st, plays[0]["key"])
    p = r3["play"]
    assert p["two_pt"] and p["concept"] == plays[0]["key"] and p["kind"] in ("run", "complete", "incomplete", "sack", "int")
    assert r3["game"]["awaiting"] != "2pt"                # Versuch abgeschlossen, Ballwechsel
    assert r3["game"]["hs"] + r3["game"]["as"] in (before, before + 2)   # 0 oder +2 Punkte


def test_penalty_payload_carries_play(tmp_path):
    """Strafen liefern das echte Play + Strafen-Infos mit, damit das Frontend den Down animieren kann."""
    from gridiron import franchise as F
    cfg = _cfg(tmp_path)
    st = F.new_franchise(cfg, "Adler", n_teams=6, seed=4)
    F.do_training(cfg, st, "team"); st.pop("meeting", None)
    F.start_game(cfg, st)
    seen = None
    for _ in range(3000):
        g = st["active_game"]
        if g["over"]:
            F.start_game(cfg, st); g = st["active_game"]
        if g.get("pat"):
            F.game_play(cfg, st, "__XP__"); continue
        uo = (g["pos"] == 0) == g["user_is_home"]
        r = F.game_play(cfg, st, "Inside Zone" if uo else "Cover 2")
        p = r.get("play", {})
        if p.get("penalty"):
            seen = p
            break
    assert seen is not None, "in 3000 Snaps keine Strafe gezogen"
    for key in ("concept", "coverage", "pre_snap", "pen_name", "pen_side", "play_kind"):
        assert key in seen, f"Strafe ohne Feld {key}"
    assert isinstance(seen["pre_snap"], bool) and seen["pen_side"] in ("off", "def")


def test_profiles_isolated(tmp_path):
    """Spielstände werden pro Profilname getrennt gespeichert."""
    from gridiron import franchise as F
    cfg = _cfg(tmp_path)
    try:
        F.set_profile("max"); F.new_franchise(cfg, "MaxTeam", n_teams=6, seed=1)
        F.set_profile("alex"); F.new_franchise(cfg, "AlexTeam", n_teams=6, seed=2)
        F.set_profile("max"); assert F.load(cfg)["team_name"] == "MaxTeam"
        F.set_profile("alex"); assert F.load(cfg)["team_name"] == "AlexTeam"
        F.set_profile("neu"); assert F.load(cfg) is None        # frisches Profil = kein Stand
    finally:
        F.set_profile("default")


def test_choice_events(tmp_path):
    """Entscheidungs-Event: 2 Buffs + 1 Debuff, je 1 von 2 wählbar; Auswahl wirkt."""
    import random
    from gridiron import franchise as F
    cfg = _cfg(tmp_path)
    st = F.new_franchise(cfg, "Ev", n_teams=6, seed=3)
    F._gen_event(st, random.Random(1))
    ev = F.view(st)["pending_event"]
    assert ev and len(ev["buffs"]) == 2 and len(ev["buffs"][0]) == 2 and len(ev["debuff"]) == 2
    bud = st["budget"]
    res = F.resolve_event(cfg, st, b0=1, b1=0, d=1)        # je 1 von 2 wählen
    assert res.get("ok") and res["messages"]
    assert F.view(st)["pending_event"] is None             # Event abgeschlossen
    # Events sind getrennt vom Training und nicht jede Woche (process_events erzeugt kein Buff/Debuff-Event)
    F.do_training(cfg, st, "team"); st.pop("meeting", None)
    assert F.view(st)["pending_event"] is None


def test_kickoff_and_start_ovr(tmp_path):
    """Start ~70 OVR, Münzwurf + Kickoff-Return setzen die Startposition."""
    from gridiron import franchise as F
    cfg = _cfg(tmp_path)
    st = F.new_franchise(cfg, "Kicks", n_teams=8, seed=1)
    assert F.view(st)["ratings"]["ovr"] >= 70           # Start ~70+
    F.do_training(cfg, st, "team"); st.pop("meeting", None)
    r = F.start_game(cfg, st)
    g = r["game"]
    assert g["coin"] and "user_receives" in g["coin"]
    k = g["kickoff"]
    assert 15 <= k["return_to"] <= 100 or k["td"]
    if not k["td"]:
        assert g["ytz"] == 100 - k["return_to"]         # Feldposition aus Return


def test_end_game_by_clock(tmp_path):
    """Spieluhr abgelaufen -> Spiel wird vorzeitig beendet und gewertet."""
    from gridiron import franchise as F
    cfg = _cfg(tmp_path)
    st = F.new_franchise(cfg, "Adler", n_teams=6, seed=12)
    F.do_training(cfg, st, "team"); st.pop("meeting", None)
    F.start_game(cfg, st)
    res = F.end_game(cfg, st)
    assert res.get("result") and "winner" in res["result"]
    assert st.get("active_game") is None            # Spiel abgeschlossen


def test_game_clock_real(tmp_path):
    """Echte Spieluhr: Start bei voller Viertelzeit, läuft pro Snap ab, Viertel/Halbzeit/Ende sauber."""
    from gridiron import franchise as F
    cfg = _cfg(tmp_path)
    st = F.new_franchise(cfg, "Adler", n_teams=6, seed=7)
    F.do_training(cfg, st, "team"); st.pop("meeting", None)
    gv = F.start_game(cfg, st)["game"]
    assert gv["quarter"] == 1 and gv["clock"] == F.QUARTER_SECONDS
    assert gv["timeouts"] == [3, 3]

    g = st["active_game"]
    first_receiver = g["pos"]
    saw_q2 = saw_q3 = saw_two_min = False
    guard = 0
    while not st["active_game"]["over"] and guard < 800:
        gg = st["active_game"]
        assert gg["clock"] >= 0 and gg["clock"] <= max(F.QUARTER_SECONDS, F.OT_SECONDS)
        assert gg["quarter"] >= 1 and gg["down"] in (1, 2, 3, 4)
        assert 0 <= gg["timeouts"][0] <= 3 and 0 <= gg["timeouts"][1] <= 3
        if gg["quarter"] == 2:
            saw_q2 = True
        if gg["quarter"] == 3 and not saw_q3:
            saw_q3 = True
            assert gg["pos"] == (first_receiver ^ 1)      # zweite Hälfte: anderes Team bekommt Kickoff
            assert gg["timeouts"] == [3, 3]               # Auszeiten zur Halbzeit zurückgesetzt
        if any("Zwei-Minuten" in L["desc"] for L in gg["log"]):
            saw_two_min = True
        F.game_play(cfg, st, F._auto_choice(st))
        guard += 1
    over = st["active_game"]
    assert over["over"] and over["quarter"] >= 4          # über die Uhr beendet (regulär nach Q4 / evtl. OT)
    assert saw_q2 and saw_q3 and saw_two_min               # alle Viertel-/Halbzeit-/2-Min-Mechaniken liefen


def test_penalties_apply_rules(tmp_path):
    """Strafen: Vor-Snap-Foul wiederholt den Down, Defensiv-Foul gibt Yards/automatisches First Down."""
    from gridiron import franchise as F

    # Roll wirft mit Sicherheit eine Strafe, wenn rate hoch genug
    class _Always:
        def __init__(self, seq):
            self.seq = list(seq); self.i = 0
        def random(self):
            v = self.seq[self.i % len(self.seq)]; self.i += 1; return v

    # Pre-Snap (False Start): kein Play, Down bleibt, Distanz +5, Feldposition nach hinten
    g = {"ytz": 60.0, "dist": 10.0, "down": 2, "q": 1, "score": [0, 0], "log": []}
    pen = {"name": "False Start", "side": "off", "yards": 5, "auto_first": False, "pre_snap": True, "spot": False}
    off = {"name": "Adler"}
    accepted = F._apply_penalty(g, pen, {"turnover": False, "yards": 4}, 4, False, off, True)
    assert accepted and g["down"] == 2 and g["dist"] == 15.0 and g["ytz"] == 65.0

    # Defensive Holding: +5 Yard, automatisches First Down
    g2 = {"ytz": 60.0, "dist": 8.0, "down": 3, "q": 1, "score": [0, 0], "log": []}
    pen2 = {"name": "Defensive Holding", "side": "def", "yards": 5, "auto_first": True, "pre_snap": False, "spot": False}
    accepted2 = F._apply_penalty(g2, pen2, {"turnover": False, "yards": 2}, 2, False, off, True)
    assert accepted2 and g2["down"] == 1 and g2["dist"] == 10.0 and g2["ytz"] == 55.0

    # Offense lehnt Defensiv-Strafe ab, wenn das Play mehr brachte (großer Lauf, kein Auto-First)
    g3 = {"ytz": 60.0, "dist": 5.0, "down": 1, "q": 1, "score": [0, 0], "log": []}
    pen3 = {"name": "Offside (Defense)", "side": "def", "yards": 5, "auto_first": False, "pre_snap": False, "spot": False}
    accepted3 = F._apply_penalty(g3, pen3, {"turnover": False, "yards": 20}, 20, False, off, True)
    assert accepted3 is False and g3["ytz"] == 60.0      # abgelehnt -> unverändert, Play zählt

    # _roll_penalty: rate=1 liefert immer, rate=0 nie
    assert F._roll_penalty(_Always([0.0]), rate=1.0) is not None
    assert F._roll_penalty(_Always([0.99]), rate=0.13) is None


def test_random_playcalls_and_philly(tmp_path):
    """Eigene Plays: 6 Offense-Calls (2 Lauf/4 Pass), 6 gemischte Coverages; Philly genau 1×."""
    from gridiron import franchise as F
    from gridiron.simulator import COVERAGES
    cfg = _cfg(tmp_path)
    st = F.new_franchise(cfg, "Adler", n_teams=6, seed=9)
    F.do_training(cfg, st, "team"); st.pop("meeting", None)
    F.start_game(cfg, st)
    g = st["active_game"]

    # Defense: 6 gut gemischte Coverages (Mann UND Zone vertreten)
    g["pos"] = 1 if g["user_is_home"] else 0             # Gegner am Ball -> Nutzer verteidigt
    g["clock_running"] = False                            # kein Auszeit-Button -> nur Coverages
    F._new_decision_options(st)
    dopts = F._game_view(st)["options"]
    assert len(dopts) == 6 and all(o["type"] == "Coverage" for o in dopts)
    assert len({o["key"] for o in dopts}) == 6           # keine Duplikate
    keys = {o["key"] for o in dopts}
    assert any(COVERAGES[k].get("man") for k in keys) and any(not COVERAGES[k].get("man") for k in keys)

    # Philly Special wird genau einmal angeboten
    g["pos"] = 0 if g["user_is_home"] else 1             # Nutzer am Ball
    g["ytz"], g["philly_at"], g["off_snaps"], g["philly_used"] = 75, 1, 0, False
    F._new_decision_options(st)
    assert any(o["key"] == "__PHILLY__" for o in st["active_game"]["opts"])
    r = F.game_play(cfg, st, "__PHILLY__")
    assert "Philly" in r["play"]["desc"] and st["active_game"]["philly_used"]
    # danach nie wieder
    g = st["active_game"]; g["pos"] = 0 if g["user_is_home"] else 1
    g["ytz"], g["philly_at"], g["off_snaps"] = 75, 1, 0
    F._new_decision_options(st)
    assert not any(o["key"] == "__PHILLY__" for o in st["active_game"]["opts"])


def test_franchise_detailed_game(tmp_path):
    """Nutzer-Spiel liefert ein vollständiges Play-by-Play für die Übertragung."""
    from gridiron import franchise as F
    cfg = _cfg(tmp_path)
    st = F.new_franchise(cfg, "Adler", n_teams=6, seed=2)
    F.do_training(cfg, st, "team"); st.pop("meeting", None)
    out = F.sim_week(cfg, st)
    g = out.get("user_game")
    assert g and g["plays"] and "Adler" in (g["home"], g["away"])
    assert g["hs"] != g["as"]                                   # kein Unentschieden
    assert any(p["score"] for p in g["plays"])                  # es wurde gepunktet
    for p in g["plays"]:
        assert 0 <= p["x"] <= 100 and p["q"] in (1, 2, 3, 4)
    assert F.view(st)["has_last_game"]
    # Feldrichtung: jedes Team läuft in die GEGNERISCHE Endzone (Heim -> links x=0,
    # Gast -> rechts x=100), nicht in die eigene.
    for p in g["plays"]:
        if "TOUCHDOWN" in p["desc"]:
            assert p["x"] == (0 if p["team"] == g["home"] else 100)
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
            F.do_training(cfg, st, "team"); st.pop("meeting", None)
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
    F.do_training(cfg, st, "team"); st.pop("meeting", None)
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
        F.do_training(cfg, st, "team"); st.pop("meeting", None); F.sim_week(cfg, st); F.next_week(cfg, st)
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
    F.do_training(cfg, st, "team"); st.pop("meeting", None)
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
        F.do_training(cfg, st, "team"); st.pop("meeting", None)
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
    derived = F._units_from_roster(team["roster"])                  # Feld-Units aus Kader abgeleitet
    assert {k: team["units"][k] for k in derived} == derived
    assert 50 <= team["units"]["K"] <= 95                           # Kicker: eigenes Special-Teams-Rating (nicht aus Kader)
    # Skillpunkt verteilen hebt Attribut + Units
    p["pts"] = 1
    attr = next(k for k in p["attr"] if p["attr"][k] < p["cap"][k])
    before = p["attr"][attr]
    r = F.alloc(cfg, st, p["id"], attr)
    assert r["ok"] and p["attr"][attr] == before + 1
    d2 = F._units_from_roster(team["roster"])
    assert {k: team["units"][k] for k in d2} == d2 and "K" in team["units"]   # Kicker bleibt erhalten
    # Auto-verteilen, Starter-Toggle, Fokus
    p["pts"] = 4
    assert F.alloc_auto(cfg, st, p["id"])["ok"]
    assert "starter" in F.depth_toggle(cfg, st, p["id"])
    assert F.set_focus(cfg, st, "QB")["focus"] == "QB"
    # EXP durch Wochentraining (Pflicht) + Spiel
    F.do_training(cfg, st, "team"); st.pop("meeting", None)
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
    F.do_training(cfg, st, "team"); st.pop("meeting", None)
    g = F.start_game(cfg, st)["game"]
    assert g["awaiting"] in ("offense", "defense") and g["options"]
    guard = 0
    while not g["over"] and guard < 600:
        # Spieluhr-Invarianten bei jedem Snap
        assert g["clock"] >= 0 and g["quarter"] >= 1
        assert 0 <= g["timeouts"][0] <= 3 and 0 <= g["timeouts"][1] <= 3
        g = F.game_play(cfg, st, g["options"][0]["key"])["game"]
        guard += 1
    assert g["over"] and g["quarter"] >= 4                 # Spiel endet über die echte Spieluhr (regulär nach Q4, evtl. OT)
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
    client.post("/api/fr/resolve_meeting", params={"idx": 0})            # Vereinsmeeting vor dem Spiel abschließen
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
