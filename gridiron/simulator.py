"""Play-Simulator: Offense-Konzept gegen Defensiv-Coverage.

Kern der Plattform. Eine Monte-Carlo-Engine simuliert tausende Wiederholungen
eines Spielzugs (Konzept × Coverage × Situation) und liefert die volle
Ertragsverteilung: erwartete Yards, Erfolgsrate, Big-Play-, TD-, Turnover- und
Sack-Wahrscheinlichkeit sowie erwartetes EPA.

Seriös statt Orakel: Die Zahlen entstehen aus **echten Liga-Basisraten**
(Yards-/Erfolgs-/Big-Play-Verteilungen aus dem Daten-Lake) multipliziert mit
einer **kalibrierten Football-Wissensmatrix** (Konzept-Stärken/-Schwächen je
Coverage). Jeder Wert ist damit nachvollziehbar. Mit Charting-Daten (Phase 3)
lässt sich die Matrix datengelernt verfeinern.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from gridiron.config import Config
from gridiron.storage import GridironStore

# --------------------------------------------------------------------------- #
# Football-Wissensbasis
# --------------------------------------------------------------------------- #
# Coverages: "Weichheit" (0..1) je Zone = wie leicht dort Raum entsteht.
# Höher = verwundbarer. man=1 -> Manndeckung, blitz=Zusatzrusher (0..1),
# box = Verteidiger in der Box (Laufabwehr), deep_def = tiefe Safetys.
COVERAGES: dict[str, dict] = {
    "Cover 0":    {"label": "Cover 0 — Mann, All-Out-Blitz", "deep": .82, "inter": .55, "short": .50, "flat": .55, "man": 1, "blitz": 1.00, "box": 7, "deep_def": 0},
    "Cover 1":    {"label": "Cover 1 — Mann mit Free Safety", "deep": .48, "inter": .55, "short": .55, "flat": .58, "man": 1, "blitz": .35, "box": 7, "deep_def": 1},
    "Cover 2 Man":{"label": "Cover 2 Mann (2 Deep)",          "deep": .42, "inter": .50, "short": .58, "flat": .55, "man": 1, "blitz": .10, "box": 6, "deep_def": 2},
    "Cover 2":    {"label": "Cover 2 (2 Deep Zone)",          "deep": .58, "inter": .60, "short": .55, "flat": .42, "man": 0, "blitz": .10, "box": 6, "deep_def": 2},
    "Tampa 2":    {"label": "Tampa 2 (MLB sinkt tief)",       "deep": .50, "inter": .45, "short": .58, "flat": .48, "man": 0, "blitz": .05, "box": 6, "deep_def": 2},
    "Cover 3":    {"label": "Cover 3 (3 Deep Zone)",          "deep": .50, "inter": .55, "short": .58, "flat": .66, "man": 0, "blitz": .20, "box": 7, "deep_def": 1},
    "Cover 4":    {"label": "Cover 4 / Quarters",             "deep": .40, "inter": .58, "short": .62, "flat": .60, "man": 0, "blitz": .05, "box": 6, "deep_def": 2},
    "Cover 6":    {"label": "Cover 6 (Quarter-Quarter-Half)", "deep": .46, "inter": .56, "short": .60, "flat": .58, "man": 0, "blitz": .08, "box": 6, "deep_def": 2},
    "Cover 1 Robber":{"label": "Cover 1 Robber (Mann + Lauerer)", "deep": .50, "inter": .40, "short": .55, "flat": .58, "man": 1, "blitz": .30, "box": 7, "deep_def": 1},
    "Cover 3 Buzz":{"label": "Cover 3 Buzz (Safety sinkt)",   "deep": .50, "inter": .50, "short": .56, "flat": .60, "man": 0, "blitz": .18, "box": 7, "deep_def": 1},
    "Cover 2 Sink":{"label": "Cover 2 Sink (tiefe Hälften)",   "deep": .62, "inter": .58, "short": .52, "flat": .45, "man": 0, "blitz": .08, "box": 6, "deep_def": 2},
    "Cover 9":    {"label": "Cover 9 (Match-Quarters)",        "deep": .44, "inter": .57, "short": .61, "flat": .59, "man": 0, "blitz": .06, "box": 6, "deep_def": 2},
}

# Konzepte: zone = Hauptangriffszone, depth = Ziel-Air-Yards-Profil,
# beats_man/beats_blitz = Bonus (>1) gegen Mann/Blitz, expl = Big-Play-Neigung.
# is_pass=False -> Laufkonzept (gap = Angriffsstelle, run-spezifisch).
_C = lambda **k: k
PASS_CONCEPTS: dict[str, dict] = {
    "Four Verts":  _C(label="Four Verts", zone="deep", depth=22, beats_man=1.05, beats_blitz=1.10, expl=1.6, note="Vier Senkrechte — sucht das tiefe Loch (stark gg. Cover 3/0)."),
    "Mesh":        _C(label="Mesh", zone="short", depth=4, beats_man=1.30, beats_blitz=1.20, expl=1.0, note="Kreuzende Drag-Routen — Mann-Killer, schnell gegen Blitz."),
    "Smash":       _C(label="Smash (Hi-Lo)", zone="flat", depth=10, beats_man=0.95, beats_blitz=0.95, expl=1.1, note="Corner+Hitch — High-Low am Sideline (frisst Cover 2)."),
    "Flood":       _C(label="Flood / Sail", zone="flat", depth=12, beats_man=0.95, beats_blitz=0.90, expl=1.2, note="Drei Routen, drei Tiefen einer Seite — stresst Zone."),
    "Slant-Flat":  _C(label="Slant-Flat", zone="short", depth=4, beats_man=1.15, beats_blitz=1.25, expl=0.9, note="Quick Game — schneller Abschluss, schlägt Blitz."),
    "Stick":       _C(label="Stick", zone="short", depth=6, beats_man=1.10, beats_blitz=1.15, expl=0.8, note="Stick/Flat-Triangle — sicherer Raumgewinn."),
    "Y-Cross":     _C(label="Y-Cross", zone="inter", depth=16, beats_man=1.10, beats_blitz=0.85, expl=1.4, note="Tiefe Überquerung — knackt Mann & Cover 3-Naht."),
    "Dagger":      _C(label="Dagger", zone="inter", depth=15, beats_man=1.00, beats_blitz=0.80, expl=1.5, note="Seam clears, Dig dahinter — gegen Single-High tödlich."),
    "Drive":       _C(label="Drive", zone="short", depth=6, beats_man=1.20, beats_blitz=1.10, expl=0.9, note="Shallow + Dig — Mann-Beater über die Mitte."),
    "Spacing":     _C(label="Spacing", zone="short", depth=5, beats_man=0.90, beats_blitz=1.15, expl=0.7, note="Underneath-Raumaufteilung — frisst weiche Zone."),
    "RB Screen":   _C(label="RB Screen", zone="short", depth=-2, beats_man=0.95, beats_blitz=1.40, expl=1.3, note="Screen — bestraft aggressiven Pass-Rush/Blitz."),
    "WR Screen":   _C(label="WR Screen / Bubble", zone="flat", depth=-1, beats_man=0.85, beats_blitz=1.20, expl=1.1, note="Schneller Perimeter-Wurf gegen weiche Corners."),
    "Curls":       _C(label="Curls / Hitch", zone="short", depth=8, beats_man=1.00, beats_blitz=0.90, expl=0.8, note="Curl/Hitch-Kombi — sicherer Raumgewinn gegen weiche Zone."),
    "Levels":      _C(label="Levels", zone="inter", depth=12, beats_man=1.15, beats_blitz=0.85, expl=1.1, note="Zwei In-Breaker auf zwei Tiefen — Mann-Beater über die Mitte."),
    "Post-Wheel":  _C(label="Post-Wheel", zone="deep", depth=20, beats_man=1.20, beats_blitz=0.95, expl=1.7, note="Post hält den Safety, Wheel läuft an der Sideline frei."),
    "Shallow":     _C(label="Shallow Cross", zone="short", depth=3, beats_man=1.25, beats_blitz=1.15, expl=0.9, note="Tiefe Querung von der Backside — klassischer Mann-Killer."),
    "Double Outs": _C(label="Double Outs", zone="flat", depth=11, beats_man=1.00, beats_blitz=0.85, expl=1.0, note="Zwei Out-Routen — schneller Sideline-Wurf gegen Off-Coverage."),
    "PA Boot":     _C(label="Play-Action Bootleg", zone="inter", depth=14, beats_man=1.05, beats_blitz=0.70, expl=1.4, note="Play-Action + Rollout — Hi-Lo auf einer Seite, bestraft Run-Fits."),
}
RUN_CONCEPTS: dict[str, dict] = {
    "Inside Zone": _C(label="Inside Zone", gap="inside", expl=1.0, note="Zonenblock A/B-Gap — Brot & Butter."),
    "Outside Zone":_C(label="Outside Zone", gap="outside", expl=1.2, note="Stretch zum Rand — gut gg. leichte Box."),
    "Power":       _C(label="Power", gap="inside", expl=0.9, note="Pulling Guard, Wucht am Point of Attack."),
    "Counter":     _C(label="Counter", gap="inside", expl=1.1, note="Misdirection + zwei Puller."),
    "Draw":        _C(label="Draw", gap="inside", expl=1.3, note="Verzögert — bestraft Pass-Rush/leichte Box."),
    "Toss":        _C(label="Toss / Pitch", gap="outside", expl=1.3, note="Schnell zum Rand, Speed in Space."),
    "Trap":        _C(label="Trap", gap="inside", expl=1.1, note="Lädt Penetrator ein, blockt ihn weg."),
    "Dive":        _C(label="Dive", gap="inside", expl=0.8, note="Schneller A-Gap-Hit — vor dem Blitz."),
    "Sweep":       _C(label="Sweep", gap="outside", expl=1.3, note="Pulling Guards zum Rand — Speed in Space."),
    "Iso":         _C(label="Iso", gap="inside", expl=0.9, note="Fullback-Lead direkt durch das Loch."),
    "Pin & Pull":  _C(label="Pin & Pull", gap="outside", expl=1.2, note="Down-Blocks + Puller — Stretch mit Wucht."),
}

# Standard-Air-Yards-Streuung je Tiefe (für realistische Wurfverteilung).
_AIR_SPREAD = {"screen": 2.0, "short": 3.0, "inter": 4.5, "deep": 7.0}


def _depth_band(air: float) -> str:
    if air < 0:
        return "screen"
    if air <= 7:
        return "short"
    if air <= 14:
        return "inter"
    return "deep"


@dataclass
class BaseRates:
    """Liga-Basisraten aus dem Daten-Lake (Anker der Simulation)."""
    pass_epa: float = 0.02
    run_epa: float = -0.02
    pass_success: float = 0.46
    run_success: float = 0.42
    pass_yards_mean: float = 7.2
    run_yards_mean: float = 4.3
    explosive_pass: float = 0.12
    explosive_run: float = 0.10
    source: str = "default"


def base_rates(cfg: Config) -> BaseRates:
    """Verankert die Engine auf echten Daten, wenn vorhanden – sonst Defaults."""
    try:
        with GridironStore(cfg) as store:
            if store.count_plays() < 200:
                return BaseRates()
            q = store.con.execute(
                "SELECT "
                " AVG(CASE WHEN is_pass THEN epa END), AVG(CASE WHEN is_rush THEN epa END),"
                " AVG(CASE WHEN is_pass THEN success::INT END), AVG(CASE WHEN is_rush THEN success::INT END),"
                " AVG(CASE WHEN is_pass THEN yards_gained END), AVG(CASE WHEN is_rush THEN yards_gained END),"
                " AVG(CASE WHEN is_pass THEN (yards_gained>=15)::INT END),"
                " AVG(CASE WHEN is_rush THEN (yards_gained>=10)::INT END)"
                " FROM plays WHERE down IS NOT NULL").fetchone()
        f = lambda v, d: float(v) if v is not None else d
        return BaseRates(
            pass_epa=f(q[0], 0.02), run_epa=f(q[1], -0.02),
            pass_success=f(q[2], 0.46), run_success=f(q[3], 0.42),
            pass_yards_mean=f(q[4], 7.2), run_yards_mean=f(q[5], 4.3),
            explosive_pass=f(q[6], 0.12), explosive_run=f(q[7], 0.10),
            source="data")
    except Exception:
        return BaseRates()


@dataclass
class SimResult:
    concept: str
    coverage: str
    is_pass: bool
    n: int
    mean_yards: float
    median_yards: float
    success_rate: float
    explosive_rate: float
    td_rate: float
    turnover_rate: float
    sack_rate: float
    expected_epa: float
    completion_rate: float = 0.0
    int_rate: float = 0.0
    outcomes: list[dict] = field(default_factory=list)
    hist: list[dict] = field(default_factory=list)
    verdict: str = ""
    note: str = ""
    matchup_factor: float = 1.0


# --------------------------------------------------------------------------- #
# Situations-Hilfen
# --------------------------------------------------------------------------- #
def _success_threshold(down: int, ydstogo: int) -> float:
    if down >= 3:
        return float(ydstogo)
    return (0.45 if down == 1 else 0.60) * ydstogo


def _box_for(coverage: str, personnel: str) -> int:
    box = COVERAGES[coverage]["box"]
    box += {"21": 1, "12": 1, "13": 2}.get(personnel, 0)  # mehr Tight Ends/FB -> vollere Box
    return box


def list_concepts() -> list[dict]:
    out = []
    for k, v in PASS_CONCEPTS.items():
        out.append({"key": k, "label": v["label"], "type": "Pass", "note": v["note"]})
    for k, v in RUN_CONCEPTS.items():
        out.append({"key": k, "label": v["label"], "type": "Lauf", "note": v["note"]})
    return out


def list_coverages() -> list[dict]:
    return [{"key": k, "label": v["label"]} for k, v in COVERAGES.items()]


# --------------------------------------------------------------------------- #
# Matchup-Faktor (transparente Football-Logik)
# --------------------------------------------------------------------------- #
def _pass_matchup(concept: dict, cov: dict) -> float:
    """Effizienz-Multiplikator eines Pass-Konzepts gegen eine Coverage (~0.6..1.6)."""
    softness = cov[concept["zone"]]                       # Raum in der Hauptzone
    f = 0.55 + 0.95 * softness                            # 0.55..1.5
    if cov["man"]:
        f *= concept["beats_man"]
    else:
        f *= (2.0 - concept["beats_man"]) ** 0.5          # Zone-Beater leicht abschwächen
    f *= 1.0 + 0.35 * cov["blitz"] * (concept["beats_blitz"] - 1.0)
    # tiefe Konzepte gegen viele Safetys bestrafen, gegen wenige belohnen
    if concept["zone"] == "deep":
        f *= 1.0 + 0.12 * (1 - cov["deep_def"])
    return float(np.clip(f, 0.55, 1.65))


def _run_matchup(concept: dict, cov: dict, box: int) -> float:
    """Lauf-Effizienz ~ leichte Box gut, volle Box schlecht; Rand vs. Blitz."""
    f = 1.0 + 0.16 * (6 - box)                            # 6er-Box neutral
    if concept["gap"] == "outside":
        f *= 1.0 + 0.10 * cov["blitz"]                    # Rand schlägt eindringenden Rush
    else:
        f *= 1.0 - 0.06 * cov["blitz"]
    if concept["label"].startswith("Draw"):
        f *= 1.0 + 0.20 * cov["blitz"]                    # Draw bestraft Pass-Rush
    return float(np.clip(f, 0.6, 1.5))


def _pass_params(c: dict, cov: dict):
    """Wahrscheinlichkeiten eines Pass-Konzepts gegen die Coverage.
    Liefert (Matchup-Faktor, Tiefenband, Completion-, Sack-, Int-Wahrsch.)."""
    mf = _pass_matchup(c, cov)
    band = _depth_band(c["depth"])
    comp_base = {"screen": 0.86, "short": 0.71, "inter": 0.60, "deep": 0.46}[band]
    comp_p = float(np.clip(comp_base + 0.20 * (mf - 1.0), 0.20, 0.93))
    sack_p = float(np.clip(0.055 + 0.10 * cov["blitz"] * (2.0 - c["beats_blitz"]), 0.01, 0.22))
    int_p = float(np.clip(0.018 + 0.020 * (1 - comp_p) * (1.6 if band == "deep" else 1.0), 0.005, 0.07))
    return mf, band, comp_p, sack_p, int_p


def play_outcome(concept: str, coverage: str, situation: dict,
                 rng: np.random.Generator, rates: BaseRates | None = None) -> dict:
    """Ein einzelner, gezogener Spielzug (für den interaktiven Spielmodus).
    Liefert realisierte Yards + Ergebnis-Art (Completion/Incomplete/Sack/INT/Lauf)."""
    rates = rates or BaseRates()
    cov = COVERAGES[coverage]
    is_pass = concept in PASS_CONCEPTS
    if is_pass:
        c = PASS_CONCEPTS[concept]
        mf, band, comp_p, sack_p, int_p = _pass_params(c, cov)
        u = rng.random()
        if u < sack_p:
            return {"yards": -int(rng.integers(4, 10)), "kind": "sack", "turnover": False, "pass": True}
        if u < sack_p + int_p:
            return {"yards": 0, "kind": "int", "turnover": True, "pass": True}
        if rng.random() < comp_p:
            air = c["depth"] + rng.normal(0, _AIR_SPREAD[band])
            yac = rng.gamma(1.6, ({"screen": 8.0, "short": 4.5, "inter": 3.0, "deep": 2.2}[band] * mf) / 1.6)
            fum = rng.random() < 0.012
            return {"yards": max(int(round(air + yac)) - (3 if fum else 0), -2),
                    "kind": "complete", "turnover": fum, "pass": True}
        return {"yards": 0, "kind": "incomplete", "turnover": False, "pass": True}
    # Lauf
    c = RUN_CONCEPTS[concept]
    box = _box_for(coverage, str(situation.get("personnel", "11")))
    mf = _run_matchup(c, cov, box)
    mean_target = max(rates.run_yards_mean * mf, 1.0)
    y = rng.gamma(2.6, (mean_target + 1.6) / 2.6) - 1.6
    if rng.random() < 0.05 * c["expl"] * mf:
        y += int(rng.integers(8, 45))
    if rng.random() < 0.08 / mf:
        y = -int(rng.integers(1, 4))
    fum = rng.random() < 0.011
    return {"yards": int(round(y)), "kind": "run", "turnover": fum, "pass": False}


# --------------------------------------------------------------------------- #
# Simulation
# --------------------------------------------------------------------------- #
def simulate(cfg: Config | None, concept: str, coverage: str, situation: dict,
             n: int = 4000, seed: int | None = 42,
             rates: BaseRates | None = None) -> SimResult:
    if coverage not in COVERAGES:
        raise ValueError(f"Unbekannte Coverage: {coverage}")
    is_pass = concept in PASS_CONCEPTS
    if not is_pass and concept not in RUN_CONCEPTS:
        raise ValueError(f"Unbekanntes Konzept: {concept}")
    rates = rates or (base_rates(cfg) if cfg is not None else BaseRates())
    cov = COVERAGES[coverage]
    rng = np.random.default_rng(seed)

    down = int(situation.get("down", 1))
    ydstogo = int(situation.get("ydstogo", 10))
    yardline = int(situation.get("yardline_100", 60))    # Yards bis Endzone
    personnel = str(situation.get("personnel", "11"))
    needed = _success_threshold(down, ydstogo)
    box = situation.get("box")
    box = int(box) if box else _box_for(coverage, personnel)

    if is_pass:
        c = PASS_CONCEPTS[concept]
        mf, band, comp_p, sack_p, int_p = _pass_params(c, cov)

        u = rng.random(n)
        sack = u < sack_p
        intc = (u >= sack_p) & (u < sack_p + int_p)
        live = ~sack & ~intc
        complete = live & (rng.random(n) < comp_p)

        air = c["depth"] + rng.normal(0, _AIR_SPREAD[band], n)
        yac_scale = {"screen": 8.0, "short": 4.5, "inter": 3.0, "deep": 2.2}[band] * mf
        yac = rng.gamma(1.6, yac_scale / 1.6, n)
        yards = np.zeros(n)
        yards[complete] = np.maximum(air[complete] + yac[complete], -2)
        yards[sack] = -rng.integers(4, 10, sack.sum())
        turnover = intc.copy()
        # Fumble-Lost auf Catch (klein)
        fum = complete & (rng.random(n) < 0.012)
        turnover |= fum
        yards[fum] = np.maximum(yards[fum] - 3, -2)
        base_epa, base_succ, base_expl = rates.pass_epa, rates.pass_success, rates.explosive_pass
        expl_cut = 15.0
    else:
        c = RUN_CONCEPTS[concept]
        mf = _run_matchup(c, cov, box)
        mean_target = max(rates.run_yards_mean * mf, 1.0)
        # rechtsschiefe Verteilung mit korrektem Mittelwert (Median < Mittel).
        shift = 1.6
        base = rng.gamma(2.6, (mean_target + shift) / 2.6, n) - shift
        explode = rng.random(n) < (0.05 * c["expl"] * mf)
        base[explode] += rng.integers(8, 45, explode.sum())
        tfl = rng.random(n) < (0.08 / mf)
        base[tfl] = -rng.integers(1, 4, tfl.sum())
        yards = base
        fum = rng.random(n) < 0.011
        turnover = fum
        yards[fum] = np.minimum(yards[fum], 1)
        sack = np.zeros(n, dtype=bool)
        base_epa, base_succ, base_expl = rates.run_epa, rates.run_success, rates.explosive_run
        expl_cut = 10.0

    yards = np.clip(yards, -12, yardline)                 # max bis Endzone
    td = yards >= yardline
    success = (yards >= needed) & ~turnover
    explosive = yards >= expl_cut

    mean_y = float(yards.mean())
    succ = float(success.mean())
    expl = float(explosive.mean())
    to_rate = float(turnover.mean())

    # Ergebnis-Aufschlüsselung (für die visuelle Darstellung)
    if is_pass:
        comp_rate = float(complete.mean())
        int_rate = float(intc.mean())
        sack_rate = float(sack.mean())
        incomp = max(0.0, 1.0 - comp_rate - int_rate - sack_rate)
        outcomes = [{"label": "Completion", "pct": round(comp_rate, 4), "cls": "ok"},
                    {"label": "Incomplete", "pct": round(incomp, 4), "cls": "mid"},
                    {"label": "Sack", "pct": round(sack_rate, 4), "cls": "warn"},
                    {"label": "Interception", "pct": round(int_rate, 4), "cls": "bad"}]
    else:
        comp_rate = 0.0
        int_rate = 0.0
        sack_rate = 0.0
        stuff = float((yards <= 0).mean())
        big = float((yards >= 10).mean())
        mid = max(0.0, 1.0 - stuff - big - to_rate)
        outcomes = [{"label": "Raumgewinn", "pct": round(mid, 4), "cls": "ok"},
                    {"label": "Big Run", "pct": round(big, 4), "cls": "ok2"},
                    {"label": "Stuff (≤0)", "pct": round(stuff, 4), "cls": "warn"},
                    {"label": "Fumble", "pct": round(to_rate, 4), "cls": "bad"}]
    # EPA-Schätzung: Basis + Abweichung von Erfolg/Big-Play - Turnover-Strafe
    epa = (base_epa + 1.6 * (succ - base_succ) + 2.2 * (expl - base_expl)
           - 4.0 * to_rate + 0.012 * (mean_y - (rates.pass_yards_mean if is_pass else rates.run_yards_mean)))
    epa = float(np.clip(epa, -1.2, 1.2))

    hist = _histogram(yards)
    res = SimResult(
        concept=concept, coverage=coverage, is_pass=is_pass, n=n,
        mean_yards=round(mean_y, 2), median_yards=round(float(np.median(yards)), 1),
        success_rate=round(succ, 4), explosive_rate=round(expl, 4),
        td_rate=round(float(td.mean()), 4), turnover_rate=round(to_rate, 4),
        sack_rate=round(float(sack.mean()), 4), expected_epa=round(epa, 3),
        completion_rate=round(comp_rate, 4), int_rate=round(int_rate, 4),
        outcomes=outcomes, hist=hist, note=c["note"], matchup_factor=round(mf, 2))
    res.verdict = _verdict(res)
    return res


def _histogram(yards: np.ndarray) -> list[dict]:
    bins = [(-99, -1, "Verlust"), (-1, 3, "0–3"), (3, 7, "4–7"), (7, 15, "8–15"),
            (15, 30, "16–30"), (30, 999, "30+")]
    n = len(yards)
    return [{"label": lab, "pct": round(float(((yards >= lo) & (yards < hi)).mean()), 4)}
            for lo, hi, lab in bins]


def _verdict(r: SimResult) -> str:
    e = r.expected_epa
    if e >= 0.20:
        return "Top-Matchup ✅"
    if e >= 0.07:
        return "Vorteil Offense"
    if e >= -0.05:
        return "Ausgeglichen"
    if e >= -0.18:
        return "Vorteil Defense"
    return "Schlechtes Matchup ⛔"


# --------------------------------------------------------------------------- #
# Berater / Matrix
# --------------------------------------------------------------------------- #
def best_concepts(cfg: Config | None, coverage: str, situation: dict,
                  top: int = 6, n: int = 2500) -> list[SimResult]:
    rates = base_rates(cfg) if cfg is not None else BaseRates()
    res = [simulate(None, k, coverage, situation, n=n, rates=rates)
           for k in list(PASS_CONCEPTS) + list(RUN_CONCEPTS)]
    res.sort(key=lambda r: r.expected_epa, reverse=True)
    return res[:top]


def stopping_coverages(cfg: Config | None, concept: str, situation: dict,
                       n: int = 2500) -> list[SimResult]:
    """Coverages sortiert nach Defense-Stärke (niedrigstes Offense-EPA zuerst)."""
    rates = base_rates(cfg) if cfg is not None else BaseRates()
    res = [simulate(None, concept, cov, situation, n=n, rates=rates) for cov in COVERAGES]
    res.sort(key=lambda r: r.expected_epa)
    return res


def matrix(cfg: Config | None, situation: dict, n: int = 1500) -> dict:
    """Volle Heatmap: erwartetes EPA für jedes Konzept × jede Coverage."""
    rates = base_rates(cfg) if cfg is not None else BaseRates()
    covs = list(COVERAGES)
    rows = []
    for k in list(PASS_CONCEPTS) + list(RUN_CONCEPTS):
        cells = [simulate(None, k, cov, situation, n=n, rates=rates).expected_epa for cov in covs]
        label = (PASS_CONCEPTS.get(k) or RUN_CONCEPTS[k])["label"]
        typ = "Pass" if k in PASS_CONCEPTS else "Lauf"
        rows.append({"concept": k, "label": label, "type": typ, "epa": cells})
    return {"coverages": [COVERAGES[c]["label"] for c in covs],
            "coverage_keys": covs, "rows": rows, "source": rates.source}
