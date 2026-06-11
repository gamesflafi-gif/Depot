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
# Seitenlinien liegen bei x≈1.2 und x≈52.1 (Frontend). Spieler-/Routen-x bleibt im Feld,
# mit etwas Rand, damit keine Figur über die Linie ragt.
IN_LO, IN_HI = 2.6, 50.7


def _clampx(x: float) -> float:
    return min(IN_HI, max(IN_LO, x))

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
    # x immer im Feld halten (Routen nahe der Seitenlinie liefen sonst ins Aus)
    return [[round(_clampx(x), 2), round(y, 2)] for x, y in R[name]]


# Routen, die Manndeckung gut schlagen (Tempo-/Trennungs-Routen).
_MAN_BEATERS = {"slant", "drag", "cross", "post", "corner", "go", "seam",
                "wheel", "out", "sail", "dig", "snag"}


def _open_receiver(skill_routes: dict, defense: list[dict], primary: str) -> str:
    """Wählt den Receiver mit der größten Separation gegen die gegebene Coverage.

    So wirft der QB nicht stur auf die primäre Route, sondern auf den, der gegen
    die jeweilige Deckung frei wird – Manndeckung wird von Tempo-Routen geschlagen,
    Zonendeckung von Receivern in den Lücken zwischen den Drops.
    """
    best, best_score = primary, -1e9
    for k, (rname, r) in skill_routes.items():
        if rname == "block":
            continue
        cx, cy = r[-1]                       # Fangpunkt
        sep = 8.0                            # ungedeckt = großzügige Trennung
        for d in defense:
            if d.get("role") == "rush":
                continue
            cov = d.get("cover")
            if cov:                          # Manndeckung
                if cov == k:
                    base = 1.2 + (2.8 if rname in _MAN_BEATERS else 0.0)
                    sep = min(sep, base)
            elif d.get("drop"):              # Zonendeckung -> Abstand zur Landmarke
                dx, dy = cx - d["drop"][0], cy - d["drop"][1]
                sep = min(sep, (dx * dx + dy * dy) ** 0.5)
        score = sep + (0.6 if k == primary else 0.0)   # leichter Bonus auf die Erstoption
        if score > best_score:
            best, best_score = k, score
    return best


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
    "Curls":      ({"X": "comeback", "Z": "hitch", "SL": "stick", "TE": "hitch", "RB": "flat"}, "X"),
    "Levels":     ({"SL": "drag", "X": "dig", "Z": "go", "TE": "block", "RB": "checkdown"}, "X"),
    "Post-Wheel": ({"Z": "post", "RB": "wheel", "X": "go", "SL": "dig", "TE": "block"}, "RB"),
    "Shallow":    ({"X": "drag", "TE": "dig", "SL": "go", "Z": "comeback", "RB": "checkdown"}, "X"),
    "Double Outs":({"X": "out", "Z": "out", "SL": "hitch", "TE": "stick", "RB": "flat"}, "X"),
    "PA Boot":    ({"TE": "flat", "SL": "corner", "X": "comeback", "Z": "go", "RB": "swing"}, "SL"),
}

# Aufstellungen: pro Play eine echte Formation (verschiebt Skill-Spieler/QB-Tiefe).
FORMATIONS = {
    "Shotgun":    {},
    "Singleback": {"QB": (26.65, -1.6)},
    "I-Form":     {"QB": (26.65, -1.6), "RB": (26.65, -7.6)},
    "Trips Re":   {"X": (5.0, 0.0), "TE": (39.0, -0.6), "SL": (44.0, -0.6), "Z": (49.0, 0.0)},
    "Empty":      {"QB": (26.65, -5.0), "RB": (11.0, -0.4)},
}
_PASS_FORMS = ["Shotgun", "Trips Re", "Empty", "Singleback"]
_RUN_FORMS = ["Singleback", "I-Form", "Shotgun"]


def _formation(concept: str, is_pass: bool) -> tuple[str, dict]:
    """Deterministische, zum Konzept passende Formation (gleiches Konzept -> gleicher Look)."""
    forms = _PASS_FORMS if is_pass else _RUN_FORMS
    name = forms[sum(ord(c) for c in concept) % len(forms)]
    return name, FORMATIONS[name]


