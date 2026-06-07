"""Daten-Lake: DuckDB (Play-by-Play). Speicherschonend, Parquet-nativ,
ideal für 8 GB RAM. Schreibvorgänge sind idempotent (Upsert über play_id),
sodass ein erneuter/abgebrochener Lauf keine Duplikate erzeugt.
"""
from __future__ import annotations

import duckdb

from gridiron.config import Config

# Reihenfolge MUSS zu COLUMNS passen (Insert per Position).
COLUMNS = [
    "play_id", "game_id", "season", "week", "posteam", "defteam", "qtr",
    "down", "ydstogo", "yardline_100", "score_differential",
    "game_seconds_remaining", "shotgun", "no_huddle", "play_type",
    "is_pass", "is_rush", "pass_length", "pass_location", "run_location",
    "run_gap", "play_action", "air_yards", "yards_gained", "epa", "success",
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS plays (
    play_id        VARCHAR PRIMARY KEY,
    game_id        VARCHAR,
    season         INTEGER,
    week           INTEGER,
    posteam        VARCHAR,
    defteam        VARCHAR,
    qtr            INTEGER,
    down           INTEGER,
    ydstogo        INTEGER,
    yardline_100   INTEGER,
    score_differential INTEGER,
    game_seconds_remaining INTEGER,
    shotgun        BOOLEAN,
    no_huddle      BOOLEAN,
    play_type      VARCHAR,
    is_pass        BOOLEAN,
    is_rush        BOOLEAN,
    pass_length    VARCHAR,
    pass_location  VARCHAR,
    run_location   VARCHAR,
    run_gap        VARCHAR,
    play_action    BOOLEAN,
    air_yards      DOUBLE,
    yards_gained   DOUBLE,
    epa            DOUBLE,
    success        BOOLEAN
);
"""


class GridironStore:
    """Persistenter Daten-Lake. Als Kontextmanager nutzbar."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        cfg.ensure_dirs()
        self.con = duckdb.connect(str(cfg.db_path))
        self.con.execute(_SCHEMA)

    def __enter__(self) -> "GridironStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self.con.close()

    # -- Schreiben (idempotent) ------------------------------------------ #
    def insert_plays(self, plays: list[dict]) -> int:
        if not plays:
            return 0
        rows = [[p.get(c) for c in COLUMNS] for p in plays]
        ph = ",".join(["?"] * len(COLUMNS))
        self.con.executemany(
            f"INSERT OR REPLACE INTO plays ({','.join(COLUMNS)}) VALUES ({ph})", rows)
        return len(rows)

    # -- Lesen / Statistik ----------------------------------------------- #
    def count_plays(self) -> int:
        return int(self.con.execute("SELECT COUNT(*) FROM plays").fetchone()[0])

    def seasons(self) -> list[int]:
        rows = self.con.execute(
            "SELECT DISTINCT season FROM plays WHERE season IS NOT NULL "
            "ORDER BY season").fetchall()
        return [int(r[0]) for r in rows]

    def teams(self) -> list[str]:
        rows = self.con.execute(
            "SELECT DISTINCT posteam FROM plays WHERE posteam IS NOT NULL "
            "AND posteam <> '' ORDER BY posteam").fetchall()
        return [r[0] for r in rows]

    def stats(self) -> dict:
        n = self.count_plays()
        out: dict = {"plays": n}
        if n:
            row = self.con.execute(
                "SELECT MIN(season), MAX(season), COUNT(DISTINCT posteam), "
                "SUM(CASE WHEN is_pass THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN is_rush THEN 1 ELSE 0 END) FROM plays").fetchone()
            out.update(season_min=row[0], season_max=row[1], teams=int(row[2] or 0),
                       pass_plays=int(row[3] or 0), run_plays=int(row[4] or 0))
        return out

    def export_parquet(self, path: str | None = None) -> str:
        target = path or str(self.cfg.data_dir + "/plays.parquet")
        self.con.execute(f"COPY plays TO '{target}' (FORMAT PARQUET)")
        return target
