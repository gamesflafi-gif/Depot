"""nflverse-Quelle: NFL Play-by-Play je Saison (Parquet, frei).

Lädt die Saison-Parquet-Datei (GitHub-Release) herunter und liefert
normalisierte Play-Dicts. Im Modus ``sample`` kommen Offline-Beispieldaten
(kein Netzwerk) – für Tests/Demo.

Hinweis: Das Herunterladen läuft auf dem Server (volle Internet-Anbindung),
nicht in eingeschränkten Sandboxes.
"""
from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Iterator

from gridiron.config import Config

log = logging.getLogger(__name__)

# Nur die für Scouting/Modell nötigen Spalten (von ~370) – spart RAM/Zeit.
# "pass"/"rush" sind in DuckDB heikel -> in Anführungszeichen.
_SELECT = """
 play_id, game_id, CAST(season AS INTEGER) AS season, CAST(week AS INTEGER) AS week,
 posteam, defteam, CAST(qtr AS INTEGER) AS qtr, CAST(down AS INTEGER) AS down,
 CAST(ydstogo AS INTEGER) AS ydstogo, CAST(yardline_100 AS INTEGER) AS yardline_100,
 CAST(score_differential AS INTEGER) AS score_differential,
 CAST(game_seconds_remaining AS INTEGER) AS game_seconds_remaining,
 CAST(shotgun AS BOOLEAN) AS shotgun, CAST(no_huddle AS BOOLEAN) AS no_huddle,
 play_type,
 CAST("pass" AS BOOLEAN) AS is_pass, CAST("rush" AS BOOLEAN) AS is_rush,
 pass_length, pass_location, run_location, run_gap,
 CAST(play_action AS BOOLEAN) AS play_action,
 CAST(air_yards AS DOUBLE) AS air_yards, CAST(yards_gained AS DOUBLE) AS yards_gained,
 CAST(epa AS DOUBLE) AS epa, CAST(success AS BOOLEAN) AS success
"""


def iter_plays(cfg: Config, seasons: list[int]) -> Iterator[dict]:
    if cfg.source_mode == "sample":
        from gridiron.sample_data import SAMPLE_PLAYS
        yield from SAMPLE_PLAYS
        return

    import duckdb
    import urllib.request

    con = duckdb.connect()
    for yr in seasons:
        url = f"{cfg.nflverse_base}/play_by_play_{yr}.parquet"
        path = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
                path = tmp.name
            log.info("Lade Saison %s …", yr)
            req = urllib.request.Request(url, headers={"User-Agent": "Gridiron/0.1"})
            with urllib.request.urlopen(req, timeout=cfg.request_timeout) as resp, \
                    open(path, "wb") as fh:
                fh.write(resp.read())
            q = (f"SELECT {_SELECT} FROM read_parquet('{path}') "
                 "WHERE play_type IN ('run','pass') AND down IS NOT NULL")
            cur = con.execute(q)
            names = [d[0] for d in cur.description]
            for r in cur.fetchall():
                yield dict(zip(names, r))
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"nflverse-Saison {yr} nicht ladbar: {exc}\nURL: {url}")
        finally:
            if path and os.path.exists(path):
                os.remove(path)
