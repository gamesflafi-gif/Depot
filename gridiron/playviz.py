"""Spielzug-Geometrie für die visuelle Darstellung (Play-Art).

Liefert für ein Offense-Konzept gegen eine Coverage die Positionen aller 22
Spieler plus die Routen der Receiver und die Zonen-Drops der Defense — als
Koordinaten in Yards (Line of Scrimmage = y 0, downfield positiv). Das Frontend
zeichnet daraus ein animiertes Spielfeld. Football-Wissen liegt hier zentral und
ist damit testbar; die Engine-Logik (Erträge) bleibt im simulator.
"""
from __future__ import annotations

from gridiron.simulator import COVERAGES, PASS_CONCEPTS, RUN_CONCEPTS

W = 53.3            # Feldbreite (Yards)
C = 26.65           # Mitte

# Offensive Grundausrichtung (Shotgun, 11 Personnel) – feste Startpositionen.
POS = {
    "LT": (23.05, 0.0), "LG": (24.85, 0.0), "C": (26.65, 0.0),
    "RG": (28.45, 0.0), "RT": (30.25, 0.0),
    "QB": (26.65, -5.0), "RB": (24.5, -6.0),
    "X": (5.0, 0.0), "Z": (49.0, 0.0), "SL": (40.0, -1.0), "TE": (32.2, 0.0),
}
OL = ["LT", "LG", "C", "RG", "RT"]
SKILL = ["X", "Z", "SL", "TE", "RB"]


def _dirs(sx: float):
    """inside = Richtung Mitte (+1/-1), sideline = Gegenrichtung."""
    inside = 1.0 if sx < C else -1.0
    return inside, -inside


def _route(name: str, start: tuple[float, float]) -> list[list[float]]:
    sx, sy = start
    ins, side = _dirs(sx)
    R = {
        "go":      [(sx, sy), (sx, 22)],
        "seam":    [(sx, sy), (sx, 20)],
        "post":    [(sx, sy), (sx, 11), (sx + ins * 7, 19)],
        "corner":  [(sx, sy), (sx, 11), (sx + side * 7, 18)],
        "dig":     [(sx, sy), (sx, 12), (sx + ins * 15, 12)],
        "out":     [(sx, sy), (sx, 7), (sx + side * 8, 7)],
        "slant":   [(sx, sy), (sx + ins * 6, 5)],
        "flat":    [(sx, sy), (sx + side * 6, 1.5)],
        "hitch":   [(sx, sy), (sx, 7), (sx, 5.5)],
        "comeback":[(sx, sy), (sx, 14), (sx + side * 2, 12)],
        "drag":    [(sx, sy), (sx + ins * 18, 3)],
        "cross":   [(sx, sy), (sx, 3), (sx + ins * 22, 13)],
        "wheel":   [(sx, sy), (sx + side * 3, 2), (sx + side * 3, 17)],
        "stick":   [(sx, sy), (sx, 6), (sx + side * 3, 6)],
        "sail":    [(sx, sy), (sx, 9), (sx + side * 9, 13)],
        "snag":    [(sx, sy), (sx + ins * 6, 5), (sx + ins * 4, 4)],
        "swing":   [(sx, sy), (sx + side * 7, -4)],
        "checkdown":[(sx, sy), (sx + ins * 3, 2)],
        "bubble":  [(sx, sy), (sx + side * 3, -1.5), (sx + side * 7, -0.5)],
        "screen":  [(sx, sy), (sx + 3.5, -2.5), (sx + 6, -2)],
        "block":   [(sx, sy), (sx, sy)],
    }
    return [[round(x, 2), round(y, 2)] for x, y in R[name]]


