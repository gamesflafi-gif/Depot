"""Franchise-Modus: das Football-Manager-Spiel in Gridiron.

Baue dein Team (Einheiten verbessern, Playbook wählen), spiele eine Liga-Saison
gegen KI-Teams, gewinne die Playoffs und den Titel — über mehrere Saisons. Die
einzelnen Spiele werden nicht blind gewürfelt, sondern aus Team-Stärken **und**
der echten Matchup-Logik des Play-Simulators (Playbook-Konzept gegen
gegnerische Coverage) berechnet. Spielstand wird als JSON im Daten-Verzeichnis
gespeichert (eine Speicherdatei pro Server-Instanz).
"""
from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass

import numpy as np

from gridiron.config import Config
from gridiron.simulator import COVERAGES, PASS_CONCEPTS, RUN_CONCEPTS, play_outcome, simulate

# Einheiten (Roster-Gruppen) und ihre Gewichte für Offense-/Defense-Stärke.
OFF_UNITS = {"QB": 0.34, "OL": 0.30, "WR": 0.20, "RB": 0.16}
DEF_UNITS = {"DL": 0.40, "DB": 0.32, "LB": 0.28}
UNIT_LABELS = {"QB": "Quarterback", "OL": "O-Line", "WR": "Receiver", "RB": "Running Back",
               "DL": "D-Line", "LB": "Linebacker", "DB": "Secondary"}
ALL_UNITS = list(OFF_UNITS) + list(DEF_UNITS)

_AI_NAMES = ["Hawks", "Bisons", "Storm", "Vipers", "Titans", "Comets", "Wolves",
             "Sharks", "Raptors", "Outlaws", "Sentinels", "Blizzard"]
_AI_CONCEPTS = list(PASS_CONCEPTS) + list(RUN_CONCEPTS)
_AI_COVERS = list(COVERAGES)
# KI-Teams mit Identität: Name, Kürzel, Primär-/Sekundärfarbe.
TEAM_CATALOG = [
    ("Hawks", "HAW", "#2f81f7", "#0b2545"), ("Bisons", "BIS", "#b4530a", "#3a1d0a"),
    ("Storm", "STM", "#6a4ec2", "#241a45"), ("Vipers", "VIP", "#1f9e5a", "#0c2e1c"),
    ("Titans", "TTN", "#2b6cb0", "#10233a"), ("Comets", "CMT", "#d2a106", "#3a2f06"),
    ("Wolves", "WLV", "#7c8896", "#1c2127"), ("Sharks", "SHK", "#0ea5b7", "#062b30"),
    ("Raptors", "RAP", "#c1121f", "#3a0a0e"), ("Outlaws", "OUT", "#9aa02b", "#2b2d0a"),
    ("Sentinels", "SEN", "#3d5afe", "#101a45"), ("Blizzard", "BLZ", "#4aa3df", "#0c2738"),
]
# Auswählbare Farben fürs eigene Team.
USER_COLORS = ["#16c784", "#e5484d", "#3d5afe", "#f5a524", "#9750dd",
               "#0ea5b7", "#e0457b", "#d29922"]
_NEUTRAL = {"down": 1, "ydstogo": 10, "yardline_100": 60, "personnel": "11"}
_EPA_CACHE: dict[tuple, float] = {}


def _abbr(name: str) -> str:
    p = name.split()
    if len(p) >= 2:
        return (p[0][0] + p[1][:2]).upper()
    return name[:3].upper()


def _epa(concept: str, coverage: str) -> float:
    key = (concept, coverage)
    if key not in _EPA_CACHE:
        _EPA_CACHE[key] = simulate(None, concept, coverage, _NEUTRAL, n=1200, seed=11).expected_epa
    return _EPA_CACHE[key]