# Laufkonzept -> RB-Pfad (absolute Wegpunkte) und optionale Puller.
def _run_path(concept: str, rb: tuple[float, float]) -> dict:
    rbx, rby = rb
    paths = {
        "Inside Zone":  [(rbx, rby), (C + 1.2, 0.5), (C + 1.5, 6)],
        "Outside Zone": [(rbx, rby), (C + 4, -0.5), (38, 2), (40, 8)],
        "Power":        [(rbx, rby), (C + 2, 0), (C + 2.5, 7)],
        "Counter":      [(rbx, rby), (rbx - 2, -5.5), (C + 3, 0.5), (C + 3, 6)],
        "Draw":         [(rbx, rby), (C, -4), (C, 1), (C, 6)],
        "Toss":         [(rbx, rby), (18, -5), (12, 0), (12, 7)],
        "Trap":         [(rbx, rby), (C + 0.5, 0.5), (C + 0.8, 6)],
        "Dive":         [(rbx, rby), (C + 0.8, 0.4), (C + 1.0, 6)],
        "Sweep":        [(rbx, rby), (C + 5, -0.8), (40, 1), (43, 7)],
        "Iso":          [(rbx, rby), (C + 1.6, 0), (C + 1.8, 7)],
        "Pin & Pull":   [(rbx, rby), (C + 4, -0.5), (39, 2), (41, 8)],
    }
    pull = {"Power": ["LG"], "Counter": ["RG", "TE"], "Toss": ["RT"],
            "Sweep": ["LG", "RG"], "Pin & Pull": ["RT", "RG"]}.get(concept, [])
    return {"path": [[round(_clampx(x), 2), round(y, 2)] for x, y in paths[concept]], "pull": pull}


# Defense: jede Coverage als 11 Spieler mit Rolle:
#   role "rush" -> stürmt den QB · "man" + cover=Receiver -> Manndeckung
#   role "zone" + drop=[x,y] -> Zonen-Drop (deep=True färbt tiefe Safetys).
def _D(pos, x, y, role, cover=None, drop=None, deep=False) -> dict:
    d = {"pos": pos, "x": round(x, 2), "y": round(y, 2), "role": role, "deep": deep}
    if cover:
        d["cover"] = cover
    if drop:
        d["drop"] = [round(drop[0], 2), round(drop[1], 2)]
    return d


def _defense(coverage: str) -> list[dict]:
    # Grundfront (4 DL stürmen immer)
    out = [_D("DE", 21.5, 0.8, "rush"), _D("DT", 25.3, 0.8, "rush"),
           _D("DT", 28.0, 0.8, "rush"), _D("DE", 31.8, 0.8, "rush")]
    LB = [(23.5, 4.6), (26.65, 4.9), (32.0, 4.6)]        # Will, Mike, Sam
    CBL, CBR = (6.0, 6.0), (48.0, 6.0)

    if coverage == "Cover 0":                            # Mann, All-Out-Blitz
        out += [_D("CB", *CBL, "man", cover="X"), _D("CB", *CBR, "man", cover="Z"),
                _D("S", 22.0, 8.0, "man", cover="SL"), _D("S", 31.0, 8.0, "man", cover="TE"),
                _D("LB", *LB[0], "man", cover="RB"),
                _D("LB", *LB[1], "rush"), _D("LB", *LB[2], "rush")]
    elif coverage == "Cover 1":                          # Mann mit Free Safety
        out += [_D("S", C, 13.5, "zone", drop=[C, 15.0], deep=True),
                _D("CB", *CBL, "man", cover="X"), _D("CB", *CBR, "man", cover="Z"),
                _D("S", 30.0, 7.0, "man", cover="SL"),
                _D("LB", *LB[0], "man", cover="TE"), _D("LB", *LB[2], "man", cover="RB"),
                _D("LB", *LB[1], "zone", drop=[C, 7.0])]
    elif coverage == "Cover 2 Man":                      # 2 Deep, Mann drunter
        out += [_D("S", 16.0, 13.0, "zone", drop=[16.0, 15.0], deep=True),
                _D("S", 37.0, 13.0, "zone", drop=[37.0, 15.0], deep=True),
                _D("CB", *CBL, "man", cover="X"), _D("CB", *CBR, "man", cover="Z"),
                _D("LB", *LB[0], "man", cover="RB"), _D("LB", *LB[1], "man", cover="TE"),
                _D("LB", *LB[2], "man", cover="SL")]
    elif coverage in ("Cover 2", "Tampa 2"):
        mlb_deep = coverage == "Tampa 2"
        out += [_D("S", 15.0, 13.0, "zone", drop=[14.0, 15.5], deep=True),
                _D("S", 38.0, 13.0, "zone", drop=[39.0, 15.5], deep=True),
                _D("CB", *CBL, "zone", drop=[7.0, 7.0]), _D("CB", *CBR, "zone", drop=[46.0, 7.0]),
                _D("LB", *LB[0], "zone", drop=[18.0, 9.0]),
                _D("LB", *LB[1], "zone", drop=[C, 16.0] if mlb_deep else [C, 9.5], deep=mlb_deep),
                _D("LB", *LB[2], "zone", drop=[35.0, 9.0])]
    elif coverage == "Cover 3":
        out += [_D("CB", *CBL, "zone", drop=[8.0, 16.0], deep=True),
                _D("CB", *CBR, "zone", drop=[45.0, 16.0], deep=True),
                _D("S", C, 14.0, "zone", drop=[C, 17.0], deep=True),
                _D("S", 33.0, 7.0, "zone", drop=[36.0, 9.0]),
                _D("LB", *LB[0], "zone", drop=[17.0, 9.0]),
                _D("LB", *LB[1], "zone", drop=[C, 9.0]),
                _D("LB", *LB[2], "zone", drop=[34.0, 8.0])]
    elif coverage == "Cover 4":
        out += [_D("CB", *CBL, "zone", drop=[8.0, 15.0], deep=True),
                _D("CB", *CBR, "zone", drop=[45.0, 15.0], deep=True),
                _D("S", 19.0, 13.0, "zone", drop=[19.0, 16.0], deep=True),
                _D("S", 34.0, 13.0, "zone", drop=[34.0, 16.0], deep=True),
                _D("LB", *LB[0], "zone", drop=[18.0, 8.0]),
                _D("LB", *LB[1], "zone", drop=[C, 8.5]),
                _D("LB", *LB[2], "zone", drop=[35.0, 8.0])]
    else:  # Cover 6 (Quarter-Quarter-Half)
        out += [_D("CB", *CBL, "zone", drop=[8.0, 13.0]),
                _D("CB", *CBR, "zone", drop=[45.0, 16.0], deep=True),
                _D("S", 15.0, 13.0, "zone", drop=[14.0, 16.0], deep=True),
                _D("S", 36.0, 13.0, "zone", drop=[37.0, 16.0], deep=True),
                _D("LB", *LB[0], "zone", drop=[18.0, 8.0]),
                _D("LB", *LB[1], "zone", drop=[C, 9.0]),
                _D("LB", *LB[2], "zone", drop=[34.0, 8.0])]
    return out


