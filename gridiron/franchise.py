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
import math
import os
import random
import re
from dataclasses import dataclass

import numpy as np

from gridiron.config import Config
from gridiron.simulator import COVERAGES, PASS_CONCEPTS, RUN_CONCEPTS, play_outcome, simulate

# Einheiten (Roster-Gruppen) und ihre Gewichte für Offense-/Defense-Stärke.
GAME_DRIVES = 14                                          # Drives je Spiel (~7 Ballbesitze/Team)
OFF_UNITS = {"QB": 0.34, "OL": 0.30, "WR": 0.20, "RB": 0.16}
DEF_UNITS = {"DL": 0.40, "DB": 0.32, "LB": 0.28}
ST_UNITS = ["K"]                                     # Special Teams (Kicker) – zählt nicht in Off/Def-Rating
UNIT_LABELS = {"QB": "Quarterback", "OL": "O-Line", "WR": "Receiver", "RB": "Running Back",
               "DL": "D-Line", "LB": "Linebacker", "DB": "Secondary", "K": "Kicker"}
ALL_UNITS = list(OFF_UNITS) + list(DEF_UNITS) + ST_UNITS


def _unit_side(u: str) -> str:
    return "Offense" if u in OFF_UNITS else "Defense" if u in DEF_UNITS else "Special"


def kicker(team: dict) -> int:
    return team.get("units", {}).get("K", 65)


def fg_make_prob(ytz: float, krating: int) -> float:
    """Trefferwahrscheinlichkeit eines Field Goals: Distanz + Kicker-Stärke."""
    dist = ytz + 17.0                                # FG-Distanz (7 Yd Snap/Hold + 10 Yd Endzone)
    mid = 50.0 + (krating - 50) * 0.32               # 50%-Distanz; guter Kicker trifft weiter
    p = 1.0 / (1.0 + math.exp((dist - mid) / 7.0))
    return max(0.02, min(0.99, p))


def xp_make_prob(krating: int) -> float:
    return max(0.80, min(0.995, 0.86 + (krating - 50) * 0.003))


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


# Kader: Anzahl Spieler je Positionsgruppe (nur das Nutzer-Team führt echte Spieler).
ROSTER_SLOTS = {"QB": 2, "RB": 2, "WR": 3, "OL": 4, "DL": 4, "LB": 3, "DB": 3}
_FIRST = ["Marcus", "Tyler", "Jalen", "Deon", "Chris", "Andre", "Malik", "Cody",
          "Jordan", "Xavier", "Trey", "Devin", "Isaiah", "Brandon", "Kyle", "Drew",
          "Cam", "Aaron", "Josh", "Mason", "Elias", "Noah", "Leon", "Finn"]
_LAST = ["Brooks", "Carter", "Hayes", "Reed", "Coleman", "Foster", "Greer", "Mason",
         "Wells", "Pierce", "Dalton", "Boyd", "Frye", "Nash", "Sutton", "Vance",
         "Lang", "Webb", "Kraft", "Bauer", "Stein", "Wolff", "Roth", "Frank"]


def _name(rng: random.Random) -> str:
    return f"{rng.choice(_FIRST)} {rng.choice(_LAST)}"


# Kader: Slots & Starter je Positionsgruppe (nur das Nutzer-Team führt echte Spieler).
ROSTER_SLOTS = {"QB": 2, "RB": 3, "WR": 4, "OL": 5, "DL": 4, "LB": 4, "DB": 4}
STARTERS = {"QB": 1, "RB": 1, "WR": 2, "OL": 5, "DL": 4, "LB": 3, "DB": 3}

# Attribute je Position (Schlüssel -> Gewicht fürs OVR).
POS_ATTRS = {
    "QB": {"ACC": .35, "ARM": .25, "AWR": .25, "MOB": .15},
    "RB": {"SPD": .30, "AGI": .25, "PWR": .25, "CTH": .20},
    "WR": {"SPD": .30, "RTE": .30, "CTH": .30, "JMP": .10},
    "OL": {"PBK": .35, "RBK": .35, "STR": .20, "AWR": .10},
    "DL": {"PRSH": .35, "RDEF": .35, "STR": .20, "MOB": .10},
    "LB": {"TKL": .30, "COV": .30, "SPD": .25, "AWR": .15},
    "DB": {"COV": .40, "SPD": .30, "BALL": .20, "TKL": .10},
}
ATTR_LABELS = {"ACC": "Genauigkeit", "ARM": "Wurfkraft", "AWR": "Übersicht", "MOB": "Mobilität",
               "SPD": "Speed", "AGI": "Agilität", "PWR": "Power", "CTH": "Hände", "RTE": "Route",
               "JMP": "Sprungkraft", "PBK": "Pass-Schutz", "RBK": "Run-Block", "STR": "Stärke",
               "PRSH": "Pass-Rush", "RDEF": "Run-Stop", "TKL": "Tackling", "COV": "Coverage",
               "BALL": "Ball-Skills"}
POS_LABELS = {"QB": "Quarterback", "RB": "Running Back", "WR": "Receiver", "OL": "O-Line",
              "DL": "D-Line", "LB": "Linebacker", "DB": "Secondary"}

# Entwicklungs-Trait (Madden-Stil): wie schnell ein Spieler EXP in Können umsetzt.
DEV_TRAITS = {"normal": 1.0, "star": 1.4, "superstar": 1.9}
DEV_LABELS = {"normal": "Normal", "star": "Star", "superstar": "Superstar"}


def _gen_dev(rng: random.Random, prospect: bool = False) -> str:
    """Würfelt einen Entwicklungs-Trait. Prospects haben mehr Boom-Potenzial."""
    r = rng.random()
    if prospect:
        return "superstar" if r < 0.09 else "star" if r < 0.32 else "normal"
    return "superstar" if r < 0.04 else "star" if r < 0.18 else "normal"

_FIRST = ["Marcus", "Tyler", "Jalen", "Deon", "Chris", "Andre", "Malik", "Cody",
          "Jordan", "Xavier", "Trey", "Devin", "Isaiah", "Brandon", "Kyle", "Drew",
          "Cam", "Aaron", "Josh", "Mason", "Elias", "Noah", "Leon", "Finn", "Theo",
          "Luca", "Jonas", "Nico", "Ben", "Tim", "Erik", "Paul", "Max", "Liam"]
_LAST = ["Brooks", "Carter", "Hayes", "Reed", "Coleman", "Foster", "Greer", "Mason",
         "Wells", "Pierce", "Dalton", "Boyd", "Frye", "Nash", "Sutton", "Vance",
         "Lang", "Webb", "Kraft", "Bauer", "Stein", "Wolff", "Roth", "Frank",
         "Berg", "Hahn", "Voss", "Lorenz", "Schwarz", "Kern", "Busch", "Engel"]


def _name(rng: random.Random) -> str:
    return f"{rng.choice(_FIRST)} {rng.choice(_LAST)}"


def player_ovr(p: dict) -> int:
    w = POS_ATTRS[p["pos"]]
    return round(sum(p["attr"][k] * w[k] for k in w))


def player_pot(p: dict) -> int:
    w = POS_ATTRS[p["pos"]]
    return round(sum(p["cap"][k] * w[k] for k in w))


# Statistik-Schema (Saison + Karriere je Spieler)
STAT_KEYS = ["pass_yds", "pass_td", "rush_att", "rush_yds", "rec", "rec_yds",
             "td", "tkl", "sack", "intc"]


def _blank_stats() -> dict:
    d = {k: 0 for k in STAT_KEYS}
    d["games"] = 0
    return d


def _accumulate(rid: dict, box: dict) -> None:
    """Addiert die Box-Score-Werte eines Spiels in Saison- und Karrierestatistik."""
    for pid, s in box.items():
        p = rid.get(pid)
        if not p:
            continue
        for tgt in ("season", "career"):
            d = p.setdefault(tgt, _blank_stats())
            for k in STAT_KEYS:
                d[k] = d.get(k, 0) + s.get(k, 0)
            d["games"] = d.get("games", 0) + 1


def _coach_view(team: dict, role: str) -> dict:
    c = team.get("coaches", {}).get(role) or _gen_coach(role, 60, random.Random(0))
    return {"role": role, "label": COACH_ROLES[role], "name": c["name"],
            "rating": coach_rating(c), "improve_cost": upgrade_cost(coach_rating(c)),
            "traits": [{"label": t, "val": c["traits"][t]} for t in c["traits"]]}


def _player_view(p: dict) -> dict:
    return {"id": p["id"], "name": p["name"], "pos": p["pos"], "age": p["age"],
            "starter": p["starter"], "ovr": player_ovr(p), "pot": player_pot(p),
            "exp": p.get("exp", 0), "pts": p.get("pts", 0), "inj": p.get("inj", 0),
            "dev": p.get("dev", "normal"), "dev_label": DEV_LABELS.get(p.get("dev", "normal"), "Normal"),
            "side": "Offense" if p["pos"] in OFF_UNITS else "Defense",
            "attrs": [{"key": k, "label": ATTR_LABELS[k], "val": p["attr"][k], "cap": p["cap"][k]}
                      for k in POS_ATTRS[p["pos"]]],
            "season": p.get("season", _blank_stats()), "career": p.get("career", _blank_stats())}


def _unique_name(rng: random.Random, used: set | None) -> str:
    if used is None:
        return _name(rng)
    for _ in range(60):
        n = _name(rng)
        if n not in used:
            used.add(n)
            return n
    n = f"{_name(rng)} jr."
    used.add(n)
    return n


def _gen_player(pid: int, pos: str, base: int, rng: random.Random,
                age: int | None = None, starter: bool = False, used: set | None = None,
                hicap: bool = False) -> dict:
    age = age if age is not None else rng.randint(21, 33)
    attr, cap = {}, {}
    for k in POS_ATTRS[pos]:
        a = max(46, min(82, round(rng.gauss(base + 1, 4)) + (2 if starter else 0)))
        attr[k] = a
        if hicap:                                        # eigenes Team: viel Luft nach oben (bis 99 erreichbar)
            cap[k] = min(99, max(a + rng.randint(10, 22), rng.randint(90, 99)))
        else:
            cap[k] = min(99, max(a, a + rng.randint(2, 16) - max(0, age - 28)))
    return {"id": pid, "name": _unique_name(rng, used), "pos": pos, "age": age, "starter": starter,
            "attr": attr, "cap": cap, "exp": 0, "pts": 0, "inj": 0,
            "dev": _gen_dev(rng), "season": _blank_stats(), "career": _blank_stats()}


def _gen_roster(base: int, rng: random.Random, hicap: bool = False) -> list[dict]:
    roster, pid, used = [], 0, set()
    for grp, cnt in ROSTER_SLOTS.items():
        for i in range(cnt):
            roster.append(_gen_player(pid, grp, base, rng, starter=i < STARTERS[grp], used=used, hicap=hicap))
            pid += 1
    return roster


def _draft_class(state: dict, rng: random.Random, n: int = 16) -> list[dict]:
    """Erzeugt eine Klasse freier Spieler (Rookies mit Potenzial + Veteranen)."""
    out, used = [], set()
    seq = state.get("pid_seq", 10000)
    for _ in range(n):
        pos = rng.choice(list(ROSTER_SLOTS))
        rookie = rng.random() < 0.6
        base = rng.randint(52, 64) if rookie else rng.randint(60, 72)
        age = rng.randint(21, 23) if rookie else rng.randint(24, 30)
        p = _gen_player(seq, pos, base, rng, age=age, used=used)
        seq += 1
        if rookie:                                       # Rookies: mehr Entwicklung
            for k in p["cap"]:
                p["cap"][k] = min(99, p["cap"][k] + rng.randint(2, 9))
        out.append(p)
    state["pid_seq"] = seq
    return out


