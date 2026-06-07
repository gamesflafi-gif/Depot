"""Konfiguration für Gridiron.

Werte per Umgebungsvariablen überschreibbar. Alles Lokale liegt unter
``data/gridiron/`` – nichts verlässt den Server.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# nflverse veröffentlicht Play-by-Play als Parquet je Saison (CC0-nahe, frei).
_NFLVERSE_PBP = "https://github.com/nflverse/nflverse-data/releases/download/pbp"


def _default_seasons() -> list[int]:
    env = os.environ.get("GRIDIRON_SEASONS", "")
    if env.strip():
        out: list[int] = []
        for part in env.replace(" ", "").split(","):
            if "-" in part:
                a, b = part.split("-")
                out += list(range(int(a), int(b) + 1))
            elif part:
                out.append(int(part))
        return out
    return [2021, 2022, 2023, 2024]


@dataclass
class Config:
    data_dir: str = "data/gridiron"
    db_file: str = "gridiron.duckdb"

    # Datenquelle: "nflverse" (live) oder "sample" (offline, für Tests/Demo)
    source_mode: str = field(
        default_factory=lambda: os.environ.get("GRIDIRON_SOURCE", "nflverse"))
    seasons: list[int] = field(default_factory=_default_seasons)
    nflverse_base: str = _NFLVERSE_PBP
    request_timeout: int = 120

    # hinter HTTPS „Secure"-Cookies (GRIDIRON_HTTPS=1) – für späteres Web.
    https: bool = field(
        default_factory=lambda: os.environ.get("GRIDIRON_HTTPS", "") in ("1", "true", "yes"))

    @property
    def db_path(self) -> Path:
        return Path(self.data_dir) / self.db_file

    @property
    def model_dir(self) -> Path:
        return Path(self.data_dir) / "model"

    def ensure_dirs(self) -> None:
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)
        self.model_dir.mkdir(parents=True, exist_ok=True)


def load_config() -> Config:
    cfg = Config()
    if d := os.environ.get("GRIDIRON_DATA_DIR"):
        cfg.data_dir = d
    return cfg