def diagram(concept: str, coverage: str) -> dict:
    if coverage not in COVERAGES:
        raise ValueError(f"Unbekannte Coverage: {coverage}")
    is_pass = concept in PASS_CONCEPTS
    if not is_pass and concept not in RUN_CONCEPTS:
        raise ValueError(f"Unbekanntes Konzept: {concept}")

    fname, fov = _formation(concept, is_pass)
    pos = {**POS, **fov}                                  # Aufstellung dieses Plays

    offense: list[dict] = []
    for k in OL:
        offense.append({"pos": "OL", "x": pos[k][0], "y": pos[k][1], "route": None})
    offense.append({"pos": "QB", "x": pos["QB"][0], "y": pos["QB"][1], "route": None})

    defense = _defense(coverage)
    ball_target = None
    if is_pass:
        routes, primary = _PASS_ROUTES[concept]
        skill_routes = {k: (routes.get(k, "block"), _route(routes.get(k, "block"), pos[k]))
                        for k in SKILL}
        target = _open_receiver(skill_routes, defense, primary)   # offene Anspielstation
        for k in SKILL:
            rname, r = skill_routes[k]
            is_target = (k == target)
            offense.append({"pos": k, "x": pos[k][0], "y": pos[k][1],
                            "route": r, "rname": rname, "target": is_target})
            if is_target:
                ball_target = r[-1]
        kind = "pass"
    else:
        run = _run_path(concept, pos["RB"])
        # RB läuft den Pfad, andere Skill-Spieler blocken/stehen
        for k in SKILL:
            if k == "RB":
                offense.append({"pos": "RB", "x": pos[k][0], "y": pos[k][1],
                                "route": run["path"], "rname": "run", "carry": True})
            else:
                offense.append({"pos": k, "x": pos[k][0], "y": pos[k][1], "route": None})
        ball_target = run["path"][-1]
        kind = "run"

    return {
        "concept": concept, "coverage": coverage, "kind": kind, "formation": fname,
        "coverage_label": COVERAGES[coverage]["label"],
        "offense": offense, "defense": defense,
        "ball_target": ball_target, "width": W,
    }