# --------------------------------------------------------------------------- #
# College-Scouting & Draft
# --------------------------------------------------------------------------- #
SCOUT_MAX = 3                          # volle Aufklärung nach 3 Scouting-Stufen
_SCOUT_HALF = {0: 9, 1: 5, 2: 2, 3: 0}  # Unsicherheits-Halbweite der OVR-Spanne je Stufe


def _gen_prospects(state: dict, rng: random.Random, n: int = 12) -> list[dict]:
    """College-Prospects: junge Talente mit verstecktem Können & Boom/Bust-Risiko."""
    out, used = [], set()
    seq = state.get("pid_seq", 10000)
    for _ in range(n):
        pos = rng.choice(list(ROSTER_SLOTS))
        base = rng.randint(50, 66)
        p = _gen_player(seq, pos, base, rng, age=rng.randint(20, 23), used=used)
        seq += 1
        for k in p["cap"]:                               # College-Talent: deutliches Ceiling
            p["cap"][k] = min(99, p["cap"][k] + rng.randint(4, 14))
        p["dev"] = _gen_dev(rng, prospect=True)
        p["scout"] = 0
        p["_bias"] = rng.randint(-4, 4)                  # Scouting-Konsens kann danebenliegen
        out.append(p)
    state["pid_seq"] = seq
    return out


def _proj_round(p: dict) -> str:
    """Öffentlicher Scouting-Konsens (kann durch _bias daneben liegen = Boom/Bust)."""
    est = player_pot(p) + p.get("_bias", 0)
    return "1. Runde" if est >= 82 else "2.–3. Runde" if est >= 74 \
        else "4.–5. Runde" if est >= 66 else "Spätrunde"


def _grade_word(ovr: int) -> str:
    return "Star-Anlage" if ovr >= 80 else "Sofort-Starter" if ovr >= 72 \
        else "Rotationsspieler" if ovr >= 64 else "Projekt"


def prospect_cost(p: dict) -> int:
    return {"1. Runde": 26, "2.–3. Runde": 17, "4.–5. Runde": 10}.get(_proj_round(p), 6)


def prospect_view(p: dict) -> dict:
    """Zeigt nur, was bereits gescoutet wurde. Volle Werte erst ab Stufe 3."""
    sc = p.get("scout", 0)
    ovr, pot = player_ovr(p), player_pot(p)
    half = _SCOUT_HALF.get(sc, 9)
    lo = max(40, ovr + p.get("_bias", 0) - half)
    hi = min(99, ovr + p.get("_bias", 0) + half)
    full = sc >= SCOUT_MAX
    out = {
        "id": p["id"], "pos": p["pos"], "age": p["age"], "scout": sc, "scout_max": SCOUT_MAX,
        "side": "Offense" if p["pos"] in OFF_UNITS else "Defense",
        "name": p["name"] if sc >= 1 else f"Prospect #{p['id'] % 1000:03d}",
        "round": _proj_round(p), "cost": prospect_cost(p),
        "ovr_lo": lo, "ovr_hi": hi,
        "ovr": ovr if full else None,
        "grade": _grade_word(ovr) if sc >= 2 else "?",
    }
    if sc >= 2:
        topk = max(p["attr"], key=lambda k: p["attr"][k])
        out["strength"] = ATTR_LABELS[topk]
    if full:
        out["pot"] = pot
        out["dev"] = p.get("dev", "normal")
        out["dev_label"] = DEV_LABELS.get(p.get("dev", "normal"), "Normal")
        out["attrs"] = [{"key": k, "label": ATTR_LABELS[k], "val": p["attr"][k], "cap": p["cap"][k]}
                        for k in POS_ATTRS[p["pos"]]]
    return out


def scout_prospect(cfg: Config, state: dict, pid: int) -> dict:
    p = next((x for x in state.get("prospects", []) if x["id"] == pid), None)
    if not p:
        return {"error": "Prospect nicht gefunden."}
    if p.get("scout", 0) >= SCOUT_MAX:
        return {"error": "Bereits vollständig gescoutet."}
    if state.get("scout_pts", 0) < 1:
        return {"error": "Keine Scouting-Punkte übrig — nächste Woche gibt es neue."}
    state["scout_pts"] -= 1
    p["scout"] = p.get("scout", 0) + 1
    save(cfg, state)
    return {"ok": True, "scout": p["scout"]}


def draft_prospect(cfg: Config, state: dict, pid: int) -> dict:
    team = state["teams"][0]
    pool = state.get("prospects", [])
    p = next((x for x in pool if x["id"] == pid), None)
    if not p:
        return {"error": "Prospect nicht verfügbar."}
    pos = p["pos"]
    if sum(1 for x in team["roster"] if x["pos"] == pos) >= ROSTER_SLOTS[pos]:
        return {"error": f"{POS_LABELS[pos]} ist voll ({ROSTER_SLOTS[pos]}) — erst jemanden entlassen."}
    cost = prospect_cost(p)
    if state["budget"] < cost:
        return {"error": f"Budget zu niedrig (brauchst {cost}, hast {state['budget']})."}
    pool.remove(p)
    for key in ("scout", "_bias"):
        p.pop(key, None)
    p["starter"] = False
    team["roster"].append(p)
    state["budget"] -= cost
    _sync_units(team)
    save(cfg, state)
    return {"ok": True, "drafted": p["name"], "ovr": player_ovr(p), "cost": cost}


def _units_from_roster(roster: list[dict]) -> dict:
    by: dict[str, list[tuple[int, int]]] = {g: [] for g in ROSTER_SLOTS}
    for p in roster:
        if p.get("inj", 0) > 0:                          # verletzt -> nicht verfügbar
            continue
        by[p["pos"]].append((player_ovr(p), 2 if p["starter"] else 1))
    # Falls eine Gruppe komplett ausfällt: Notbesetzung (verletzte zählen schwach)
    for g in by:
        if not by[g]:
            inj = [(max(40, player_ovr(p) - 6), 1) for p in roster if p["pos"] == g]
            by[g] = inj or [(55, 1)]
    out = {}
    for g, lst in by.items():
        wsum = sum(w for _, w in lst)
        out[g] = round(sum(o * w for o, w in lst) / wsum) if wsum else 60
    return out


def _sync_units(team: dict) -> None:
    if team.get("roster"):
        new = _units_from_roster(team["roster"])
        for u in ST_UNITS:                               # Kicker/Special Teams nicht aus dem Kader ableiten
            new[u] = team.get("units", {}).get(u, 65)
        team["units"] = new


def _gain_exp(p: dict, amount: int) -> None:
    amount = round(amount * DEV_TRAITS.get(p.get("dev", "normal"), 1.0))   # Dev-Trait beschleunigt Wachstum
    p["exp"] += amount
    while p["exp"] >= 100:
        p["exp"] -= 100
        p["pts"] += 1


def allocate_point(team: dict, pid: int, attr: str) -> dict:
    p = next((x for x in team.get("roster", []) if x["id"] == pid), None)
    if not p:
        return {"error": "Spieler nicht gefunden."}
    if attr not in p["attr"]:
        return {"error": "Attribut passt nicht zur Position."}
    if p["pts"] <= 0:
        return {"error": "Keine Skillpunkte verfügbar."}
    if p["attr"][attr] >= p["cap"][attr]:
        return {"error": "Attribut ist am Potenzial-Limit."}
    p["attr"][attr] += 1
    p["pts"] -= 1
    _sync_units(team)
    return {"ok": True, "attr": attr, "value": p["attr"][attr], "pts": p["pts"]}


def auto_allocate(team: dict, pid: int) -> dict:
    p = next((x for x in team.get("roster", []) if x["id"] == pid), None)
    if not p:
        return {"error": "Spieler nicht gefunden."}
    w = POS_ATTRS[p["pos"]]
    spent = 0
    while p["pts"] > 0:
        cands = [k for k in w if p["attr"][k] < p["cap"][k]]
        if not cands:
            break
        best = max(cands, key=lambda k: (w[k], -p["attr"][k]))
        p["attr"][best] += 1
        p["pts"] -= 1
        spent += 1
    _sync_units(team)
    return {"ok": True, "spent": spent, "pts": p["pts"]}


def set_starter(team: dict, pid: int) -> dict:
    p = next((x for x in team.get("roster", []) if x["id"] == pid), None)
    if not p:
        return {"error": "Spieler nicht gefunden."}
    limit = STARTERS[p["pos"]]
    starters = [x for x in team["roster"] if x["pos"] == p["pos"] and x["starter"]]
    if not p["starter"] and len(starters) >= limit:
        return {"error": f"Maximal {limit} Starter auf {p['pos']} — erst einen entfernen."}
    p["starter"] = not p["starter"]
    _sync_units(team)
    return {"ok": True, "starter": p["starter"]}


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


# --- Trainer mit individuellen Stärken/Schwächen ---------------------------- #
COACH_ROLES = {"HC": "Head Coach", "OC": "Offensive Coordinator", "DC": "Defensive Coordinator"}
COACH_TRAITS = {"HC": ["Entwicklung", "Spielmanagement", "Moral"],
                "OC": ["Passspiel", "Laufspiel", "Kreativität"],
                "DC": ["Coverage", "Pass-Rush", "Disziplin"]}


def _gen_coach(role: str, base: int, rng: random.Random) -> dict:
    traits = {t: max(45, min(92, round(rng.gauss(base, 7)))) for t in COACH_TRAITS[role]}
    return {"role": role, "name": _name(rng), "traits": traits}


def coach_rating(c: dict) -> int:
    return round(sum(c["traits"].values()) / len(c["traits"]))


def _trait(team: dict, role: str, trait: str, dflt: int = 60) -> int:
    return team.get("coaches", {}).get(role, {}).get("traits", {}).get(trait, dflt)


def _coach_rating(team: dict, role: str) -> int:
    c = team.get("coaches", {}).get(role)
    return coach_rating(c) if c else 60


def offense(team: dict) -> int:
    b = _rating(team["units"], OFF_UNITS)
    return min(99, b + round((_coach_rating(team, "OC") - 60) * 0.30)
              + round((_trait(team, "HC", "Spielmanagement") - 60) * 0.10))


def defense(team: dict) -> int:
    b = _rating(team["units"], DEF_UNITS)
    return min(99, b + round((_coach_rating(team, "DC") - 60) * 0.30)
              + round((_trait(team, "HC", "Spielmanagement") - 60) * 0.10))


def overall(team: dict) -> int:
    return round((offense(team) + defense(team)) / 2)


# --------------------------------------------------------------------------- #
# Persistenz
# --------------------------------------------------------------------------- #
import contextvars
_PROFILE = contextvars.ContextVar("gi_profile", default="default")


def _sanitize_profile(name: str) -> str:
    s = re.sub(r"[^a-z0-9_-]", "", (name or "").strip().lower())[:32]
    return s or "default"


def set_profile(name: str):
    """Aktives Profil für diesen Request setzen (Spielstand pro Name)."""
    return _PROFILE.set(_sanitize_profile(name))


def _save_path(cfg: Config) -> str:
    cfg.ensure_dirs()
    prof = _PROFILE.get()
    fname = "franchise.json" if prof == "default" else f"franchise_{prof}.json"
    return os.path.join(cfg.data_dir, fname)


def exists(cfg: Config) -> bool:
    return os.path.exists(_save_path(cfg))


def load(cfg: Config) -> dict | None:
    p = _save_path(cfg)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as fh:
        state = json.load(fh)
    _migrate(state)
    return state


