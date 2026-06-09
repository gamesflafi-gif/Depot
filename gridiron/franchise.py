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

from gridiron.config import Config
from gridiron.simulator import COVERAGES, PASS_CONCEPTS, RUN_CONCEPTS, simulate

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
_NEUTRAL = {"down": 1, "ydstogo": 10, "yardline_100": 60, "personnel": "11"}
_EPA_CACHE: dict[tuple, float] = {}


def _epa(concept: str, coverage: str) -> float:
    key = (concept, coverage)
    if key not in _EPA_CACHE:
        _EPA_CACHE[key] = simulate(None, concept, coverage, _NEUTRAL, n=1200, seed=11).expected_epa
    return _EPA_CACHE[key]


def _rating(units: dict, weights: dict) -> int:
    return round(sum(units[u] * w for u, w in weights.items()))


def offense(team: dict) -> int:
    return _rating(team["units"], OFF_UNITS)


def defense(team: dict) -> int:
    return _rating(team["units"], DEF_UNITS)


def overall(team: dict) -> int:
    return round((offense(team) + defense(team)) / 2)


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


def _new_team(name: str, base: int, rng: random.Random, user: bool = False) -> dict:
    units = {u: max(50, min(95, base + rng.randint(-6, 6))) for u in ALL_UNITS}
    return {
        "name": name, "user": user, "units": units,
        "concept": "Inside Zone" if user else rng.choice(_AI_CONCEPTS),
        "coverage": "Cover 3" if user else rng.choice(_AI_COVERS),
        "w": 0, "l": 0, "t": 0, "pf": 0, "pa": 0,
    }


def new_franchise(cfg: Config, team_name: str, n_teams: int = 8,
                  difficulty: str = "normal", seed: int | None = None) -> dict:
    n_teams = max(4, n_teams - (n_teams % 2))             # gerade, >=4
    rng = random.Random(seed)
    user_base = {"leicht": 76, "normal": 70, "schwer": 66}.get(difficulty, 70)
    teams = [_new_team(team_name.strip()[:24] or "Mein Team", user_base, rng, user=True)]
    names = rng.sample(_AI_NAMES, n_teams - 1)
    for nm in names:
        teams.append(_new_team(nm, rng.randint(64, 80), rng))
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
def _expected_points(off_team: dict, def_team: dict, home_adv: float) -> float:
    edge = 0.42 * (offense(off_team) - defense(def_team))
    matchup = 11.0 * _epa(off_team["concept"], def_team["coverage"])
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
                            + 1.5 * _epa(off["concept"], deff["coverage"])))
        for _ in range(14):
            is_pass = rng.random() < 0.57
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
            "winner": home["name"] if sh > sa else away["name"], "plays": plays}


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
def sim_week(cfg: Config, state: dict) -> dict:
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
        out = _sim_playoff_round(state, rng)
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
    user = state["teams"][0]["name"]
    g = next((x for x in games if user in (x["home"], x["away"])), None)
    income = 6
    if g:
        income += 10 if g["winner"] == user else 3
    state["budget"] += income


def standings(state: dict) -> list[dict]:
    rows = [{"name": t["name"], "user": t["user"], "w": t["w"], "l": t["l"],
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


def _sim_playoff_round(state: dict, rng: random.Random) -> dict:
    teams = state["teams"]
    po = state["playoff"]
    games, user_game = [], None
    for hn, an in po["pairs"]:
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
            t["concept"] = rng.choice(_AI_CONCEPTS)
            t["coverage"] = rng.choice(_AI_COVERS)
    state["season"] += 1
    state["week"] = 0
    state["phase"] = "regular"
    state["playoff"] = None
    state["champion"] = None
    state["results"] = []
    state["last_user_game"] = None
    state["schedule"] = _round_robin(len(state["teams"]))
    state["budget"] += 20                                 # Saisonbudget
    save(cfg, state)
    return state


# --------------------------------------------------------------------------- #
# Team-Aufbau (Manager)
# --------------------------------------------------------------------------- #
def upgrade_cost(level: int) -> int:
    return max(5, round((level - 50) * 0.6) + 5)


def upgrade_unit(cfg: Config, state: dict, unit: str) -> dict:
    if unit not in ALL_UNITS:
        return {"error": "Unbekannte Einheit."}
    team = state["teams"][0]
    lvl = team["units"][unit]
    if lvl >= 95:
        return {"error": f"{UNIT_LABELS[unit]} ist bereits auf Maximum (95)."}
    cost = upgrade_cost(lvl)
    if state["budget"] < cost:
        return {"error": f"Budget zu niedrig (brauchst {cost}, hast {state['budget']})."}
    team["units"][unit] = min(95, lvl + 2)
    state["budget"] -= cost
    save(cfg, state)
    return {"ok": True, "unit": unit, "level": team["units"][unit], "cost": cost,
            "budget": state["budget"]}


def set_playbook(cfg: Config, state: dict, concept: str | None, coverage: str | None) -> dict:
    team = state["teams"][0]
    if concept is not None:
        if concept not in _AI_CONCEPTS:
            return {"error": "Unbekanntes Konzept."}
        team["concept"] = concept
    if coverage is not None:
        if coverage not in COVERAGES:
            return {"error": "Unbekannte Coverage."}
        team["coverage"] = coverage
    save(cfg, state)
    return {"ok": True, "concept": team["concept"], "coverage": team["coverage"]}


# --------------------------------------------------------------------------- #
# Zustand fürs Frontend
# --------------------------------------------------------------------------- #
def _next_opponent(state: dict) -> dict | None:
    if state["phase"] == "regular" and state["week"] < len(state["schedule"]):
        user_i = 0
        for hi, ai in state["schedule"][state["week"]]:
            if hi == user_i or ai == user_i:
                opp = state["teams"][ai if hi == user_i else hi]
                return {"name": opp["name"], "home": hi == user_i, "ovr": overall(opp),
                        "off": offense(opp), "def": defense(opp), "coverage": opp["coverage"]}
    return None


def view(state: dict) -> dict:
    team = state["teams"][0]
    last = state["results"][-1] if state["results"] else None
    return {
        "team_name": state["team_name"], "season": state["season"],
        "week": state["week"], "phase": state["phase"], "budget": state["budget"],
        "difficulty": state["difficulty"], "champion": state["champion"],
        "record": {"w": team["w"], "l": team["l"]},
        "ratings": {"off": offense(team), "def": defense(team), "ovr": overall(team)},
        "units": [{"key": u, "label": UNIT_LABELS[u], "level": team["units"][u],
                   "cost": upgrade_cost(team["units"][u]), "side": "Offense" if u in OFF_UNITS else "Defense"}
                  for u in ALL_UNITS],
        "playbook": {"concept": team["concept"], "coverage": team["coverage"]},
        "next": _next_opponent(state),
        "standings": standings(state),
        "playoff": state["playoff"],
        "last_result": last,
        "n_weeks": len(state["schedule"]),
        "history": state["history"],
        "has_last_game": bool(state.get("last_user_game")),
    }
