"""Daten-Lake: DuckDB (Metadaten/Abfragen) + Parquet-Export (Rohbestand).

DuckDB braucht keinen Server, ist speicherschonend und liest/schreibt Parquet
nativ – ideal für 8 GB RAM. Alle Schreibvorgänge sind **idempotent**
(INSERT OR REPLACE über die Werk-ID), sodass ein erneuter/abgebrochener Lauf
keine Duplikate erzeugt.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import duckdb

from synapse.config import Config
from synapse.models import Work

_SCHEMA = """
CREATE TABLE IF NOT EXISTS works (
    id              VARCHAR PRIMARY KEY,
    title           VARCHAR,
    abstract        VARCHAR,
    doi             VARCHAR,
    year            INTEGER,
    cited_by_count  INTEGER,
    is_oa           BOOLEAN,
    oa_url          VARCHAR,
    venue           VARCHAR,
    authors         VARCHAR,          -- JSON
    concepts        VARCHAR,          -- JSON
    referenced_works VARCHAR,         -- JSON
    updated_date    VARCHAR,
    ingested_at     VARCHAR
);
CREATE TABLE IF NOT EXISTS dead_letter (
    raw   VARCHAR,
    error VARCHAR,
    ts    VARCHAR
);
CREATE TABLE IF NOT EXISTS state (
    key   VARCHAR PRIMARY KEY,
    value VARCHAR
);
CREATE TABLE IF NOT EXISTS events (
    ts      VARCHAR,
    event   VARCHAR,          -- 'search' | 'click'
    query   VARCHAR,
    work_id VARCHAR,
    rank    INTEGER
);
"""


class SynapseStore:
    """Persistenter Daten-Lake. Als Kontextmanager nutzbar."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        cfg.ensure_dirs()
        self.con = duckdb.connect(str(cfg.db_path))
        self.con.execute(_SCHEMA)

    # -- Kontextmanager -------------------------------------------------- #
    def __enter__(self) -> "SynapseStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self.con.close()

    # -- Schreiben (idempotent) ------------------------------------------ #
    def upsert_works(self, works: list[Work]) -> int:
        if not works:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        rows = [(
            w.id, w.title, w.abstract, w.doi, w.year, w.cited_by_count,
            w.is_oa, w.oa_url, w.venue,
            json.dumps(w.authors, ensure_ascii=False),
            json.dumps(w.concepts, ensure_ascii=False),
            json.dumps(w.referenced_works, ensure_ascii=False),
            w.updated_date, now,
        ) for w in works]
        self.con.executemany(
            "INSERT OR REPLACE INTO works VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        return len(rows)

    def add_dead_letter(self, raw: dict, error: str) -> None:
        self.con.execute(
            "INSERT INTO dead_letter VALUES (?,?,?)",
            [json.dumps(raw, ensure_ascii=False)[:20000], str(error)[:1000],
             datetime.now(timezone.utc).isoformat()])

    # -- Nutzungs-Events (Grundlage fürs lernende Ranking) --------------- #
    def log_event(self, event: str, query: str = "", work_id: str = "",
                  rank: int | None = None) -> None:
        self.con.execute(
            "INSERT INTO events VALUES (?,?,?,?,?)",
            [datetime.now(timezone.utc).isoformat(), event, query[:500],
             work_id, rank])

    def count_events(self, event: str | None = None) -> int:
        if event:
            return int(self.con.execute(
                "SELECT COUNT(*) FROM events WHERE event=?", [event]).fetchone()[0])
        return int(self.con.execute("SELECT COUNT(*) FROM events").fetchone()[0])

    # -- Checkpoints (Wiederanlauf) -------------------------------------- #
    def get_state(self, key: str, default: str = "") -> str:
        r = self.con.execute("SELECT value FROM state WHERE key=?", [key]).fetchone()
        return r[0] if r else default

    def set_state(self, key: str, value: str) -> None:
        self.con.execute("INSERT OR REPLACE INTO state VALUES (?,?)", [key, value])

    # -- Lesen / Statistik ----------------------------------------------- #
    def count_works(self) -> int:
        return int(self.con.execute("SELECT COUNT(*) FROM works").fetchone()[0])

    def count_dead_letter(self) -> int:
        return int(self.con.execute("SELECT COUNT(*) FROM dead_letter").fetchone()[0])

    def stats(self) -> dict:
        n = self.count_works()
        out = {"works": n, "dead_letter": self.count_dead_letter()}
        if n:
            row = self.con.execute(
                "SELECT MIN(year), MAX(year), "
                "SUM(CASE WHEN is_oa THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN abstract <> '' THEN 1 ELSE 0 END) FROM works"
            ).fetchone()
            out.update(year_min=row[0], year_max=row[1],
                       open_access=int(row[2] or 0), with_abstract=int(row[3] or 0))
        return out

    def fetch_for_index(self) -> list[dict]:
        """Liefert alle Werke mit dem für die Suche nötigen Text/Metadaten."""
        rows = self.con.execute(
            "SELECT id, title, abstract, year, doi, venue, cited_by_count "
            "FROM works"
        ).fetchall()
        return [{"id": r[0], "title": r[1] or "", "abstract": r[2] or "",
                 "year": r[3], "doi": r[4] or "", "venue": r[5] or "",
                 "cited_by_count": int(r[6] or 0)} for r in rows]

    def fetch_by_ids(self, ids: list[str]) -> dict:
        """Liefert Metadaten inkl. primärem Forschungsfeld (Top-Konzept) je ID.
        Wird für die Verbindungs-Entdeckung genutzt (nur wenige IDs -> schnell)."""
        if not ids:
            return {}
        ph = ",".join(["?"] * len(ids))
        rows = self.con.execute(
            f"SELECT id, title, year, doi, venue, cited_by_count, concepts "
            f"FROM works WHERE id IN ({ph})", ids).fetchall()
        out: dict = {}
        for r in rows:
            try:
                concepts = json.loads(r[6]) if r[6] else []
            except Exception:
                concepts = []
            field = concepts[0]["name"] if concepts else ""
            out[r[0]] = {"id": r[0], "title": r[1] or "", "year": r[2],
                         "doi": r[3] or "", "venue": r[4] or "",
                         "cited_by_count": int(r[5] or 0), "field": field}
        return out

    def export_parquet(self, path: str | None = None) -> str:
        """Schreibt den aktuellen Werk-Bestand als Parquet (Lake-Snapshot)."""
        target = path or str(self.cfg.lake_path / "works.parquet")
        self.con.execute(f"COPY works TO '{target}' (FORMAT PARQUET)")
        return target