# Team-Schemata (wirken übers ganze Spiel, nicht ein einzelner Spielzug).
OFF_SCHEMES = {
    "Vertikal": ["Four Verts", "Y-Cross", "Dagger", "Flood"],
    "Quick Game": ["Slant-Flat", "Mesh", "Stick", "Drive", "Spacing"],
    "Ausgeglichen": ["Smash", "Stick", "Inside Zone", "Y-Cross", "Slant-Flat"],
    "Lauflastig": ["Inside Zone", "Outside Zone", "Power", "Counter", "Toss"],
}
DEF_SCHEMES = {
    "Aggressiv (Blitz)": ["Cover 0", "Cover 1"],
    "Ausgeglichen": ["Cover 1", "Cover 3", "Cover 2"],
    "Zone": ["Cover 2", "Cover 3", "Cover 4", "Tampa 2"],
    "Quarters": ["Cover 4", "Cover 6", "Cover 2"],
}
_PASS_BIAS = {"Vertikal": 0.66, "Quick Game": 0.62, "Ausgeglichen": 0.56, "Lauflastig": 0.42}
_SCHEME_CACHE: dict[tuple, float] = {}


def _scheme_epa(off_scheme: str, def_scheme: str) -> float:
    """Mittleres EPA des Offense-Schemas gegen das Defense-Schema (Spiel-Ebene)."""
    key = (off_scheme, def_scheme)
    if key not in _SCHEME_CACHE:
        cs = OFF_SCHEMES.get(off_scheme) or list(PASS_CONCEPTS)
        cv = DEF_SCHEMES.get(def_scheme) or list(COVERAGES)
        vals = [_epa(c, v) for c in cs for v in cv]
        _SCHEME_CACHE[key] = sum(vals) / len(vals)
    return _SCHEME_CACHE[key]


def _rating(units: dict, weights: dict) -> int:
    return round(sum(units[u] * w for u, w in weights.items()))


def offense(team: dict) -> int:
    s = team.get("staff", {})
    b = _rating(team["units"], OFF_UNITS)
    return min(99, b + round((s.get("OC", 60) - 60) * 0.30) + round((s.get("HC", 60) - 60) * 0.12))


def defense(team: dict) -> int:
    s = team.get("staff", {})
    b = _rating(team["units"], DEF_UNITS)
    return min(99, b + round((s.get("DC", 60) - 60) * 0.30) + round((s.get("HC", 60) - 60) * 0.12))


def overall(team: dict) -> int:
    return round((offense(team) + defense(team)) / 2)


STAFF_LABELS = {"HC": "Head Coach", "OC": "Offensive Coordinator", "DC": "Defensive Coordinator"}


# --------------------------------------------------------------------------- #
# Persistenz
# --------------------------------------------------------------------------- #
def _save_path(cfg: Config) -> str:
    cfg.ensure_dirs()
    return os.path.join(cfg.data_dir, "franchise.json")


def exists(cfg: Config) -> bool:
    return os.path.exists(_save_path(cfg))


