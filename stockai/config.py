"""Laden und Zugriff auf die Projektkonfiguration (config.yaml)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Projekt-Root = ein Verzeichnis über diesem Paket
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT / "config.yaml"


@dataclass
class Config:
    """Typisierter Zugriff auf die Konfiguration."""

    tickers: list[str]
    etfs: list[str]
    crypto: list[str]
    sectors: dict[str, str]
    history_period: str
    history_interval: str
    horizon_days: int
    profit_threshold: float
    news_max_per_ticker: int
    news_lookback_days: int
    model: dict[str, Any]
    paths: dict[str, str]
    raw: dict[str, Any] = field(default_factory=dict)

    # --- abgeleitete, absolute Pfade -------------------------------------
    @property
    def store_dir(self) -> Path:
        p = ROOT / self.paths.get("store_dir", "data/store")
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def model_dir(self) -> Path:
        p = ROOT / self.paths.get("model_dir", "data/models")
        p.mkdir(parents=True, exist_ok=True)
        return p


def load_dotenv(env_path: Path | None = None) -> None:
    """Lädt Schlüssel=Wert-Paare aus einer ``.env``-Datei in die Umgebung.

    Ohne Zusatz-Abhängigkeit. Bereits gesetzte Variablen werden nicht
    überschrieben. So genügt es, Secrets (Telegram-Token, NewsAPI-Key …) in eine
    ``.env`` im Projekt-Root zu schreiben.
    """
    path = env_path or (ROOT / ".env")
    if not path.exists():
        return
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception:
        pass  # defekte .env darf das Programm nicht stoppen


def load_config(path: str | os.PathLike | None = None) -> Config:
    """Liest die YAML-Konfiguration und liefert ein ``Config``-Objekt."""
    load_dotenv()  # Secrets aus .env verfügbar machen (falls vorhanden)
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(cfg_path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    # Bequemes Umschalten ohne Datei-Edit: STOCKAI_DATA_SOURCE=live|demo
    env_source = os.environ.get("STOCKAI_DATA_SOURCE")
    if env_source:
        data["data_source"] = env_source.strip().lower()

    return Config(
        tickers=list(data.get("tickers", [])),
        etfs=list(data.get("etfs", [])),
        crypto=list(data.get("crypto", [])),
        sectors=dict(data.get("sectors", {})),
        history_period=str(data.get("history_period", "2y")),
        history_interval=str(data.get("history_interval", "1d")),
        horizon_days=int(data.get("horizon_days", 5)),
        profit_threshold=float(data.get("profit_threshold", 0.0)),
        news_max_per_ticker=int(data.get("news_max_per_ticker", 25)),
        news_lookback_days=int(data.get("news_lookback_days", 7)),
        model=dict(data.get("model", {})),
        paths=dict(data.get("paths", {})),
        raw=data,
    )