def _migrate(state: dict) -> None:
    """Ältere Spielstände um neue Felder ergänzen (Dev-Traits, College-Scouting)."""
    rng = random.Random(state.get("season", 1) * 7 + 13)
    for t in state.get("teams", []):
        for pl in t.get("roster", []):
            pl.setdefault("dev", "normal")
        u = t.get("units")                               # Kicker-Rating ergänzen (Special Teams)
        if isinstance(u, dict) and "K" not in u:
            u["K"] = rng.randint(58, 74)
        if t.get("user"):                                 # neue Anlagen für alte Spielstände
            for fac in ("medical", "athletic", "scouting_fac", "youth"):
                t.setdefault(fac, 1)
    if "scout_pts" not in state:
        state["scout_pts"] = 6
    if "prospects" not in state:
        state["prospects"] = _gen_prospects(state, rng)


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


def _season_schedule(n: int, rng: random.Random) -> list:
    """Round-Robin + eine liga-weite Bye-Week (spielfreie Woche) in der Mitte."""
    weeks = _round_robin(n)
    if len(weeks) >= 4:
        weeks.insert(rng.randint(2, len(weeks) - 2), [])   # [] = Bye Week
    return weeks


def _new_team(name: str, abbr: str, color: str, color2: str, base: int,
              rng: random.Random, user: bool = False) -> dict:
    units = {u: max(50, min(95, base + rng.randint(-6, 6))) for u in ALL_UNITS}
    coaches = {r: _gen_coach(r, base - 4, rng) for r in COACH_ROLES}
    return {
        "name": name, "abbr": abbr, "color": color, "color2": color2, "user": user,
        "units": units, "coaches": coaches, "stadium": 1,
        "off_scheme": "Ausgeglichen" if user else rng.choice(list(OFF_SCHEMES)),
        "def_scheme": "Ausgeglichen" if user else rng.choice(list(DEF_SCHEMES)),
        "w": 0, "l": 0, "t": 0, "pf": 0, "pa": 0,
    }


def new_franchise(cfg: Config, team_name: str, n_teams: int = 8,
                  difficulty: str = "normal", color: str | None = None,
                  seed: int | None = None) -> dict:
    n_teams = max(4, n_teams - (n_teams % 2))             # gerade, >=4
    rng = random.Random(seed)
    nm = team_name.strip()[:24] or "Mein Team"
    ucolor = color if color in USER_COLORS else USER_COLORS[0]
    user_team = _new_team(nm, _abbr(nm), ucolor, "#0c1a12", 70, rng, user=True)
    user_team["roster"] = _gen_roster(70, rng, hicap=True)   # Start: ~70-OVR-Kader, viel Entwicklungs-Potenzial
    user_team["equipment"] = 1                            # Trainings-Equipment (EXP/Woche)
    for fac in ("medical", "athletic", "scouting_fac", "youth"):
        user_team[fac] = 1                                # Anlagen starten auf Stufe 1
    _sync_units(user_team)                                # Units aus dem Kader ableiten
    teams = [user_team]
    # KI-Stärke je Schwierigkeit (Nutzer startet bei 70 und wächst ~8-9 OVR/Saison)
    ai_lo, ai_hi = {"leicht": (64, 74), "normal": (70, 80), "schwer": (76, 86)}.get(difficulty, (70, 80))
    for cname, cabbr, c1, c2 in rng.sample(TEAM_CATALOG, n_teams - 1):
        teams.append(_new_team(cname, cabbr, c1, c2, rng.randint(ai_lo, ai_hi), rng))
    teams[0]["game_bonus"] = 0
    state = {
        "team_name": teams[0]["name"], "season": 1, "week": 0,
        "phase": "regular", "budget": 60, "difficulty": difficulty,
        "teams": teams, "schedule": _season_schedule(n_teams, rng),
        "results": [], "log": [], "history": [], "playoff": None,
        "champion": None, "training_focus": None, "week_trained": False, "week_done": False,
        "tutorial_seen": False,
        "coach_market": _gen_market(rng), "events": [], "pid_seq": 10000,
        "scout_pts": 6,
    }
    state["market_players"] = _draft_class(state, rng)
    state["prospects"] = _gen_prospects(state, rng)
    state["goals"] = _gen_goals(state)
    save(cfg, state)
    return state


def _gen_goals(state: dict) -> list[dict]:
    games = sum(1 for w in state["schedule"] if w)        # Spiele (ohne Bye)
    target = max(1, round(games * 0.55))
    return [
        {"key": "wins", "label": f"Mindestens {target} Siege", "target": target,
         "reward": 15, "done": False},
        {"key": "playoffs", "label": "Die Playoffs erreichen", "reward": 25, "done": False},
    ]


def _check_goals(state: dict) -> list[dict]:
    team = state["teams"][0]
    msgs = []
    for g in state.get("goals", []):
        if g.get("done"):
            continue
        ok = (g["key"] == "wins" and team["w"] >= g["target"]) or \
             (g["key"] == "playoffs" and state["phase"] in ("playoffs", "done"))
        if ok:
            g["done"] = True
            state["budget"] += g["reward"]
            msgs.append({"type": "money", "text": f"Saisonziel erreicht: {g['label']} (+{g['reward']} Mio)."})
    return msgs


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


def _avail(roster: list[dict], positions) -> list[dict]:
    pool = [p for p in roster if p["pos"] in positions and p["starter"] and p.get("inj", 0) == 0]
    return pool or [p for p in roster if p["pos"] in positions and p.get("inj", 0) == 0]


def _healthy(roster: list[dict], positions) -> list[dict]:
    return [p for p in roster if p["pos"] in positions and p.get("inj", 0) == 0]


def _pick(pool: list[dict], rng: random.Random, wf) -> dict | None:
    if not pool:
        return None
    return rng.choices(pool, weights=[max(1, wf(p)) for p in pool])[0]


def _w_start(p: dict) -> float:
    return 2.0 if p["starter"] else 0.7              # Starter mehr Touches, Bank etwas


def _stat(box: dict, p: dict) -> dict:
    return box.setdefault(p["id"], {"id": p["id"], "name": p["name"], "pos": p["pos"],
                                    "pass_yds": 0, "pass_td": 0, "rec": 0, "rec_yds": 0,
                                    "rush_att": 0, "rush_yds": 0, "td": 0,
                                    "tkl": 0, "sack": 0, "intc": 0})


def _attr_off(box: dict, roster: list[dict], o: dict, yards: int, td: bool, rng: random.Random) -> None:
    if o["pass"]:
        qb = (_avail(roster, ("QB",)) or [None])[0]
        if o["kind"] == "complete":
            tgt = _pick(_healthy(roster, ("WR", "RB")), rng,
                        lambda p: player_ovr(p) * (1.6 if p["pos"] == "WR" else 0.7) * _w_start(p))
            if qb:
                _stat(box, qb)["pass_yds"] += max(0, yards)
            if tgt:
                s = _stat(box, tgt); s["rec"] += 1; s["rec_yds"] += max(0, yards)
            if td:
                if qb:
                    _stat(box, qb)["pass_td"] += 1
                if tgt:
                    _stat(box, tgt)["td"] += 1
    else:
        rb = _pick(_healthy(roster, ("RB",)), rng, lambda p: player_ovr(p) * _w_start(p))
        if rb:
            s = _stat(box, rb); s["rush_att"] += 1; s["rush_yds"] += yards
            if td:
                s["td"] += 1


def _attr_def(box: dict, roster: list[dict], o: dict, rng: random.Random) -> None:
    t = _pick(_healthy(roster, ("DL", "LB", "DB")), rng, lambda p: player_ovr(p) * _w_start(p))
    if t:
        _stat(box, t)["tkl"] += 1
    if o["kind"] == "sack":
        s = _pick(_healthy(roster, ("DL", "LB")), rng, lambda p: player_ovr(p) * _w_start(p))
        if s:
            _stat(box, s)["sack"] += 1
    if o["turnover"] and o["pass"]:
        d = _pick(_healthy(roster, ("DB",)), rng, lambda p: player_ovr(p) * _w_start(p))
        if d:
            _stat(box, d)["intc"] += 1


