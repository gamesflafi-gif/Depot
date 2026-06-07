"""Offline-Beispieldaten (synthetisch, aber realistisch korreliert).

Erlaubt Tests & Demo ohne Netzwerk. Die Wahrscheinlichkeit „Pass" hängt
plausibel von Down/Distanz/Feldzone/Spielstand ab; zwei Teams sind bewusst
lauf- bzw. passlastig, damit Tendenz-Analysen etwas zu finden haben.
"""
from __future__ import annotations

import random

_TEAMS = ["RUN", "AIR", "BAL", "MIX"]      # RUN=lauflastig, AIR=passlastig
_TEAM_BIAS = {"RUN": -0.22, "AIR": +0.22, "BAL": 0.0, "MIX": +0.05}


def _pass_prob(down: int, ydstogo: int, yardline_100: int, bias: float,
               shotgun: bool, score_diff: int) -> float:
    p = 0.50
    if down == 1:
        p = 0.46
    elif down == 2:
        p = 0.52 + (0.02 * (ydstogo - 7))
    elif down >= 3:
        p = 0.62 + 0.03 * max(0, ydstogo - 3)        # 3rd & long -> stark Pass
        if ydstogo <= 2:
            p = 0.40                                  # 3rd & short -> eher Lauf
    if yardline_100 <= 5:
        p -= 0.18                                     # Goalline -> mehr Lauf
    if shotgun:
        p += 0.20
    if score_diff <= -10:
        p += 0.12                                     # deutlich hinten -> Pass
    elif score_diff >= 10:
        p -= 0.10                                     # deutlich vorn -> Lauf
    return min(0.97, max(0.05, p + bias))


def generate_sample_plays(n_per_team: int = 220, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    plays: list[dict] = []
    pid = 0
    for team in _TEAMS:
        bias = _TEAM_BIAS[team]
        for _ in range(n_per_team):
            pid += 1
            season = rng.choice([2022, 2023, 2024])
            week = rng.randint(1, 18)
            down = rng.choices([1, 2, 3, 4], weights=[40, 32, 24, 4])[0]
            ydstogo = 10 if down == 1 else rng.randint(1, 18)
            yardline_100 = rng.randint(1, 99)
            qtr = rng.randint(1, 4)
            score_diff = rng.randint(-21, 21)
            shotgun = rng.random() < (0.55 if down >= 3 else 0.35)
            gsr = rng.randint(0, 3600)
            pp = _pass_prob(down, ydstogo, yardline_100, bias, shotgun, score_diff)
            is_pass = rng.random() < pp
            epa = rng.gauss(0.05 if is_pass else 0.0, 1.2)
            row = {
                "play_id": f"S{pid:05d}",
                "game_id": f"{season}_{week:02d}_{team}",
                "season": season, "week": week,
                "posteam": team, "defteam": rng.choice([t for t in _TEAMS if t != team]),
                "qtr": qtr, "down": down, "ydstogo": ydstogo,
                "yardline_100": yardline_100, "score_differential": score_diff,
                "game_seconds_remaining": gsr,
                "shotgun": shotgun, "no_huddle": rng.random() < 0.08,
                "play_type": "pass" if is_pass else "run",
                "is_pass": bool(is_pass), "is_rush": bool(not is_pass),
                "pass_length": (rng.choice(["short", "short", "deep"]) if is_pass else None),
                "pass_location": (rng.choice(["left", "middle", "right"]) if is_pass else None),
                "run_location": (None if is_pass else rng.choice(["left", "middle", "right"])),
                "run_gap": (None if is_pass else rng.choice(["end", "tackle", "guard"])),
                "play_action": (rng.random() < 0.25 if is_pass else False),
                "air_yards": (float(rng.randint(0, 30)) if is_pass else None),
                "yards_gained": float(round(epa * 3 + rng.randint(-2, 6))),
                "epa": float(epa), "success": bool(epa > 0),
            }
            plays.append(row)
    return plays


SAMPLE_PLAYS = generate_sample_plays()
