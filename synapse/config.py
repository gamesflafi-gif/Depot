"""Konfiguration für Synapse (Phase 0).

Werte können per Umgebungsvariablen überschrieben werden. Alles Lokale liegt
unter ``data/synapse/`` – nichts verlässt den Server.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    # Speicherorte (Daten-Lake)
    data_dir: str = "data/synapse"
    db_file: str = "synapse.duckdb"          # DuckDB-Metadaten-DB
    lake_dir: str = "lake"                    # Parquet-Lake (Rohdaten)

    # OpenAlex (CC0). „polite pool" via mailto -> stabilere, schnellere API.
    openalex_base: str = "https://api.openalex.org/works"
    mailto: str = field(default_factory=lambda: os.environ.get("SYNAPSE_MAILTO", ""))
    per_page: int = 200                      # OpenAlex-Maximum
    request_timeout: int = 30
    max_retries: int = 5                     # Backoff bei Fehlern/Rate-Limit

    # Datenquelle: "openalex" (live) oder "sample" (offline, für Tests/Demo)
    source_mode: str = field(
        default_factory=lambda: os.environ.get("SYNAPSE_SOURCE", "openalex"))

    @property
    def db_path(self) -> Path:
        return Path(self.data_dir) / self.db_file

    @property
    def lake_path(self) -> Path:
        return Path(self.data_dir) / self.lake_dir

    def ensure_dirs(self) -> None:
        self.lake_path.mkdir(parents=True, exist_ok=True)


def load_config() -> Config:
    cfg = Config()
    if d := os.environ.get("SYNAPSE_DATA_DIR"):
        cfg.data_dir = d
    return cfg