def _box_exp(s: dict) -> int:
    return (s["pass_yds"] // 20 + s["pass_td"] * 4 + (s["rush_yds"] + s["rec_yds"]) // 12
            + s["rec"] + s["rush_att"] // 3 + s["td"] * 4 + s["tkl"] + s["sack"] * 5 + s["intc"] * 8)


def simulate_game_detailed(home: dict, away: dict, rng: random.Random) -> dict:
    """Spiel als Play-by-Play auf Spielerebene. Erzeugt für das Nutzer-Team einen
    Box-Score und vergibt danach leistungsbasierte EXP."""
    score = [0, 0]
    plays: list[dict] = []
    teams = [home, away]
    user_side = 0 if home.get("user") else (1 if away.get("user") else None)
    box: dict = {}
    pos = 0 if rng.random() < 0.5 else 1
    for drive in range(GAME_DRIVES):
        off, deff = teams[pos], teams[1 - pos]
        # Heim (pos 0) verteidigt die rechte Endzone und greift nach LINKS an;
        # Gast (pos 1) greift nach RECHTS an. Jeder startet an der eigenen 25.
        attack_right = (pos == 1)
        absx = 25.0 if attack_right else 75.0
        ytz, down, dist = 75.0, 1, 10
        q = min(4, drive // (GAME_DRIVES // 4) + 1)
        oc_pool = OFF_SCHEMES.get(off.get("off_scheme", "Ausgeglichen"), list(PASS_CONCEPTS))
        dc_pool = DEF_SCHEMES.get(deff.get("def_scheme", "Ausgeglichen"), list(COVERAGES))
        edge = 0.10 * (offense(off) - defense(deff)) + 0.5 * off.get("game_bonus", 0)  # +Film-Bonus
        for _ in range(14):
            concept, coverage = rng.choice(oc_pool), rng.choice(dc_pool)
            o = play_outcome(concept, coverage, {"yardline_100": ytz, "down": down, "ydstogo": dist}, _RNG)
            yards = max(-12, min(round(o["yards"] + edge), int(ytz)))
            td = (ytz - yards <= 0) and not o["turnover"]
            if user_side is not None:
                if pos == user_side and off.get("roster"):
                    _attr_off(box, off["roster"], o, yards, td, rng)
                elif (1 - pos) == user_side and deff.get("roster"):
                    _attr_def(box, deff["roster"], o, rng)
            absx = min(100, max(0, absx + (yards if attack_right else -yards)))
            if o["turnover"]:
                plays.append(_pl(q, off["name"], "Interception!" if o["pass"] else "Fumble, Ball verloren!", absx, score, False))
                break
            if td:
                xp = 1 if rng.random() < xp_make_prob(kicker(off)) else 0   # Touchdown + Extra-Punkt
                score[pos] += 6 + xp
                plays.append(_pl(q, off["name"], "TOUCHDOWN! " + off["name"] + ("" if xp else " (Extra-Punkt daneben)"),
                                 100 if attack_right else 0, score, True))
                break
            ytz -= yards
            dist -= yards
            label = _play_label(concept, o, yards)
            if dist <= 0:
                down, dist = 1, 10
                label += " — First Down"
            else:
                down += 1
            if down > 4:
                if ytz <= 45 and rng.random() < fg_make_prob(ytz, kicker(off)):   # Field Goal je nach Kicker
                    score[pos] += 3
                    plays.append(_pl(q, off["name"], f"Field Goal gut aus {round(ytz + 17)} Yd (3)", absx, score, True))
                else:
                    plays.append(_pl(q, off["name"], "Punt" if ytz > 45 else "Field Goal daneben", absx, score, False))
                break
            plays.append(_pl(q, off["name"], label, absx, score, False))
        pos ^= 1
    sh, sa = score[0], score[1]
    while sh == sa:
        sh += 3 if rng.random() < 0.5 else 0
        sa += 3 if sh == sa else 0
    # Leistungs-EXP + Statistik auf das Nutzer-Team
    if user_side is not None:
        rid = {p["id"]: p for p in teams[user_side].get("roster", [])}
        for pid, s in box.items():
            if pid in rid:
                _gain_exp(rid[pid], _box_exp(s))
        _accumulate(rid, box)
    box_lines = sorted(box.values(), key=_box_exp, reverse=True)
    return {"home": home["name"], "away": away["name"], "hs": sh, "as": sa,
            "winner": home["name"] if sh > sa else away["name"], "plays": plays,
            "habbr": home.get("abbr", "HOM"), "aabbr": away.get("abbr", "AWY"),
            "hcolor": home.get("color", "#16c784"), "acolor": away.get("color", "#ef5350"),
            "box": [b for b in box_lines if _box_exp(b) > 0][:10]}


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
    """Wertet die aktuelle Woche aus (Spiele + Event), schreitet aber NICHT
    automatisch fort — das geschieht erst über next_week()."""
    if state["phase"] == "done":
        return {"error": "Saison beendet — starte eine neue Saison."}
    if state.get("week_done"):
        return {"error": "Diese Woche ist bereits ausgewertet — bitte zur nächsten Woche gehen."}
    if not state.get("week_trained"):
        return {"error": "Erst das Training dieser Woche absolvieren."}
    rng = random.Random()
    teams = state["teams"]

    user_game = None
    if state["phase"] == "regular":
        wk = state["week"]
        games = []
        for hi, ai in state["schedule"][wk]:
            if user_result and (hi == 0 or ai == 0):
                _apply(teams[hi], teams[ai], user_result)
                games.append(_strip(user_result))
            else:
                r, pbp = _decide(teams[hi], teams[ai], rng)
                _apply(teams[hi], teams[ai], r)
                games.append(_strip(r))
                if pbp:
                    user_game = pbp
        state["results"].append({"week": wk + 1, "games": games})
        _earn(state, games)
        out = {"phase": "regular", "week": wk + 1, "games": games}
    else:
        out = _resolve_playoff(state, rng, user_result)
        user_game = out.pop("_user_game", None)

    out["events"] = _process_events(state, rng)
    out["events"] += _check_goals(state)
    if user_game:
        state["last_user_game"] = user_game
        out["user_game"] = user_game
    state["week_done"] = True                              # Woche ausgewertet, wartet auf Bestätigung
    save(cfg, state)
    return out


def next_week(cfg: Config, state: dict) -> dict:
    """Schreitet zur nächsten Woche fort (nur nach Auswertung)."""
    if state["phase"] == "done":
        return {"error": "Saison beendet."}
    if not state.get("week_done"):
        return {"error": "Erst das Spiel der Woche abschließen."}
    if state["phase"] == "regular":
        state["week"] += 1
        if state["week"] >= len(state["schedule"]):
            _start_playoffs(state)
    else:
        _advance_playoff(state)
    extra = _check_goals(state)                           # Playoff-Ziel ggf. erfüllt
    if extra:
        state["events"] = (state.get("events") or []) + extra
    state["week_done"] = False
    state["week_trained"] = False
    state["scout_pts"] = state.get("scout_pts", 0) + 3 + (state["teams"][0].get("scouting_fac", 1) - 1)  # Scouting-Akademie gibt extra Punkte
    state["teams"][0]["game_bonus"] = 0
    # Entscheidungs-Event nicht jede Woche (~35 %), nur in der regulären Saison
    if (state["phase"] == "regular" and not state.get("pending_event")
            and state["teams"][0].get("roster") and random.random() < 0.35):
        _gen_event(state, random.Random())
    save(cfg, state)
    return {"ok": True, "view": view(state)}


def _strip(r: dict) -> dict:
    """Spielergebnis ohne das große Play-by-Play (für die Ergebnisliste)."""
    return {k: r[k] for k in ("home", "away", "hs", "as", "winner")}


def _earn(state: dict, games: list[dict]) -> None:
    team = state["teams"][0]
    user = team["name"]
    g = next((x for x in games if user in (x["home"], x["away"])), None)
    won = bool(g and g["winner"] == user)
    income = 6 + 2 * (team.get("stadium", 1) - 1)            # Stadion bringt Mehreinnahmen
    if g:
        income += 10 if won else 3
    state["budget"] += income


def _exp_mult(team: dict) -> float:
    """Trainingsausbeute: Head-Coach-Entwicklung + Equipment heben die EXP."""
    dev = _trait(team, "HC", "Entwicklung")
    return (1 + (dev - 60) / 200.0) * (1 + 0.12 * (team.get("equipment", 1) - 1))


# Wöchentliche Trainings-Optionen (visuell wählbar, 1× pro Woche).
TRAININGS = [
    {"key": "team", "label": "Teamtraining", "icon": "team",
     "desc": "Alle Spieler sammeln EXP."},
    {"key": "offense", "label": "Offense-Drills", "icon": "off",
     "desc": "Offense-Gruppe bekommt deutlich EXP."},
    {"key": "defense", "label": "Defense-Drills", "icon": "def",
     "desc": "Defense-Gruppe bekommt deutlich EXP."},
    {"key": "single", "label": "Einzeltraining", "icon": "star",
     "desc": "Größter Talent-Schub für deinen besten Entwicklungs-Spieler."},
    {"key": "regen", "label": "Regeneration", "icon": "heal",
     "desc": "Verletzte erholen sich eine Woche schneller."},
    {"key": "film", "label": "Film-Session", "icon": "film",
     "desc": "Taktik-Vorteil fürs nächste Spiel."},
]


def do_training(cfg: Config, state: dict, kind: str) -> dict:
    """Einmal pro Woche: gewähltes Training anwenden."""
    if state.get("week_trained"):
        return {"error": "Diese Woche wurde bereits trainiert."}
    team = state["teams"][0]
    roster = team.get("roster", [])
    m = _exp_mult(team)
    msg = ""
    if kind == "team":
        for p in roster:
            _gain_exp(p, round(150 * m))
        msg = "Teamtraining: alle Spieler haben EXP gesammelt."
    elif kind in ("offense", "defense"):
        side = "Offense" if kind == "offense" else "Defense"
        for p in roster:
            if _side(p["pos"]) == side:
                _gain_exp(p, round(260 * m))
        msg = f"{side}-Drills: Gruppe hat ordentlich EXP gesammelt."
    elif kind == "single":
        cand = [p for p in roster if player_ovr(p) < player_pot(p)]
        if not cand:
            return {"error": "Alle Spieler sind am Potenzial — kein Einzeltraining nötig."}
        target = min(cand, key=lambda p: (p["age"], -(player_pot(p) - player_ovr(p))))
        _gain_exp(target, round(520 * m))
        msg = f"Einzeltraining: {target['name']} ({target['pos']}) macht einen großen Schritt."
    elif kind == "regen":
        healed = 0
        for p in roster:
            if p.get("inj", 0) > 0:
                p["inj"] = max(0, p["inj"] - 1); healed += 1
        msg = (f"Regeneration: {healed} verletzte Spieler erholen sich schneller."
               if healed else "Regeneration: keine Verletzten — Team frisch erholt.")
    elif kind == "film":
        team["game_bonus"] = 3
        msg = "Film-Session: Taktik-Vorteil fürs nächste Spiel (+)."
    else:
        return {"error": "Unbekanntes Training."}
    state["week_trained"] = True
    save(cfg, state)
    return {"ok": True, "text": msg}


def _side(pos: str) -> str:
    return "Offense" if pos in OFF_UNITS else "Defense"


def _process_events(state: dict, rng: random.Random) -> list[dict]:
    """Wöchentlich nur Verletzungen heilen + kleine Flavor-Neuigkeit. Die echten
    Entscheidungs-Events (Buffs/Debuff) sind davon getrennt und nicht jede Woche."""
    team = state["teams"][0]
    roster = team.get("roster", [])
    if not roster:
        return []
    msgs: list[dict] = []
    heal = 1 + (1 if team.get("medical", 1) >= 4 else 0)   # Medizin: ab Stufe 4 heilt eine Woche schneller
    for p in roster:
        if p.get("inj", 0) > 0:
            p["inj"] = max(0, p["inj"] - heal)
            if p["inj"] == 0:
                msgs.append({"type": "ok", "text": f"{p['name']} ist wieder fit und einsatzbereit."})
    ath = (team.get("athletic", 1) - 1) * 12               # Athletik: passive Regenerations-EXP/Woche
    if ath:
        for p in roster:
            _gain_exp(p, ath)
    if rng.random() < 0.5:                                # kleine Geld-Neuigkeit (Flavor)
        inc = rng.randint(2, 6); state["budget"] += inc
        flav = rng.choice(["Fan-Andrang im Stadion", "Sponsoren-Bonus", "Merchandise-Verkäufe", "TV-Einnahmen"])
        msgs.append({"type": "money", "text": f"{flav}: +{inc} Mio."})
    state["events"] = msgs
    _sync_units(team)
    return msgs


# --------------------------------------------------------------------------- #
# Entscheidungs-Events: 2 Buffs (je 1 von 2) + 1 Debuff (1 von 2), nicht jede Woche
# --------------------------------------------------------------------------- #
_BUFFS = [
    {"label": "Sponsoren-Deal: +9 Mio Budget", "eff": [{"k": "money", "n": 9}]},
    {"label": "Trainingslager: +260 EXP fürs ganze Team", "eff": [{"k": "exp", "n": 260}]},
    {"label": "Talent-Camp: +3 Skillpunkte auf Talente", "eff": [{"k": "skillpts", "n": 3}]},
    {"label": "Reha-Wunder: alle Verletzten sofort fit", "eff": [{"k": "heal"}]},
    {"label": "Taktik-Coup: Film-Bonus +2 fürs nächste Spiel", "eff": [{"k": "film", "n": 2}]},
    {"label": "Scouting-Offensive: +6 Scouting-Punkte", "eff": [{"k": "scout", "n": 6}]},
    {"label": "Star-Förderung: +2 Attribute auf einen Starter", "eff": [{"k": "attr", "n": 2}]},
    {"label": "Merch-Hit: +5 Mio & +2 Scouting-Punkte", "eff": [{"k": "money", "n": 5}, {"k": "scout", "n": 2}]},
]
_DEBUFFS = [
    {"label": "Verletzung: ein Starter fällt 2 Wochen aus", "eff": [{"k": "injure", "n": 2}]},
    {"label": "Geldstrafe der Liga: -7 Mio Budget", "eff": [{"k": "money", "n": -7}]},
    {"label": "Formtief: -1 Team-Bonus im nächsten Spiel", "eff": [{"k": "film", "n": -1}]},
    {"label": "Trainingsausfall: ein Spieler verliert Fortschritt", "eff": [{"k": "exploss", "n": 130}]},
    {"label": "Scouting-Budget gekürzt: -4 Scouting-Punkte", "eff": [{"k": "scout", "n": -4}]},
]


def _gen_event(state: dict, rng: random.Random) -> None:
    """Erzeugt ein wählbares Event: 2 Buff-Paare + 1 Debuff-Paar (je 1 von 2)."""
    b = rng.sample(_BUFFS, 4)
    d = rng.sample(_DEBUFFS, 2)
    state["pending_event"] = {
        "buffs": [[b[0], b[1]], [b[2], b[3]]],
        "debuff": [d[0], d[1]],
        "title": rng.choice(["Saison-Ereignis", "Front-Office-Entscheidung", "Wochen-Ereignis", "Vereinsmeeting"]),
    }


def _event_view(ev: dict | None) -> dict | None:
    """Nur die Labels fürs Frontend (Effekte bleiben serverseitig)."""
    if not ev:
        return None
    return {"title": ev.get("title", "Ereignis"),
            "buffs": [[o["label"] for o in pair] for pair in ev["buffs"]],
            "debuff": [o["label"] for o in ev["debuff"]]}


def _apply_eff(state: dict, team: dict, effs: list, rng: random.Random, msgs: list) -> None:
    roster = team.get("roster", [])
    for e in effs:
        k, n = e["k"], e.get("n", 0)
        if k == "money":
            state["budget"] = max(0, state["budget"] + n)
            msgs.append({"type": "money" if n >= 0 else "bad", "text": f"Budget {'+' if n >= 0 else ''}{n} Mio."})
        elif k == "scout":
            state["scout_pts"] = max(0, state.get("scout_pts", 0) + n)
            msgs.append({"type": "ok" if n >= 0 else "bad", "text": f"Scouting-Punkte {'+' if n >= 0 else ''}{n}."})
        elif k == "exp":
            for p in roster:
                _gain_exp(p, n)
            msgs.append({"type": "ok", "text": f"+{n} EXP fürs Team."})
        elif k == "skillpts":
            cand = sorted([p for p in roster if player_ovr(p) < player_pot(p)], key=lambda p: p["age"])[:n] or roster[:n]
            for p in cand:
                p["pts"] += 1
            msgs.append({"type": "ok", "text": f"+1 Skillpunkt für {len(cand)} Talente."})
        elif k == "attr":
            starters = [p for p in roster if p["starter"]] or roster
            if starters:
                p = max(starters, key=lambda x: player_pot(x) - player_ovr(x))
                for _ in range(n):
                    under = [a for a in p["attr"] if p["attr"][a] < p["cap"][a]]
                    if under:
                        p["attr"][rng.choice(under)] += 1
                msgs.append({"type": "ok", "text": f"{p['name']}: +{n} Attribut(e)."})
        elif k == "heal":
            h = [p for p in roster if p.get("inj", 0) > 0]
            for p in h:
                p["inj"] = 0
            msgs.append({"type": "ok", "text": f"{len(h)} Spieler sofort geheilt." if h else "Keine Verletzten — Reha ungenutzt."})
        elif k == "film":
            team["game_bonus"] = team.get("game_bonus", 0) + n
            msgs.append({"type": "ok" if n >= 0 else "bad", "text": f"Team-Bonus nächstes Spiel {'+' if n >= 0 else ''}{n}."})
        elif k == "injure":
            healthy = [p for p in roster if p.get("inj", 0) == 0 and p["starter"]] or [p for p in roster if p.get("inj", 0) == 0]
            if healthy:
                p = rng.choice(healthy)
                p["inj"] = max(1, n - (team.get("medical", 1) - 1))   # Medizin verkürzt Ausfallzeit
                msgs.append({"type": "bad", "text": f"{p['name']} ({p['pos']}) fällt {n} Woche(n) aus."})
        elif k == "exploss":
            if roster:
                p = rng.choice(roster)
                p["exp"] = max(0, p["exp"] - n)
                msgs.append({"type": "bad", "text": f"{p['name']} verliert Trainingsfortschritt."})


def resolve_event(cfg: Config, state: dict, b0: int, b1: int, d: int) -> dict:
    """Wendet die gewählten Buffs + Debuff an und schließt das Event ab."""
    ev = state.get("pending_event")
    if not ev:
        return {"error": "Kein offenes Event."}
    team = state["teams"][0]
    rng = random.Random()
    msgs: list[dict] = []
    _apply_eff(state, team, ev["buffs"][0][1 if b0 else 0]["eff"], rng, msgs)
    _apply_eff(state, team, ev["buffs"][1][1 if b1 else 0]["eff"], rng, msgs)
    _apply_eff(state, team, ev["debuff"][1 if d else 0]["eff"], rng, msgs)
    state.pop("pending_event", None)
    _sync_units(team)
    state["events"] = msgs + state.get("events", [])
    save(cfg, state)
    return {"ok": True, "messages": msgs, "view": view(state)}


def standings(state: dict) -> list[dict]:
    rows = [{"name": t["name"], "abbr": t.get("abbr", "?"), "color": t.get("color", "#16c784"),
             "user": t["user"], "w": t["w"], "l": t["l"],
             "pf": t["pf"], "pa": t["pa"], "diff": t["pf"] - t["pa"],
             "ovr": overall(t), "off": offense(t), "def": defense(t),
             "off_scheme": t.get("off_scheme", "Ausgeglichen"),
             "def_scheme": t.get("def_scheme", "Ausgeglichen")} for t in state["teams"]]
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


def _resolve_playoff(state: dict, rng: random.Random, user_result: dict | None = None) -> dict:
    """Wertet die aktuelle Playoff-Runde aus (Bracket-Fortschritt erst in next_week)."""
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
    state["results"].append({"week": po["round"], "games": games})
    state["_po_pending"] = {"round": po["round"], "winners": [g["winner"] for g in games]}
    return {"phase": "playoffs", "round": po["round"], "games": games, "_user_game": user_game}


def _season_awards(state: dict) -> list[dict]:
    """Saison-Auszeichnungen aus den Saisonstatistiken des Nutzer-Teams."""
    roster = state["teams"][0].get("roster", [])
    played = [p for p in roster if p.get("season", {}).get("games", 0) > 0]
    if not played:
        return []

    def offv(p):
        s = p["season"]
        return s["pass_yds"] / 20 + s["pass_td"] * 4 + s["rush_yds"] / 12 + s["rec_yds"] / 12 + s["rec"] + s["td"] * 4

    def defv(p):
        s = p["season"]
        return s["tkl"] + s["sack"] * 3 + s["intc"] * 8

    def line(p):
        s = p["season"]
        o = []
        if s["pass_yds"]:
            o.append(f"{s['pass_yds']} Pass-Yds, {s['pass_td']} TD")
        if s["rush_yds"]:
            o.append(f"{s['rush_yds']} Rush-Yds")
        if s["rec"]:
            o.append(f"{s['rec']} Fänge, {s['rec_yds']} Yds")
        d = []
        if s["tkl"]:
            d.append(f"{s['tkl']} Tkl")
        if s["sack"]:
            d.append(f"{s['sack']} Sacks")
        if s["intc"]:
            d.append(f"{s['intc']} INT")
        if d:
            o.append(", ".join(d))
        return " · ".join(o) or f"{s['games']} Spiele"

    def mk(label, pool, key):
        pool = [p for p in pool if key(p) > 0] or pool
        if not pool:
            return None
        p = max(pool, key=key)
        return {"award": label, "id": p["id"], "name": p["name"], "pos": p["pos"], "line": line(p)}

    aw = []
    for a in [mk("MVP", played, lambda p: offv(p) + defv(p)),
              mk("Offensiv-Spieler des Jahres", played, offv),
              mk("Defensiv-Spieler des Jahres", played, defv),
              mk("Rookie des Jahres", [p for p in played if p["age"] <= 23], lambda p: offv(p) + defv(p)),
              mk("Top-Scorer", played, lambda p: p["season"]["td"] + p["season"]["pass_td"])]:
        if a:
            aw.append(a)
    return aw


def _advance_playoff(state: dict) -> None:
    pend = state.pop("_po_pending", None)
    po = state["playoff"]
    if not pend:
        return
    if pend["round"] == "Halbfinale":
        w = pend["winners"]
        po["round"] = "Finale"
        po["pairs"] = [(w[0], w[1])]
    else:                                                 # Finale -> Meister
        champ = pend["winners"][0]
        state["champion"] = champ
        state["phase"] = "done"
        aw = _season_awards(state)
        state["awards"] = aw
        state["history"].append({"season": state["season"], "champion": champ,
                                 "mvp": (aw[0]["name"] if aw else None)})


def new_season(cfg: Config, state: dict) -> dict:
    """Nächste Saison: Bilanzen zurücksetzen, KI driftet leicht, neuer Spielplan."""
    rng = random.Random()
    for t in state["teams"]:
        t["w"] = t["l"] = t["t"] = t["pf"] = t["pa"] = 0
        if not t["user"]:                                # KI wird jede Saison stärker (bleibt eine Herausforderung)
            for u in ALL_UNITS:
                t["units"][u] = max(50, min(97, t["units"][u] + rng.randint(3, 7)))
            if rng.random() < 0.4:
                t["off_scheme"] = rng.choice(list(OFF_SCHEMES))
            if rng.random() < 0.4:
                t["def_scheme"] = rng.choice(list(DEF_SCHEMES))
        elif t.get("roster"):                            # Nutzer-Kader altert & entwickelt sich
            retired = []
            for p in list(t["roster"]):
                p["age"] += 1
                p["inj"] = 0                              # Verletzungen heilen über die Pause
                p["season"] = _blank_stats()              # Saisonstatistik zurücksetzen (Karriere bleibt)
                if p["age"] >= 35 or (p["age"] >= 33 and rng.random() < 0.5):
                    t["roster"].remove(p)
                    retired.append(p["name"])
                    continue
                ks = list(p["attr"])
                if p["age"] >= 30 and rng.random() < 0.5:              # Veteranen-Abbau
                    k = rng.choice(ks)
                    p["attr"][k] = max(40, p["attr"][k] - rng.randint(1, 2))
                    p["cap"][k] = max(p["attr"][k], p["cap"][k] - 1)
                elif p["age"] <= 25 and rng.random() < 0.6:           # junge Entwicklung
                    under = [k for k in ks if p["attr"][k] < p["cap"][k]]
                    if under:
                        p["attr"][rng.choice(under)] += 1
            _sync_units(t)
            state["_retired"] = retired
    state["season"] += 1
    state["week"] = 0
    state["phase"] = "regular"
    state["playoff"] = None
    state["champion"] = None
    state["awards"] = None
    state["results"] = []
    state["last_user_game"] = None
    state["active_game"] = None
    state["week_trained"] = False
    state["week_done"] = False
    state["teams"][0]["game_bonus"] = 0
    state["schedule"] = _season_schedule(len(state["teams"]), rng)
    state["budget"] += 20                                 # Saisonbudget
    state["coach_market"] = _gen_market(rng)              # neuer Trainermarkt
    state["market_players"] = _draft_class(state, rng)    # neue Draft-/FA-Klasse
    state["prospects"] = _gen_prospects(state, rng)       # neuer College-Jahrgang
    state["scout_pts"] = state.get("scout_pts", 0) + 6    # Scouting-Punkte für die neue Klasse
    state["goals"] = _gen_goals(state)                    # neue Saisonziele
    youth = _youth_talents(state, rng)                    # Jugend-Akademie: eigene Talente pro Saison
    ret = state.pop("_retired", [])
    state["events"] = ([{"type": "bad", "text": f"Karriereende: {n}"} for n in ret]
                       + [{"type": "ok", "text": "Neue Draft-/Free-Agent-Klasse im Transfermarkt verfügbar."}]
                       + youth)
    save(cfg, state)
    return state


def _youth_talents(state: dict, rng: random.Random) -> list[dict]:
    """Jugend-Akademie: pro Saison eigene Talente (Anzahl/Qualität nach Anlagen-Stufe)."""
    team = state["teams"][0]
    lvl = team.get("youth", 1)
    if lvl <= 1:
        return []
    roster = team.get("roster", [])
    used = {p["name"] for p in roster}
    n = 2 if lvl >= 5 else 1
    base = 54 + lvl * 4
    seq = state.get("pid_seq", 10000)
    msgs = []
    for _ in range(n):
        # Position mit freiem Platz bevorzugen, sonst trotzdem ins Talentlager (Prospects)
        free = [g for g in ROSTER_SLOTS if sum(1 for x in roster if x["pos"] == g) < ROSTER_SLOTS[g]]
        pos = rng.choice(free) if free else rng.choice(list(ROSTER_SLOTS))
        p = _gen_player(seq, pos, base, rng, age=rng.randint(20, 22), used=used, hicap=True)
        seq += 1
        if free:
            p["starter"] = False
            roster.append(p)
            msgs.append({"type": "ok", "text": f"Jugend-Akademie: {p['name']} ({pos}) rückt in den Kader auf."})
        else:
            p["scout"] = SCOUT_MAX
            p["_bias"] = 0
            state.setdefault("prospects", []).append(p)
            msgs.append({"type": "ok", "text": f"Jugend-Akademie: Talent {p['name']} ({pos}) im Transfermarkt verfügbar."})
    state["pid_seq"] = seq
    _sync_units(team)
    return msgs


# --------------------------------------------------------------------------- #
# Trainermarkt
# --------------------------------------------------------------------------- #
def _gen_market(rng: random.Random) -> dict:
    return {r: [_gen_coach(r, rng.randint(58, 78), rng) for _ in range(3)] for r in COACH_ROLES}


def hire_coach(cfg: Config, state: dict, role: str, idx: int) -> dict:
    if role not in COACH_ROLES:
        return {"error": "Unbekannte Trainerrolle."}
    market = state.get("coach_market", {}).get(role, [])
    if idx < 0 or idx >= len(market):
        return {"error": "Kandidat nicht verfügbar."}
    cand = market[idx]
    cost = max(6, (coach_rating(cand) - 50) * 2)
    if state["budget"] < cost:
        return {"error": f"Budget zu niedrig (brauchst {cost}, hast {state['budget']})."}
    state["teams"][0]["coaches"][role] = cand
    state["budget"] -= cost
    market[idx] = _gen_coach(role, random.randint(58, 78), random.Random())
    save(cfg, state)
    return {"ok": True, "hired": cand["name"], "cost": cost}


def improve_coach(cfg: Config, state: dict, role: str) -> dict:
    if role not in COACH_ROLES:
        return {"error": "Unbekannte Trainerrolle."}
    c = state["teams"][0]["coaches"][role]
    weakest = min(c["traits"], key=lambda t: c["traits"][t])
    if c["traits"][weakest] >= 92:
        return {"error": "Trainer ist am Maximum."}
    cost = upgrade_cost(coach_rating(c))
    if state["budget"] < cost:
        return {"error": f"Budget zu niedrig (brauchst {cost}, hast {state['budget']})."}
    c["traits"][weakest] = min(92, c["traits"][weakest] + 2)
    state["budget"] -= cost
    save(cfg, state)
    return {"ok": True, "trait": weakest, "value": c["traits"][weakest], "cost": cost}


# --------------------------------------------------------------------------- #
# Transfermarkt (Draft & Free Agency)
# --------------------------------------------------------------------------- #
def sign_player(cfg: Config, state: dict, pid: int) -> dict:
    team = state["teams"][0]
    mk = state.get("market_players", [])
    p = next((x for x in mk if x["id"] == pid), None)
    if not p:
        return {"error": "Spieler nicht verfügbar."}
    pos = p["pos"]
    if sum(1 for x in team["roster"] if x["pos"] == pos) >= ROSTER_SLOTS[pos]:
        return {"error": f"{POS_LABELS[pos]} ist voll ({ROSTER_SLOTS[pos]}) — erst jemanden entlassen."}
    cost = max(8, (player_ovr(p) - 50) * 2)
    if state["budget"] < cost:
        return {"error": f"Budget zu niedrig (brauchst {cost}, hast {state['budget']})."}
    mk.remove(p)
    p["starter"] = False
    team["roster"].append(p)
    state["budget"] -= cost
    _sync_units(team)
    save(cfg, state)
    return {"ok": True, "signed": p["name"], "cost": cost}


def cut_player(cfg: Config, state: dict, pid: int) -> dict:
    team = state["teams"][0]
    p = next((x for x in team["roster"] if x["id"] == pid), None)
    if not p:
        return {"error": "Spieler nicht gefunden."}
    if sum(1 for x in team["roster"] if x["pos"] == p["pos"]) <= 1:
        return {"error": "Letzter Spieler auf der Position kann nicht entlassen werden."}
    team["roster"].remove(p)
    _sync_units(team)
    save(cfg, state)
    return {"ok": True, "cut": p["name"]}


# --------------------------------------------------------------------------- #
# Team-Aufbau (Manager)
# --------------------------------------------------------------------------- #
def upgrade_cost(level: int) -> int:
    return max(5, round((level - 50) * 0.6) + 5)


_FACS = {"stadium": (18, 14), "equipment": (15, 12), "medical": (16, 12),
         "athletic": (15, 11), "scouting_fac": (14, 11), "youth": (18, 13)}


def _fac_cost(team: dict, key: str) -> int:
    b, s = _FACS[key]
    return b + (team.get(key, 1) - 1) * s


def upgrade_unit(cfg: Config, state: dict, key: str) -> dict:
    """Verbessert Einheit (Kader-Aggregat, v.a. KI) oder eine Anlage (Stadion, Trainingsgelände, Medizin, Athletik, Scouting-Akademie, Jugend)."""
    team = state["teams"][0]
    if key in ALL_UNITS:
        store, cap, label = team["units"], 95, UNIT_LABELS[key]
    elif key in _FACS:
        lvl = team.get(key, 1)
        if lvl >= 5:
            return {"error": "Bereits auf Maximum (Stufe 5)."}
        cost = _fac_cost(team, key)
        if state["budget"] < cost:
            return {"error": f"Budget zu niedrig (brauchst {cost}, hast {state['budget']})."}
        team[key] = lvl + 1
        state["budget"] -= cost
        save(cfg, state)
        return {"ok": True, "unit": key, "level": team[key], "cost": cost, "budget": state["budget"]}
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


def alloc(cfg: Config, state: dict, pid: int, attr: str) -> dict:
    res = allocate_point(state["teams"][0], pid, attr)
    if res.get("ok"):
        save(cfg, state)
    return res


def alloc_auto(cfg: Config, state: dict, pid: int) -> dict:
    res = auto_allocate(state["teams"][0], pid)
    if res.get("ok"):
        save(cfg, state)
    return res


def alloc_auto_all(cfg: Config, state: dict) -> dict:
    """Verteilt offene Skillpunkte des ganzen Kaders automatisch."""
    team = state["teams"][0]
    total = 0
    for p in team.get("roster", []):
        if p.get("pts", 0) > 0:
            total += auto_allocate(team, p["id"]).get("spent", 0)
    save(cfg, state)
    return {"ok": True, "spent": total}


def depth_toggle(cfg: Config, state: dict, pid: int) -> dict:
    res = set_starter(state["teams"][0], pid)
    if res.get("ok"):
        save(cfg, state)
    return res


def set_focus(cfg: Config, state: dict, group: str | None) -> dict:
    valid = list(POS_LABELS) + ["Offense", "Defense"]
    state["training_focus"] = group if group in valid else None
    save(cfg, state)
    return {"ok": True, "focus": state["training_focus"]}


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


def _user_form(state: dict, n: int = 8) -> list[dict]:
    """Letzte Spiele des Nutzer-Teams (für Form-Streak & Verlauf)."""
    name = state["teams"][0]["name"]
    out = []
    for r in state.get("results", []):
        for g in r["games"]:
            if g["home"] == name or g["away"] == name:
                home = g["home"] == name
                pf = g["hs"] if home else g["as"]
                pa = g["as"] if home else g["hs"]
                out.append({"week": r["week"], "opp": g["away"] if home else g["home"],
                            "home": home, "won": g["winner"] == name, "pf": pf, "pa": pa})
    return out[-n:]


def _trainings_view(state: dict) -> list[dict]:
    """Trainingskarten inkl. erwartetem EXP-Ertrag (vom Equipment/Coach abhängig)."""
    team = state["teams"][0]
    m = _exp_mult(team)
    grp = {"team": "ganzes Team", "offense": "Offense", "defense": "Defense",
           "single": "Top-Talent", "regen": "Verletzte", "film": "Taktik"}
    exp = {"team": round(150 * m), "offense": round(260 * m),
           "defense": round(260 * m), "single": round(520 * m)}
    return [{**t, "exp": exp.get(t["key"], 0), "group": grp.get(t["key"], "")} for t in TRAININGS]


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
                   "cost": upgrade_cost(team["units"][u]), "side": _unit_side(u)}
                  for u in ALL_UNITS],
        "coaches": [_coach_view(team, r) for r in COACH_ROLES],
        "coach_market": {r: [{"idx": i, "name": c["name"], "rating": coach_rating(c),
                              "cost": max(6, (coach_rating(c) - 50) * 2),
                              "traits": [{"label": t, "val": c["traits"][t]} for t in c["traits"]]}
                             for i, c in enumerate(state.get("coach_market", {}).get(r, []))]
                         for r in COACH_ROLES},
        "stadium": {"level": team.get("stadium", 1),
                    "cost": 18 + (team.get("stadium", 1) - 1) * 14,
                    "income": 6 + 2 * (team.get("stadium", 1) - 1)},
        "equipment": {"level": team.get("equipment", 1),
                      "cost": 15 + (team.get("equipment", 1) - 1) * 12,
                      "exp_week": 10 + 3 * team.get("equipment", 1)},
        "facilities": {
            "medical": {"level": team.get("medical", 1), "cost": _fac_cost(team, "medical"),
                        "effect": f"Verletzungen kürzer (-{team.get('medical', 1) - 1} Wo)" + (" · heilt schneller" if team.get("medical", 1) >= 4 else "")},
            "athletic": {"level": team.get("athletic", 1), "cost": _fac_cost(team, "athletic"),
                         "effect": f"+{(team.get('athletic', 1) - 1) * 12} Regenerations-EXP/Woche"},
            "scouting_fac": {"level": team.get("scouting_fac", 1), "cost": _fac_cost(team, "scouting_fac"),
                             "effect": f"+{team.get('scouting_fac', 1) - 1} Scouting-Punkte/Woche"},
            "youth": {"level": team.get("youth", 1), "cost": _fac_cost(team, "youth"),
                      "effect": ("inaktiv (ab Stufe 2)" if team.get("youth", 1) < 2 else f"{2 if team.get('youth', 1) >= 5 else 1} Talent(e)/Saison, ~{54 + team.get('youth', 1) * 4} OVR")},
        },
        "training_focus": state.get("training_focus"),
        "focus_options": [{"key": k, "label": POS_LABELS[k]} for k in POS_LABELS],
        "skillpoints": sum(p.get("pts", 0) for p in team.get("roster", [])),
        "roster": [_player_view(p) for p in sorted(
            team.get("roster", []),
            key=lambda p: (list(ROSTER_SLOTS).index(p["pos"]), not p["starter"], -player_ovr(p)))],
        "active_game": bool(state.get("active_game")),
        "week_done": bool(state.get("week_done")),
        "tutorial_seen": bool(state.get("tutorial_seen")),
        "goals": [{"label": g["label"], "reward": g["reward"], "done": g["done"], "key": g["key"],
                   "target": g.get("target"), "progress": team["w"] if g["key"] == "wins" else None}
                  for g in state.get("goals", [])],
        "week_trained": bool(state.get("week_trained")),
        "trainings": _trainings_view(state),
        "form": _user_form(state),
        "game_bonus": team.get("game_bonus", 0),
        "is_bye": state["phase"] == "regular" and state["week"] < len(state["schedule"])
        and _user_pair(state) is None,
        "events": state.get("events", []),
        "pending_event": _event_view(state.get("pending_event")),
        "slots": ROSTER_SLOTS,
        "market_players": [{"id": p["id"], "name": p["name"], "pos": p["pos"],
                            "ovr": player_ovr(p), "pot": player_pot(p), "age": p["age"],
                            "cost": max(8, (player_ovr(p) - 50) * 2),
                            "side": "Offense" if p["pos"] in OFF_UNITS else "Defense"}
                           for p in sorted(state.get("market_players", []), key=player_ovr, reverse=True)],
        "scout_pts": state.get("scout_pts", 0),
        "prospects": [prospect_view(p) for p in sorted(
            state.get("prospects", []), key=lambda x: (player_pot(x) + x.get("_bias", 0)), reverse=True)],
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
        "awards": state.get("awards") if state["phase"] == "done" else None,
        "has_last_game": bool(state.get("last_user_game")),
    }