def load(cfg: Config) -> dict | None:
    p = _save_path(cfg)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def save(cfg: Config, state: dict) -> None:
    with open(_save_path(cfg), "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=1)


def delete(cfg: Config) -> None:
    p = _save_path(cfg)
    if os.path.exists(p):
        os.remove(p)


# --------------------------------------------------------------------------- #
# Aufbau einer neuen Franchise
# --------------------------------------------------------------------------- #
def _round_robin(n: int) -> list[list[tuple[int, int]]]:
    """Spielplan (Kreismethode), n gerade. Liefert n-1 Wochen."""
    teams = list(range(n))
    weeks = []
    for _ in range(n - 1):
        pairs = [(teams[i], teams[n - 1 - i]) for i in range(n // 2)]
        weeks.append(pairs)
        teams = [teams[0]] + [teams[-1]] + teams[1:-1]   # rotieren, 0 fix
    return weeks


def _new_team(name: str, abbr: str, color: str, color2: str, base: int,
              rng: random.Random, user: bool = False) -> dict:
    units = {u: max(50, min(95, base + rng.randint(-6, 6))) for u in ALL_UNITS}
    sb = base if user else base
    staff = {k: max(50, min(90, sb - 8 + rng.randint(-4, 8))) for k in ("HC", "OC", "DC")}
    return {
        "name": name, "abbr": abbr, "color": color, "color2": color2, "user": user,
        "units": units, "staff": staff, "stadium": 1,
        "off_scheme": "Ausgeglichen" if user else rng.choice(list(OFF_SCHEMES)),
        "def_scheme": "Ausgeglichen" if user else rng.choice(list(DEF_SCHEMES)),
        "w": 0, "l": 0, "t": 0, "pf": 0, "pa": 0,
    }


def new_franchise(cfg: Config, team_name: str, n_teams: int = 8,
                  difficulty: str = "normal", color: str | None = None,
                  seed: int | None = None) -> dict:
    n_teams = max(4, n_teams - (n_teams % 2))             # gerade, >=4
    rng = random.Random(seed)
    user_base = {"leicht": 76, "normal": 70, "schwer": 66}.get(difficulty, 70)
    nm = team_name.strip()[:24] or "Mein Team"
    ucolor = color if color in USER_COLORS else USER_COLORS[0]
    teams = [_new_team(nm, _abbr(nm), ucolor, "#0c1a12", user_base, rng, user=True)]
    for cname, cabbr, c1, c2 in rng.sample(TEAM_CATALOG, n_teams - 1):
        teams.append(_new_team(cname, cabbr, c1, c2, rng.randint(64, 80), rng))
    state = {
        "team_name": teams[0]["name"], "season": 1, "week": 0,
        "phase": "regular", "budget": 60, "difficulty": difficulty,
        "teams": teams, "schedule": _round_robin(n_teams),
        "results": [], "log": [], "history": [], "playoff": None,
        "champion": None,
    }
    save(cfg, state)
    return state


# --------------------------------------------------------------------------- #
# Spiel-Simulation
# --------------------------------------------------------------------------- #
def _team_epa(off_team: dict, def_team: dict) -> float:
    return _scheme_epa(off_team.get("off_scheme", "Ausgeglichen"),
                       def_team.get("def_scheme", "Ausgeglichen"))


def _expected_points(off_team: dict, def_team: dict, home_adv: float) -> float:
    edge = 0.42 * (offense(off_team) - defense(def_team))
    matchup = 13.0 * _team_epa(off_team, def_team)
    return max(3.0, 21.0 + edge + matchup + home_adv)


def simulate_game(home: dict, away: dict, rng: random.Random) -> dict:
    eh = _expected_points(home, away, +2.0)
    ea = _expected_points(away, home, 0.0)
    sh = max(0, round(rng.gauss(eh, 8)))
    sa = max(0, round(rng.gauss(ea, 8)))
    while sh == sa:                                       # Overtime bis Entscheidung
        if rng.random() < eh / (eh + ea):
            sh += rng.choice([3, 6, 7])
        else:
            sa += rng.choice([3, 6, 7])
    return {"home": home["name"], "away": away["name"], "hs": sh, "as": sa,
            "winner": home["name"] if sh > sa else away["name"]}


_PASS_DESC = ["Pass über die Mitte", "Pass nach außen", "tiefer Wurf",
              "Quick-Pass", "Pass in die Flat", "Pass über die Naht"]
_RUN_DESC = ["Lauf innen", "Lauf nach außen", "Draw", "Cutback", "Power-Lauf"]


def simulate_game_detailed(home: dict, away: dict, rng: random.Random) -> dict:
    """Spiel als Play-by-Play (für die visuelle Übertragung). Score bleibt an
    Team-Stärke + Matchup gekoppelt, damit es zur Liga passt."""
    score = [0, 0]                                       # [home, away]
    plays: list[dict] = []
    teams = [home, away]
    pos = 0 if rng.random() < 0.5 else 1
    for drive in range(22):
        off, deff = teams[pos], teams[1 - pos]
        attack_right = (pos == 0)
        absx = 25.0 if attack_right else 75.0           # absolute Feldposition 0..100
        ytz, down, dist = 75.0, 1, 10                   # bis Endzone, Down, Distanz
        q = min(4, drive // 6 + 1)
        mean = max(2.0, min(8.5, 5.0 + 0.11 * (offense(off) - defense(deff))
                            + 1.7 * _team_epa(off, deff)))
        pass_bias = _PASS_BIAS.get(off.get("off_scheme", "Ausgeglichen"), 0.56)
        for _ in range(14):
            is_pass = rng.random() < pass_bias
            # Turnover?
            if rng.random() < 0.028:
                desc = "Interception!" if is_pass else "Fumble, Ball verloren!"
                plays.append(_pl(q, off["name"], desc, absx, score, False))
                break
            gain = round(rng.gauss(mean if not is_pass else mean + 0.6, 6))
            ytz -= gain
            absx = min(100, max(0, absx + (gain if attack_right else -gain)))
            if ytz <= 0:                                # Touchdown
                score[pos] += 7
                plays.append(_pl(q, off["name"], "TOUCHDOWN! " + off["name"],
                                 100 if attack_right else 0, score, True))
                break
            dist -= gain
            label = (rng.choice(_PASS_DESC) if is_pass else rng.choice(_RUN_DESC))
            label += f", {'+' if gain >= 0 else ''}{gain}"
            if dist <= 0:
                down, dist = 1, 10
                label += " — First Down"
            else:
                down += 1
            if down > 4:
                if ytz <= 22 and rng.random() < 0.82:   # Field-Goal-Versuch
                    score[pos] += 3
                    plays.append(_pl(q, off["name"], "Field Goal gut (3)", absx, score, True))
                else:
                    plays.append(_pl(q, off["name"], "Punt" if ytz > 22 else "Field Goal daneben", absx, score, False))
                break
            plays.append(_pl(q, off["name"], label, absx, score, False))
        pos ^= 1
    sh, sa = score[0], score[1]
    while sh == sa:
        if rng.random() < 0.5:
            sh += 3
        else:
            sa += 3
    return {"home": home["name"], "away": away["name"], "hs": sh, "as": sa,
            "winner": home["name"] if sh > sa else away["name"], "plays": plays,
            "habbr": home.get("abbr", "HOM"), "aabbr": away.get("abbr", "AWY"),
            "hcolor": home.get("color", "#16c784"), "acolor": away.get("color", "#ef5350")}


def _pl(q: int, team: str, desc: str, absx: float, score: list[int], scored: bool) -> dict:
    return {"q": q, "team": team, "desc": desc, "x": round(absx, 1),
            "hs": score[0], "as": score[1], "score": scored}


def _decide(home: dict, away: dict, rng: random.Random):
    """Spiel entscheiden. Ist ein Nutzer-Team beteiligt -> Play-by-Play."""
    if home["user"] or away["user"]:
        g = simulate_game_detailed(home, away, rng)
        return g, g
    return simulate_game(home, away, rng), None


def _apply(home: dict, away: dict, r: dict) -> None:
    home["pf"] += r["hs"]; home["pa"] += r["as"]
    away["pf"] += r["as"]; away["pa"] += r["hs"]
    if r["hs"] > r["as"]:
        home["w"] += 1; away["l"] += 1
    else:
        away["w"] += 1; home["l"] += 1


def _idx(teams: list[dict], name: str) -> int:
    return next(i for i, t in enumerate(teams) if t["name"] == name)


# --------------------------------------------------------------------------- #
# Woche / Saison fortschreiben
# --------------------------------------------------------------------------- #
def sim_week(cfg: Config, state: dict, user_result: dict | None = None) -> dict:
    """Spielt die aktuelle Woche. user_result: selbst gespieltes Nutzer-Spiel
    (wird gewertet statt simuliert)."""
    if state["phase"] == "done":
        return {"error": "Saison beendet — starte eine neue Saison."}
    rng = random.Random()
    teams = state["teams"]

    user_game = None
    if state["phase"] == "regular":
        wk = state["week"]
        pairs = state["schedule"][wk]
        games = []
        for hi, ai in pairs:
            if user_result and (hi == 0 or ai == 0):
                r = user_result
                _apply(teams[hi], teams[ai], r)
                games.append(_strip(r))
            else:
                r, pbp = _decide(teams[hi], teams[ai], rng)
                _apply(teams[hi], teams[ai], r)
                games.append(_strip(r))
                if pbp:
                    user_game = pbp
        state["results"].append({"week": wk + 1, "games": games})
        _earn(state, games)
        state["week"] += 1
        if state["week"] >= len(state["schedule"]):
            _start_playoffs(state)
        out = {"phase": "regular", "week": wk + 1, "games": games}
    else:
        out = _sim_playoff_round(state, rng, user_result)
        user_game = out.pop("_user_game", None)

    if user_game:
        state["last_user_game"] = user_game
        out["user_game"] = user_game
    save(cfg, state)
    return out


def _strip(r: dict) -> dict:
    """Spielergebnis ohne das große Play-by-Play (für die Ergebnisliste)."""
    return {k: r[k] for k in ("home", "away", "hs", "as", "winner")}


def _earn(state: dict, games: list[dict]) -> None:
    team = state["teams"][0]
    user = team["name"]
    g = next((x for x in games if user in (x["home"], x["away"])), None)
    income = 6 + 2 * (team.get("stadium", 1) - 1)            # Stadion bringt Mehreinnahmen
    if g:
        income += 10 if g["winner"] == user else 3
    state["budget"] += income


def standings(state: dict) -> list[dict]:
    rows = [{"name": t["name"], "abbr": t.get("abbr", "?"), "color": t.get("color", "#16c784"),
             "user": t["user"], "w": t["w"], "l": t["l"],
             "pf": t["pf"], "pa": t["pa"], "diff": t["pf"] - t["pa"],
             "ovr": overall(t)} for t in state["teams"]]
    rows.sort(key=lambda r: (r["w"], r["diff"], r["pf"]), reverse=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def _start_playoffs(state: dict) -> None:
    seeds = [r["name"] for r in standings(state)][:4]
    state["phase"] = "playoffs"
    state["playoff"] = {"round": "Halbfinale", "seeds": seeds,
                        "pairs": [(seeds[0], seeds[3]), (seeds[1], seeds[2])],
                        "final": None}


def _sim_playoff_round(state: dict, rng: random.Random, user_result: dict | None = None) -> dict:
    teams = state["teams"]
    po = state["playoff"]
    user = teams[0]["name"]
    games, user_game = [], None
    for hn, an in po["pairs"]:
        if user_result and user in (hn, an):
            games.append(_strip(user_result))
            continue
        r, pbp = _decide(teams[_idx(teams, hn)], teams[_idx(teams, an)], rng)
        games.append(_strip(r))
        if pbp:
            user_game = pbp
    if po["round"] == "Halbfinale":
        winners = [g["winner"] for g in games]
        po["round"] = "Finale"
        po["pairs"] = [(winners[0], winners[1])]
        state["results"].append({"week": "Halbfinale", "games": games})
        return {"phase": "playoffs", "round": "Halbfinale", "games": games, "_user_game": user_game}
    # Finale
    champ = games[0]["winner"]
    state["champion"] = champ
    state["phase"] = "done"
    state["results"].append({"week": "Finale", "games": games})
    state["history"].append({"season": state["season"], "champion": champ})
    return {"phase": "done", "round": "Finale", "games": games, "champion": champ, "_user_game": user_game}


def new_season(cfg: Config, state: dict) -> dict:
    """Nächste Saison: Bilanzen zurücksetzen, KI driftet leicht, neuer Spielplan."""
    rng = random.Random()
    for t in state["teams"]:
        t["w"] = t["l"] = t["t"] = t["pf"] = t["pa"] = 0
        if not t["user"]:                                # KI entwickelt sich
            for u in ALL_UNITS:
                t["units"][u] = max(50, min(95, t["units"][u] + rng.randint(-3, 3)))
            if rng.random() < 0.4:
                t["off_scheme"] = rng.choice(list(OFF_SCHEMES))
            if rng.random() < 0.4:
                t["def_scheme"] = rng.choice(list(DEF_SCHEMES))
    state["season"] += 1
    state["week"] = 0
    state["phase"] = "regular"
    state["playoff"] = None
    state["champion"] = None
    state["results"] = []
    state["last_user_game"] = None
    state["active_game"] = None
    state["schedule"] = _round_robin(len(state["teams"]))
    state["budget"] += 20                                 # Saisonbudget
    save(cfg, state)
    return state


# --------------------------------------------------------------------------- #
# Team-Aufbau (Manager)
# --------------------------------------------------------------------------- #
def upgrade_cost(level: int) -> int:
    return max(5, round((level - 50) * 0.6) + 5)


def upgrade_unit(cfg: Config, state: dict, key: str) -> dict:
    """Verbessert Einheit (Kader), Trainerstab (HC/OC/DC) oder Stadion."""
    team = state["teams"][0]
    if key in ALL_UNITS:
        store, cap, label = team["units"], 95, UNIT_LABELS[key]
    elif key in STAFF_LABELS:
        team.setdefault("staff", {"HC": 60, "OC": 60, "DC": 60})
        store, cap, label = team["staff"], 95, STAFF_LABELS[key]
    elif key == "stadium":
        lvl = team.get("stadium", 1)
        if lvl >= 5:
            return {"error": "Stadion ist bereits auf Maximum (Stufe 5)."}
        cost = 18 + (lvl - 1) * 14
        if state["budget"] < cost:
            return {"error": f"Budget zu niedrig (brauchst {cost}, hast {state['budget']})."}
        team["stadium"] = lvl + 1
        state["budget"] -= cost
        save(cfg, state)
        return {"ok": True, "unit": "stadium", "level": team["stadium"], "cost": cost,
                "budget": state["budget"]}
    else:
        return {"error": "Unbekannte Verbesserung."}
    lvl = store[key]
    if lvl >= cap:
        return {"error": f"{label} ist bereits auf Maximum ({cap})."}
    cost = upgrade_cost(lvl)
    if state["budget"] < cost:
        return {"error": f"Budget zu niedrig (brauchst {cost}, hast {state['budget']})."}
    store[key] = min(cap, lvl + 2)
    state["budget"] -= cost
    save(cfg, state)
    return {"ok": True, "unit": key, "level": store[key], "cost": cost, "budget": state["budget"]}


def set_scheme(cfg: Config, state: dict, off_scheme: str | None, def_scheme: str | None) -> dict:
    team = state["teams"][0]
    if off_scheme:
        if off_scheme not in OFF_SCHEMES:
            return {"error": "Unbekanntes Offense-Schema."}
        team["off_scheme"] = off_scheme
    if def_scheme:
        if def_scheme not in DEF_SCHEMES:
            return {"error": "Unbekanntes Defense-Schema."}
        team["def_scheme"] = def_scheme
    save(cfg, state)
    return {"ok": True, "off_scheme": team["off_scheme"], "def_scheme": team["def_scheme"]}


# --------------------------------------------------------------------------- #
# Zustand fürs Frontend
# --------------------------------------------------------------------------- #
def _next_opponent(state: dict) -> dict | None:
    if state["phase"] == "regular" and state["week"] < len(state["schedule"]):
        user_i = 0
        for hi, ai in state["schedule"][state["week"]]:
            if hi == user_i or ai == user_i:
                opp = state["teams"][ai if hi == user_i else hi]
                return {"name": opp["name"], "abbr": opp.get("abbr", "?"),
                        "color": opp.get("color", "#ef5350"), "home": hi == user_i,
                        "ovr": overall(opp), "off": offense(opp), "def": defense(opp),
                        "off_scheme": opp.get("off_scheme", "?"),
                        "def_scheme": opp.get("def_scheme", "?")}
    return None


def view(state: dict) -> dict:
    team = state["teams"][0]
    last = state["results"][-1] if state["results"] else None
    return {
        "team_name": state["team_name"], "season": state["season"],
        "abbr": team.get("abbr", "?"), "color": team.get("color", "#16c784"),
        "week": state["week"], "phase": state["phase"], "budget": state["budget"],
        "difficulty": state["difficulty"], "champion": state["champion"],
        "record": {"w": team["w"], "l": team["l"]},
        "ratings": {"off": offense(team), "def": defense(team), "ovr": overall(team)},
        "units": [{"key": u, "label": UNIT_LABELS[u], "level": team["units"][u],
                   "cost": upgrade_cost(team["units"][u]), "side": "Offense" if u in OFF_UNITS else "Defense"}
                  for u in ALL_UNITS],
        "staff": [{"key": k, "label": STAFF_LABELS[k], "level": team.get("staff", {}).get(k, 60),
                   "cost": upgrade_cost(team.get("staff", {}).get(k, 60))} for k in ("HC", "OC", "DC")],
        "stadium": {"level": team.get("stadium", 1),
                    "cost": 18 + (team.get("stadium", 1) - 1) * 14,
                    "income": 6 + 2 * (team.get("stadium", 1) - 1)},
        "active_game": bool(state.get("active_game")),
        "scheme": {"off": team.get("off_scheme", "Ausgeglichen"),
                   "def": team.get("def_scheme", "Ausgeglichen")},
        "off_schemes": {k: OFF_SCHEMES[k] for k in OFF_SCHEMES},
        "def_schemes": {k: DEF_SCHEMES[k] for k in DEF_SCHEMES},
        "next": _next_opponent(state),
        "standings": standings(state),
        "playoff": state["playoff"],
        "last_result": last,
        "n_weeks": len(state["schedule"]),
        "history": state["history"],
        "has_last_game": bool(state.get("last_user_game")),
    }


# --------------------------------------------------------------------------- #
# Interaktiver Spielmodus (selbst Plays callen)
# --------------------------------------------------------------------------- #
MAX_DRIVES = 12
_RNG = np.random.default_rng()


def _user_pair(state: dict):
    """(home_idx, away_idx) des aktuellen Nutzer-Spiels oder None."""
    teams = state["teams"]
    if state["phase"] == "regular" and state["week"] < len(state["schedule"]):
        for hi, ai in state["schedule"][state["week"]]:
            if hi == 0 or ai == 0:
                return hi, ai
    elif state["phase"] == "playoffs" and state.get("playoff"):
        user = teams[0]["name"]
        for hn, an in state["playoff"]["pairs"]:
            if user in (hn, an):
                return _idx(teams, hn), _idx(teams, an)
    return None


def start_game(cfg: Config, state: dict) -> dict:
    if state.get("active_game"):
        return {"ok": True, "game": _game_view(state)}
    pair = _user_pair(state)
    if not pair:
        return {"error": "Diese Woche kein Nutzer-Spiel."}
    hi, ai = pair
    teams = state["teams"]
    pos = 0 if random.random() < 0.5 else 1
    g = {
        "hi": hi, "ai": ai, "user_is_home": hi == 0,
        "score": [0, 0], "pos": pos, "drive": 0, "q": 1,
        "down": 1, "dist": 10, "ytz": 75.0,
        "absx": 25.0 if pos == 0 else 75.0,
        "log": [], "over": False,
    }
    state["active_game"] = g
    save(cfg, state)
    return {"ok": True, "game": _game_view(state)}


def _scheme_pick(team: dict, off: bool) -> str:
    pool = OFF_SCHEMES.get(team.get("off_scheme", "Ausgeglichen"), list(PASS_CONCEPTS)) if off \
        else DEF_SCHEMES.get(team.get("def_scheme", "Ausgeglichen"), list(COVERAGES))
    return random.choice(pool)


def game_play(cfg: Config, state: dict, choice: str) -> dict:
    g = state.get("active_game")
    if not g or g["over"]:
        return {"error": "Kein laufendes Spiel."}
    teams = state["teams"]
    off_i = g["hi"] if g["pos"] == 0 else g["ai"]
    def_i = g["ai"] if g["pos"] == 0 else g["hi"]
    off, deff = teams[off_i], teams[def_i]
    user_has_ball = (g["pos"] == 0) == g["user_is_home"]

    if user_has_ball:
        if choice not in PASS_CONCEPTS and choice not in RUN_CONCEPTS:
            return {"error": "Unbekanntes Konzept."}
        concept, coverage = choice, _scheme_pick(deff, off=False)
    else:
        if choice not in COVERAGES:
            return {"error": "Unbekannte Coverage."}
        coverage, concept = choice, _scheme_pick(off, off=True)

    o = play_outcome(concept, coverage,
                     {"yardline_100": g["ytz"], "down": g["down"], "ydstogo": g["dist"]}, _RNG)
    yards = max(-12, min(o["yards"], int(g["ytz"])))
    attack_right = (g["pos"] == 0)
    g["absx"] = max(0.0, min(100.0, g["absx"] + (yards if attack_right else -yards)))
    label = _play_label(concept, o, yards)
    scored = False
    switch = True

    if o["turnover"]:
        pass                                              # Ballverlust -> anderes Team
    elif g["ytz"] - yards <= 0:
        g["score"][g["pos"]] += 7
        g["absx"] = 100.0 if attack_right else 0.0
        label = "TOUCHDOWN! " + off["name"]
        scored = True
    else:
        g["ytz"] -= yards
        g["dist"] -= yards
        if g["dist"] <= 0:
            g["down"], g["dist"] = 1, 10
            label += " — First Down"
            switch = False
        else:
            g["down"] += 1
            if g["down"] > 4:
                if g["ytz"] <= 22 and random.random() < 0.82:
                    g["score"][g["pos"]] += 3
                    label = "Field Goal gut (3)"
                    scored = True
                else:
                    label = "4th Down vergeben" if g["ytz"] > 22 else "Field Goal daneben"
            else:
                switch = False

    g["log"].insert(0, {"q": g["q"], "team": off["name"], "desc": label,
                        "hs": g["score"][0], "as_": g["score"][1],
                        "off": user_has_ball, "yards": yards})

    if switch:
        g["pos"] ^= 1
        g["drive"] += 1
        g["q"] = min(4, g["drive"] // (MAX_DRIVES // 4 or 1) + 1)
        g["down"], g["dist"], g["ytz"] = 1, 10, 75.0
        g["absx"] = 25.0 if g["pos"] == 0 else 75.0
        if g["drive"] >= MAX_DRIVES:
            g["over"] = True

    save(cfg, state)
    return {"ok": True, "play": {"desc": label, "yards": yards, "scored": scored,
                                 "kind": o["kind"]}, "game": _game_view(state)}


def _play_label(concept: str, o: dict, yards: int) -> str:
    if o["kind"] == "sack":
        return f"Sack! {yards}"
    if o["kind"] == "int":
        return "Interception!"
    if o["kind"] == "incomplete":
        return "Pass unvollständig"
    if o["kind"] == "complete":
        return f"{concept}: Fang über {yards}" if not o["turnover"] else "Fumble nach Fang!"
    return f"{concept}: Lauf {'+' if yards >= 0 else ''}{yards}" if not o["turnover"] else "Fumble!"


def finish_game(cfg: Config, state: dict) -> dict:
    """Wertet das selbst gespielte Spiel und schließt die Woche ab."""
    g = state.get("active_game")
    if not g:
        return {"error": "Kein Spiel aktiv."}
    if not g["over"]:
        return {"error": "Spiel läuft noch."}
    teams = state["teams"]
    home, away = teams[g["hi"]], teams[g["ai"]]
    hs, as_ = g["score"][0], g["score"][1]
    while hs == as_:
        hs += 3 if random.random() < 0.5 else 0
        as_ += 3 if hs == as_ else 0
    result = {"home": home["name"], "away": away["name"], "hs": hs, "as": as_,
              "winner": home["name"] if hs > as_ else away["name"]}
    state["active_game"] = None
    out = sim_week(cfg, state, user_result=result)
    return {"ok": True, "result": result, "advance": out, "view": view(state)}


def abort_game(cfg: Config, state: dict) -> dict:
    state["active_game"] = None
    save(cfg, state)
    return {"ok": True}


def _game_view(state: dict) -> dict:
    g = state["active_game"]
    teams = state["teams"]
    home, away = teams[g["hi"]], teams[g["ai"]]
    off_i = g["hi"] if g["pos"] == 0 else g["ai"]
    user_has_ball = (g["pos"] == 0) == g["user_is_home"]
    if user_has_ball:
        opts = [{"key": k, "label": (PASS_CONCEPTS.get(k) or RUN_CONCEPTS[k])["label"],
                 "type": "Pass" if k in PASS_CONCEPTS else "Lauf"}
                for k in OFF_SCHEMES.get(teams[0].get("off_scheme", "Ausgeglichen"), [])]
    else:
        opts = [{"key": k, "label": COVERAGES[k]["label"], "type": "Coverage"} for k in COVERAGES]
    return {
        "home": home["name"], "away": away["name"],
        "habbr": home.get("abbr", "HOM"), "aabbr": away.get("abbr", "AWY"),
        "hcolor": home.get("color", "#16c784"), "acolor": away.get("color", "#ef5350"),
        "hs": g["score"][0], "as": g["score"][1], "q": g["q"],
        "down": g["down"], "dist": g["dist"], "ytz": round(g["ytz"]), "absx": round(g["absx"], 1),
        "drive": g["drive"], "max_drives": MAX_DRIVES, "over": g["over"],
        "possession": teams[off_i]["name"], "user_offense": user_has_ball,
        "awaiting": "offense" if user_has_ball else "defense",
        "options": opts, "log": g["log"][:12],
        "user_is_home": g["user_is_home"],
    }