# Konzept -> {Receiver: Routenname}, target = primäre Anspielstation.
_PASS_ROUTES = {
    "Four Verts": ({"X": "go", "Z": "go", "SL": "seam", "TE": "seam", "RB": "checkdown"}, "SL"),
    "Mesh":       ({"X": "drag", "TE": "drag", "SL": "corner", "Z": "comeback", "RB": "flat"}, "X"),
    "Smash":      ({"Z": "hitch", "SL": "corner", "X": "slant", "TE": "block", "RB": "flat"}, "SL"),
    "Flood":      ({"Z": "go", "SL": "sail", "TE": "flat", "X": "comeback", "RB": "block"}, "SL"),
    "Slant-Flat": ({"X": "slant", "RB": "flat", "Z": "slant", "SL": "flat", "TE": "block"}, "X"),
    "Stick":      ({"TE": "stick", "SL": "flat", "X": "hitch", "Z": "hitch", "RB": "checkdown"}, "TE"),
    "Y-Cross":    ({"TE": "cross", "X": "go", "SL": "dig", "Z": "comeback", "RB": "checkdown"}, "TE"),
    "Dagger":     ({"SL": "seam", "X": "dig", "Z": "comeback", "TE": "block", "RB": "flat"}, "X"),
    "Drive":      ({"X": "drag", "SL": "dig", "Z": "hitch", "TE": "block", "RB": "checkdown"}, "SL"),
    "Spacing":    ({"X": "hitch", "SL": "snag", "TE": "flat", "Z": "hitch", "RB": "flat"}, "SL"),
    "RB Screen":  ({"RB": "screen", "X": "hitch", "Z": "hitch", "SL": "block", "TE": "block"}, "RB"),
    "WR Screen":  ({"Z": "bubble", "SL": "block", "TE": "block", "X": "hitch", "RB": "block"}, "Z"),
}

# Laufkonzept -> RB-Pfad (absolute Wegpunkte) und optionale Puller.
def _run_path(concept: str) -> dict:
    rbx, rby = POS["RB"]
    paths = {
        "Inside Zone":  [(rbx, rby), (C + 1.2, 0.5), (C + 1.5, 6)],
        "Outside Zone": [(rbx, rby), (C + 4, -0.5), (38, 2), (40, 8)],
        "Power":        [(rbx, rby), (C + 2, 0), (C + 2.5, 7)],
        "Counter":      [(rbx, rby), (rbx - 2, -5.5), (C + 3, 0.5), (C + 3, 6)],
        "Draw":         [(rbx, rby), (C, -4), (C, 1), (C, 6)],
        "Toss":         [(rbx, rby), (18, -5), (12, 0), (12, 7)],
        "Trap":         [(rbx, rby), (C + 0.5, 0.5), (C + 0.8, 6)],
    }
    pull = {"Power": ["LG"], "Counter": ["RG", "TE"], "Toss": ["RT"]}.get(concept, [])
    return {"path": [[round(x, 2), round(y, 2)] for x, y in paths[concept]], "pull": pull}