# --------------------------------------------------------------------------- #
# Interaktiver Spielmodus (selbst Plays callen)
# --------------------------------------------------------------------------- #
MAX_DRIVES = GAME_DRIVES
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


def _kickoff_return(rng) -> tuple[int, bool]:
    """Kickoff-Return: meist eigene 15-22, längere Returns immer unwahrscheinlicher, selten TD."""
    r = rng.random()
    if r < 0.60:
        return rng.randint(15, 22), False
    if r < 0.85:
        return rng.randint(23, 30), False
    if r < 0.96:
        return rng.randint(31, 45), False
    if r < 0.995:
        return rng.randint(46, 80), False
    return 100, True


def start_game(cfg: Config, state: dict) -> dict:
    if state.get("active_game"):
        g = state["active_game"]
        if "opts" not in g:                              # alte laufende Spiele nachrüsten
            _new_decision_options(state)
            save(cfg, state)
        return {"ok": True, "game": _game_view(state)}
    if not state.get("week_trained"):
        return {"error": "Erst das Training dieser Woche absolvieren."}
    pair = _user_pair(state)
    if not pair:
        return {"error": "Diese Woche kein Nutzer-Spiel."}
    hi, ai = pair
    teams = state["teams"]
    user_is_home = hi == 0
    # Münzwurf: Gewinner bekommt den Ball (Kickoff-Return)
    user_receives = random.random() < 0.5
    pos = (0 if user_is_home else 1) if user_receives else (1 if user_is_home else 0)
    ret_to, ret_td = _kickoff_return(random)
    g = {
        "hi": hi, "ai": ai, "user_is_home": user_is_home,
        "score": [0, 0], "pos": pos, "drive": 0, "q": 1,
        "down": 1, "dist": 10, "ytz": 75.0,
        "absx": 75.0 if pos == 0 else 25.0,
        "log": [], "over": False, "box": {},
        "off_snaps": 0, "philly_at": random.randint(1, 3), "philly_used": False,  # 🦅 Easter Egg: 1x pro Spiel
        "coin": {"user_receives": user_receives},
        "kickoff": {"return_to": ret_to, "td": ret_td, "by_user": (pos == 0) == user_is_home},
    }
    if ret_td:                                            # Kickoff-Return-Touchdown (selten)
        g["score"][pos] += 7                              # TD + Extra-Punkt
        g["pos"] ^= 1                                     # Gegner bekommt danach den Ball an eigener 25
        pos = g["pos"]
        g["ytz"], g["absx"] = 75.0, (75.0 if pos == 0 else 25.0)
    else:
        g["ytz"] = float(100 - ret_to)                    # Startposition nach Return (eigene ret_to-Linie)
        g["absx"] = float(100 - ret_to) if pos == 0 else float(ret_to)
    state["active_game"] = g
    _new_decision_options(state)
    save(cfg, state)
    return {"ok": True, "game": _game_view(state)}


