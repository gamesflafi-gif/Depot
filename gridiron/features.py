"""Situations-Merkmale: aus rohen Play-Feldern werden für Coaches verständliche
Eimer (Down/Distanz/Feldzone/Spielstand). Dieselben Definitionen werden in
SQL (Tendenz-Aggregation) und in Python (Modell-Eingabe) genutzt.
"""
from __future__ import annotations

# SQL-Ausdrücke (für DuckDB-GROUP BY in tendencies.py)
DIST_CASE = ("CASE WHEN ydstogo<=3 THEN 'kurz' WHEN ydstogo<=7 THEN 'mittel' "
             "ELSE 'lang' END")
ZONE_CASE = ("CASE WHEN yardline_100<=20 THEN 'Red Zone' "
             "WHEN yardline_100<=40 THEN 'Gegnerhälfte' "
             "WHEN yardline_100<=60 THEN 'Mittelfeld' "
             "WHEN yardline_100<=80 THEN 'eigene Hälfte' "
             "ELSE 'tief eigene Hälfte' END")

# numerische Merkmale fürs Modell (Reihenfolge ist fix!)
NUMERIC_FEATURES = [
    "down", "ydstogo", "yardline_100", "score_differential",
    "qtr", "game_seconds_remaining", "shotgun", "no_huddle",
]


def dist_bucket(ydstogo: int) -> str:
    y = ydstogo or 0
    return "kurz" if y <= 3 else "mittel" if y <= 7 else "lang"


def field_zone(yardline_100: int) -> str:
    y = yardline_100 or 50
    if y <= 20:
        return "Red Zone"
    if y <= 40:
        return "Gegnerhälfte"
    if y <= 60:
        return "Mittelfeld"
    if y <= 80:
        return "eigene Hälfte"
    return "tief eigene Hälfte"


def numeric_vector(sit: dict) -> list[float]:
    """Wandelt eine Situation (dict) in den Modell-Eingabevektor (ohne Team)."""
    def num(v) -> float:
        if isinstance(v, bool):
            return 1.0 if v else 0.0
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0
    return [num(sit.get(k)) for k in NUMERIC_FEATURES]