# Defense: Grundfront + Coverage-spezifische Safeties/Drops.
def _defense(coverage: str) -> list[dict]:
    man = COVERAGES[coverage]["man"]
    blitz = COVERAGES[coverage]["blitz"] >= 0.9
    dl = [("DE", 21.5, 0.8), ("DT", 25.3, 0.8), ("DT", 28.0, 0.8), ("DE", 31.8, 0.8)]
    lb = [("LB", 23.5, 4.5), ("LB", 26.65, 4.8), ("LB", 32.0, 4.5)]
    cbL, cbR = ("CB", 6.0, 6.0), ("CB", 48.0, 6.0)

    cov = {
        "Cover 0":    {"S": [(24.0, 4.5), (30.0, 4.5)], "cb": 1.8, "blitz": True},
        "Cover 1":    {"S": [(C, 13.0), (25.0, 5.5)], "cb": 2.5},
        "Cover 2 Man":{"S": [(16.0, 13.0), (37.0, 13.0)], "cb": 2.2},
        "Cover 2":    {"S": [(16.0, 13.0), (37.0, 13.0)], "cb": 6.0, "cbdrop": (None, 9)},
        "Tampa 2":    {"S": [(16.0, 13.5), (37.0, 13.5)], "cb": 6.0, "mlb_deep": True},
        "Cover 3":    {"S": [(C, 15.0), (31.0, 6.0)], "cb": 6.0, "cb3deep": True},
        "Cover 4":    {"S": [(19.0, 14.0), (34.0, 14.0)], "cb": 7.0, "cb4deep": True},
        "Cover 6":    {"S": [(15.0, 13.5), (36.0, 14.0)], "cb": 6.5, "cb6": True},
    }[coverage]

    out: list[dict] = []
    for pos, x, y in dl:
        d = {"pos": pos, "x": x, "y": y, "man": False}
        if blitz:
            d["drop"] = [round(C + (x - C) * 0.3, 2), -4.0]   # Pass-Rush
        out.append(d)

    # Linebacker
    for i, (pos, x, y) in enumerate(lb):
        d = {"pos": pos, "x": x, "y": y, "man": man and not blitz}
        if blitz and i == 1:
            d["drop"] = [C, -3.0]
        elif cov.get("mlb_deep") and i == 1:
            d["drop"] = [C, 14.0]
        elif not man:
            d["drop"] = [round(x + (C - x) * 0.2, 2), 8.0]   # Zonen-Drop in die Underneath
        out.append(d)

    # Corners
    cb_y = cov["cb"]
    for (pos, x, _y), deep_x in ((cbL, 8.0), (cbR, 45.0)):
        d = {"pos": pos, "x": x, "y": cb_y, "man": man}
        if cov.get("cb3deep") or cov.get("cb4deep"):
            d["drop"] = [deep_x, 16.0]
        elif cov.get("cbdrop"):
            d["drop"] = [x, 9.0]
        elif cov.get("cb6"):
            d["drop"] = [deep_x, 15.0] if x > C else [x, 9.0]
        out.append(d)

    # Safeties
    for sx, sy in cov["S"]:
        out.append({"pos": "S", "x": round(sx, 2), "y": round(sy, 2),
                    "man": False, "deep": sy >= 11})
    return out


def diagram(concept: str, coverage: str) -> dict:
    if coverage not in COVERAGES:
        raise ValueError(f"Unbekannte Coverage: {coverage}")
    is_pass = concept in PASS_CONCEPTS
    if not is_pass and concept not in RUN_CONCEPTS:
        raise ValueError(f"Unbekanntes Konzept: {concept}")

    offense: list[dict] = []
    for k in OL:
        offense.append({"pos": "OL", "x": POS[k][0], "y": POS[k][1], "route": None})
    offense.append({"pos": "QB", "x": POS["QB"][0], "y": POS["QB"][1], "route": None})

    ball_target = None
    if is_pass:
        routes, target = _PASS_ROUTES[concept]
        for k in SKILL:
            rname = routes.get(k, "block")
            r = _route(rname, POS[k])
            is_target = (k == target)
            offense.append({"pos": k, "x": POS[k][0], "y": POS[k][1],
                            "route": r, "rname": rname, "target": is_target})
            if is_target:
                ball_target = r[-1]
        kind = "pass"
    else:
        run = _run_path(concept)
        # RB läuft den Pfad, andere Skill-Spieler blocken/stehen
        for k in SKILL:
            if k == "RB":
                offense.append({"pos": "RB", "x": POS[k][0], "y": POS[k][1],
                                "route": run["path"], "rname": "run", "carry": True})
            else:
                offense.append({"pos": k, "x": POS[k][0], "y": POS[k][1], "route": None})
        ball_target = run["path"][-1]
        kind = "run"

    return {
        "concept": concept, "coverage": coverage, "kind": kind,
        "coverage_label": COVERAGES[coverage]["label"],
        "offense": offense, "defense": _defense(coverage),
        "ball_target": ball_target, "width": W,
    }