def _random_off_options() -> list[dict]:
    """4 zufällige Offense-Plays, immer mindestens 1 Lauf und 1 Pass."""
    passes, runs = list(PASS_CONCEPTS), list(RUN_CONCEPTS)
    chosen = [random.choice(passes), random.choice(runs)]
    pool = [k for k in passes + runs if k not in chosen]
    random.shuffle(pool)
    chosen += pool[:2]
    random.shuffle(chosen)
    return [{"key": k, "label": (PASS_CONCEPTS.get(k) or RUN_CONCEPTS[k])["label"],
             "type": "Pass" if k in PASS_CONCEPTS else "Lauf"} for k in chosen]


def _new_decision_options(state: dict) -> None:
    """Erzeugt die Auswahl-Optionen für die aktuelle Spielsituation (einmal pro Snap)."""
    g = state["active_game"]
    if g.get("over"):
        g["opts"] = []
        return
    teams = state["teams"]
    off = teams[g["hi"] if g["pos"] == 0 else g["ai"]]
    user_has_ball = (g["pos"] == 0) == g["user_is_home"]
    if g.get("pat"):                                      # Extra-Punkt / 2-Punkte nach TD
        g["opts"] = [{"key": "__XP__", "label": f"Extra-Punkt (Kick, {round(xp_make_prob(kicker(off)) * 100)}%)", "type": "+1"},
                     {"key": "__2PT__", "label": "2-Punkte-Conversion", "type": "+2"}]
    elif user_has_ball:
        opts = _random_off_options()
        if g["ytz"] <= 50:                                # Field Goal ab ca. Mittellinie
            opts.append({"key": "__FG__", "label": f"Field Goal ({round(g['ytz'] + 17)} Yd, {round(fg_make_prob(g['ytz'], kicker(off)) * 100)}%)", "type": "Kick"})
        g["off_snaps"] = g.get("off_snaps", 0) + 1
        if not g.get("philly_used") and g["off_snaps"] == g.get("philly_at", 2):   # 🦅 genau einmal anbieten
            opts.append({"key": "__PHILLY__", "label": "🦅 Philly Special", "type": "Trick"})
        g["opts"] = opts
    else:                                                 # Defense: 4 zufällige Coverages
        covs = random.sample(list(COVERAGES), min(4, len(COVERAGES)))
        g["opts"] = [{"key": k, "label": COVERAGES[k]["label"], "type": "Coverage"} for k in covs]


def _scheme_pick(team: dict, off: bool) -> str:
    pool = OFF_SCHEMES.get(team.get("off_scheme", "Ausgeglichen"), list(PASS_CONCEPTS)) if off \
        else DEF_SCHEMES.get(team.get("def_scheme", "Ausgeglichen"), list(COVERAGES))
    return random.choice(pool)


# --- Strafen (echte Football-Regeln) -------------------------------------------------
# (Name, Seite, Yards, automatisches First Down, Vor-Snap (kein Play), Spot-Foul, Gewicht)
_PENALTIES = [
    ("False Start", "off", 5, False, True, False, 10),
    ("Delay of Game", "off", 5, False, True, False, 4),
    ("Illegal Formation", "off", 5, False, True, False, 3),
    ("Holding (Offense)", "off", 10, False, False, False, 9),
    ("Illegal Block in the Back", "off", 10, False, False, False, 5),
    ("Offensive Pass Interference", "off", 10, False, False, False, 3),
    ("Offside (Defense)", "def", 5, False, True, False, 8),
    ("Encroachment", "def", 5, False, True, False, 3),
    ("Neutral Zone Infraction", "def", 5, False, True, False, 3),
    ("Defensive Holding", "def", 5, True, False, False, 5),
    ("Defensive Pass Interference", "def", 0, True, False, True, 6),
    ("Face Mask", "def", 15, True, False, False, 4),
    ("Roughing the Passer", "def", 15, True, False, False, 3),
    ("Unnecessary Roughness", "def", 15, True, False, False, 3),
]


def _roll_penalty(rng, rate: float = 0.13):
    """Wirft mit kleiner Wahrscheinlichkeit eine Strafe (gewichtet)."""
    if rng.random() >= rate:
        return None
    tot = sum(p[6] for p in _PENALTIES)
    r = rng.random() * tot
    acc = 0.0
    for name, side, yds, af, pre, spot, w in _PENALTIES:
        acc += w
        if r <= acc:
            return {"name": name, "side": side, "yards": yds,
                    "auto_first": af, "pre_snap": pre, "spot": spot}
    return None


def _apply_penalty(g: dict, pen: dict, o: dict, yards: int,
                   attack_right: bool, off: dict, user_off: bool) -> bool:
    """Wendet eine Strafe an. True = angenommen (ersetzt das Play), False = abgelehnt (Play zählt)."""
    off_pen = (pen["side"] == "off")
    is_td = (not o["turnover"]) and (g["ytz"] - yards <= 0)
    accept = True
    if pen["pre_snap"]:
        accept = True                                   # Vor-Snap-Foul: immer geahndet, kein Snap
    elif off_pen:
        if o["turnover"] or yards < -pen["yards"]:       # Verteidigung lehnt ab, wenn das Play ohnehin schlecht lief
            accept = False
    else:
        gain_first = yards >= g["dist"]
        pen_gain = (min(int(g["ytz"]) - 1, 18) if pen["spot"] else pen["yards"])
        if is_td or (gain_first and yards >= pen_gain and not pen["auto_first"]):
            accept = False                               # Offense lehnt ab, wenn das Play mehr brachte
    if not accept:
        return False
    ytz = float(g["ytz"]); dist = float(g["dist"]); down = g["down"]
    if off_pen:
        ytz = ytz + (100.0 - ytz) / 2 if ytz + pen["yards"] > 99 else ytz + pen["yards"]  # Half-the-distance zur eigenen Goalline
        dist = dist + pen["yards"]
        label = f"🚩 {pen['name']} gegen {off['name']} — {pen['yards']} Yd zurück, Wiederholung {down}. Down"
    else:
        gained = (min(int(ytz) - 1, 18) if pen["spot"] else pen["yards"])
        if ytz - gained < 1:                             # Half-the-distance zur gegnerischen Goalline
            gained = max(1, int(ytz // 2))
        ytz = max(1.0, ytz - gained)
        if pen["auto_first"]:
            down, dist = 1, 10.0
            label = f"🚩 {pen['name']} (Verteidigung) — +{gained} Yd, automatisches First Down"
        else:
            dist = dist - gained
            extra = ""
            if dist <= 0:
                down, dist, extra = 1, 10.0, " — First Down"
            label = f"🚩 {pen['name']} (Verteidigung) — +{gained} Yd{extra}"
    g["ytz"] = round(ytz, 1)
    g["dist"] = round(max(1.0, dist), 1)
    g["down"] = down
    g["absx"] = round((100.0 - g["ytz"]) if attack_right else g["ytz"], 1)
    g["log"].insert(0, {"q": g["q"], "team": off["name"], "desc": label,
                        "hs": g["score"][0], "as_": g["score"][1], "off": user_off, "yards": 0})
    return True


def game_play(cfg: Config, state: dict, choice: str) -> dict:
    g = state.get("active_game")
    if not g or g["over"]:
        return {"error": "Kein laufendes Spiel."}
    teams = state["teams"]
    off_i = g["hi"] if g["pos"] == 0 else g["ai"]
    def_i = g["ai"] if g["pos"] == 0 else g["hi"]
    off, deff = teams[off_i], teams[def_i]
    user_has_ball = (g["pos"] == 0) == g["user_is_home"]

    if g.get("pat"):                                      # Extra-Punkt / 2-Punkte-Conversion offen
        return _resolve_pat(cfg, state, g, off, deff, user_has_ball, choice)
    if choice == "__FG__":                                # Nutzer entscheidet sich fürs Field Goal
        return _attempt_fg(cfg, state, g, off, user_has_ball)

    philly = (choice == "__PHILLY__") and user_has_ball
    if user_has_ball:
        if philly:
            g["philly_used"] = True
            concept, coverage = "Flood", _scheme_pick(deff, off=False)   # Trick-Play, visuell als Pass
        elif choice in PASS_CONCEPTS or choice in RUN_CONCEPTS:
            concept, coverage = choice, _scheme_pick(deff, off=False)
        else:
            return {"error": "Unbekanntes Konzept."}
    else:
        if choice not in COVERAGES:
            return {"error": "Unbekannte Coverage."}
        coverage, concept = choice, _scheme_pick(off, off=True)

    ytz0, dist0 = g["ytz"], g["dist"]                # Feldposition vor dem Snap (für die Animation)
    if philly:                                       # 🦅 Easter Egg: meist großer Raumgewinn
        o = ({"yards": min(int(g["ytz"]), random.randint(16, 38)), "kind": "complete", "turnover": False, "pass": True}
             if random.random() < 0.80 else {"yards": 0, "kind": "incomplete", "turnover": False, "pass": True})
    else:
        o = play_outcome(concept, coverage,
                         {"yardline_100": g["ytz"], "down": g["down"], "ydstogo": g["dist"]}, _RNG)
    yards = max(-12, min(o["yards"], int(g["ytz"])))
    attack_right = (g["pos"] == 1)   # Gast greift nach rechts an, Heim nach links
    # Strafen (nur normale Snaps – nicht bei Trick-Plays/FG/PAT)
    pen = None if philly else _roll_penalty(random)
    if pen and _apply_penalty(g, pen, o, yards, attack_right, off, user_has_ball):
        pen_desc = g["log"][0]["desc"]
        _new_decision_options(state)
        save(cfg, state)
        return {"ok": True, "play": {"desc": pen_desc, "yards": 0, "scored": False, "td": False,
                                     "kind": "penalty", "penalty": True, "user_off": user_has_ball,
                                     "ytz0": round(ytz0), "dist0": round(dist0)},
                "game": _game_view(state)}
    is_td = (not o["turnover"]) and (g["ytz"] - yards <= 0)
    # Box-Score (Nutzer-Team)
    urost = teams[0].get("roster")
    if urost:
        if user_has_ball:
            _attr_off(g.setdefault("box", {}), urost, o, yards, is_td, random)
        else:
            _attr_def(g.setdefault("box", {}), urost, o, random)
    g["absx"] = max(0.0, min(100.0, g["absx"] + (yards if attack_right else -yards)))
    label = _play_label(concept, o, yards)
    if philly:                                            # 🦅 Trick-Play eigenes Label
        label = f"🦅 Philly Special! +{yards}" if o["kind"] == "complete" else "🦅 Philly Special — vereitelt"
    scored = False
    switch = True

    if o["turnover"]:
        pass                                              # Ballverlust -> anderes Team
    elif g["ytz"] - yards <= 0:
        g["score"][g["pos"]] += 6                         # TD = 6, danach Extra-Punkt/2-Punkte
        g["absx"] = 100.0 if attack_right else 0.0
        label = ("🦅 Philly Special — " if philly else "") + "TOUCHDOWN! " + off["name"]
        scored = True
        if user_has_ball:
            g["pat"] = {"pos": g["pos"]}                  # Nutzer wählt XP/2PT -> noch kein Wechsel
            switch = False
        else:                                             # KI: Extra-Punkt automatisch
            if random.random() < xp_make_prob(kicker(off)):
                g["score"][g["pos"]] += 1
                label += " + Extra-Punkt"
            else:
                label += " (Extra-Punkt daneben)"
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
                if not user_has_ball and g["ytz"] <= 45:          # KI: Field Goal im Bereich
                    if random.random() < fg_make_prob(g["ytz"], kicker(off)):
                        g["score"][g["pos"]] += 3
                        label = f"Field Goal gut aus {round(g['ytz'] + 17)} Yd (+3)"
                        scored = True
                    else:
                        label = f"Field Goal daneben aus {round(g['ytz'] + 17)} Yd"
                else:
                    label = "4th Down vergeben — Ballverlust"
            else:
                switch = False

    g["log"].insert(0, {"q": g["q"], "team": off["name"], "desc": label,
                        "hs": g["score"][0], "as_": g["score"][1],
                        "off": user_has_ball, "yards": yards})

    if switch:
        _switch_possession(g)

    _new_decision_options(state)                          # Optionen für den nächsten Snap
    save(cfg, state)
    return {"ok": True, "play": {"desc": label, "yards": yards, "scored": scored, "td": is_td,
                                 "kind": o["kind"], "concept": concept, "coverage": coverage,
                                 "user_off": user_has_ball, "ytz0": round(ytz0), "dist0": round(dist0)},
            "game": _game_view(state)}


def _switch_possession(g: dict) -> None:
    """Ballwechsel: neuer Drive für das andere Team an der eigenen 25."""
    g["pos"] ^= 1
    g["drive"] += 1
    g["q"] = min(4, g["drive"] // (MAX_DRIVES // 4 or 1) + 1)
    g["down"], g["dist"], g["ytz"] = 1, 10, 75.0
    g["absx"] = 75.0 if g["pos"] == 0 else 25.0
    if g["drive"] >= MAX_DRIVES:
        g["over"] = True


def _pat_log(g: dict, off: dict, label: str, user_off: bool) -> None:
    g["log"].insert(0, {"q": g["q"], "team": off["name"], "desc": label,
                        "hs": g["score"][0], "as_": g["score"][1], "off": user_off, "yards": 0})


def _resolve_pat(cfg: Config, state: dict, g: dict, off: dict, deff: dict,
                 user_off: bool, choice: str) -> dict:
    """Extra-Punkt (Kick) oder 2-Punkte-Conversion nach einem Touchdown."""
    pos = g.pop("pat")["pos"]
    if choice == "__2PT__":
        edge = 0.10 * (offense(off) - defense(deff))
        good = random.random() < max(0.30, min(0.66, 0.46 + edge * 0.04))
        label = "2-Punkte-Conversion gut! (+2)" if good else "2-Punkte-Conversion gescheitert"
        if good:
            g["score"][pos] += 2
        kind, fg_dist = "pat", 0                          # 2PT: keine Kick-Animation
    else:                                                 # Extra-Punkt-Kick
        good = random.random() < xp_make_prob(kicker(off))
        label = "Extra-Punkt gut (+1)" if good else "Extra-Punkt daneben"
        if good:
            g["score"][pos] += 1
        kind, fg_dist = "fg", 18                          # Kick-Animation (Extra-Punkt)
    _pat_log(g, off, label, user_off)
    _switch_possession(g)
    _new_decision_options(state)
    save(cfg, state)
    return {"ok": True, "play": {"desc": label, "yards": 0, "scored": True, "good": good, "kind": kind,
                                 "fg_dist": fg_dist, "concept": None, "coverage": None, "user_off": user_off},
            "game": _game_view(state)}


def _attempt_fg(cfg: Config, state: dict, g: dict, off: dict, user_off: bool) -> dict:
    """Vom Nutzer gewählter Field-Goal-Versuch (Trefferchance = Distanz + Kicker)."""
    ytz = g["ytz"]
    if ytz > 55:
        return {"error": "Zu weit für ein Field Goal."}
    dist = round(ytz + 17)
    if random.random() < fg_make_prob(ytz, kicker(off)):
        g["score"][g["pos"]] += 3
        label = f"Field Goal gut aus {dist} Yd (+3)"
        scored = True
    else:
        label = f"Field Goal daneben aus {dist} Yd"
        scored = False
    _pat_log(g, off, label, user_off)
    _switch_possession(g)
    _new_decision_options(state)
    save(cfg, state)
    return {"ok": True, "play": {"desc": label, "yards": 0, "scored": scored, "good": scored, "kind": "fg",
                                 "fg_dist": dist, "concept": None, "coverage": None, "user_off": user_off},
            "game": _game_view(state)}


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


def end_game(cfg: Config, state: dict) -> dict:
    """Beendet das laufende Spiel (z. B. wenn die Spieluhr abläuft) und wertet es."""
    g = state.get("active_game")
    if not g:
        return {"error": "Kein Spiel aktiv."}
    g["over"] = True
    save(cfg, state)
    return finish_game(cfg, state)


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
    # Leistungs-EXP aus dem selbst gespielten Spiel + Box-Score
    box = g.get("box", {})
    rid = {p["id"]: p for p in teams[0].get("roster", [])}
    for pid, s in box.items():
        if pid in rid:
            _gain_exp(rid[pid], _box_exp(s))
    _accumulate(rid, box)
    box_lines = [b for b in sorted(box.values(), key=_box_exp, reverse=True) if _box_exp(b) > 0][:10]
    state["active_game"] = None
    out = sim_week(cfg, state, user_result=result)
    result["box"] = box_lines
    return {"ok": True, "result": result, "advance": out, "view": view(state)}


def abort_game(cfg: Config, state: dict) -> dict:
    state["active_game"] = None
    save(cfg, state)
    return {"ok": True}


def _auto_choice(state: dict) -> str:
    """Sinnvolle automatische Spielzug-Wahl (für Sim-Buttons)."""
    g = state["active_game"]
    if g.get("pat"):
        return "__XP__"                                   # automatischer Extra-Punkt
    user_has_ball = (g["pos"] == 0) == g["user_is_home"]
    if user_has_ball and g["down"] >= 4 and g["ytz"] <= 45:
        return "__FG__"                                   # 4th Down in Reichweite -> Field Goal
    return _scheme_pick(state["teams"][0], off=user_has_ball)


def game_sim_drive(cfg: Config, state: dict) -> dict:
    """Spielt den aktuellen Ballbesitz automatisch aus (bis Possession-Wechsel/Ende)."""
    g = state.get("active_game")
    if not g or g["over"]:
        return {"error": "Kein laufendes Spiel."}
    start, guard = g["pos"], 0
    while not state["active_game"]["over"] and state["active_game"]["pos"] == start and guard < 60:
        game_play(cfg, state, _auto_choice(state))
        guard += 1
    if state["active_game"]["over"]:
        return finish_game(cfg, state)
    return {"ok": True, "game": _game_view(state)}


def game_sim_rest(cfg: Config, state: dict) -> dict:
    """Simuliert das restliche Spiel automatisch zu Ende und wertet es."""
    g = state.get("active_game")
    if not g:
        return {"error": "Kein laufendes Spiel."}
    guard = 0
    while not state["active_game"]["over"] and guard < 400:
        game_play(cfg, state, _auto_choice(state))
        guard += 1
    return finish_game(cfg, state)


def _game_view(state: dict) -> dict:
    g = state["active_game"]
    teams = state["teams"]
    home, away = teams[g["hi"]], teams[g["ai"]]
    off_i = g["hi"] if g["pos"] == 0 else g["ai"]
    off = teams[off_i]
    user_has_ball = (g["pos"] == 0) == g["user_is_home"]
    pat = bool(g.get("pat"))
    if "opts" not in g:                                   # Fallback (z. B. altes Spiel)
        _new_decision_options(state)
    opts = g.get("opts", [])
    return {
        "home": home["name"], "away": away["name"],
        "habbr": home.get("abbr", "HOM"), "aabbr": away.get("abbr", "AWY"),
        "hcolor": home.get("color", "#16c784"), "acolor": away.get("color", "#ef5350"),
        "hs": g["score"][0], "as": g["score"][1], "q": g["q"],
        "down": g["down"], "dist": g["dist"], "ytz": round(g["ytz"]), "absx": round(g["absx"], 1),
        "drive": g["drive"], "max_drives": MAX_DRIVES, "over": g["over"],
        "possession": teams[off_i]["name"], "user_offense": user_has_ball,
        "awaiting": "pat" if pat else ("offense" if user_has_ball else "defense"),
        "pat": pat, "kicker": kicker(teams[0]),
        "options": opts, "log": g["log"][:12],
        "user_is_home": g["user_is_home"],
        "coin": g.get("coin"), "kickoff": g.get("kickoff"),
    }
