"""Pro-Nutzer-Daten: jeder Telegram-Nutzer bekommt ein eigenes Depot, einen
eigenen Sparplan und eigene Alerts – sauber getrennt nach Chat-ID.

Wichtig: Die **KI bleibt ein gemeinsames, präzises Modell** (mehr Daten = bessere
Treffer). Personalisiert wird, *worauf* sie schaut: Die Depot-/Watch-Werte aller
Nutzer fließen automatisch ins Lernen und Analysieren ein, damit die KI sich
langfristig gezielt um genau diese Aktien kümmert – ohne die Genauigkeit eines
Einzel-Nutzer-Modells zu opfern.

Dateien liegen unter ``<store>/users/<id>/``. Eine evtl. vorhandene Alt-Datei
(aus der Einzel-Nutzer-Zeit) wird beim ersten Zugriff dem Betreiber zugeordnet.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from stockai.config import Config

DEFAULT_USER = "default"
_CHAT_ENV = "STOCKAI_TELEGRAM_CHAT_ID"
_PREFS = "prefs.json"

RISK_LEVELS = ("defensiv", "ausgewogen", "offensiv")
_DEFAULT_RISK = "ausgewogen"


def sanitize(user: str | None) -> str:
    """Macht eine Chat-ID zu einem sicheren Verzeichnisnamen."""
    u = re.sub(r"[^A-Za-z0-9_-]", "", str(user or DEFAULT_USER))
    return u or DEFAULT_USER


def owner_user(cfg: Config) -> str:
    """Der Betreiber = erste Chat-ID der Allowlist (für die Alt-Daten-Migration)."""
    from stockai.notify import parse_chat_ids
    ids = parse_chat_ids(os.environ.get(_CHAT_ENV))
    return sanitize(ids[0]) if ids else DEFAULT_USER


def user_dir(cfg: Config, user: str | None) -> Path:
    d = Path(cfg.store_dir) / "users" / sanitize(user)
    d.mkdir(parents=True, exist_ok=True)
    return d


def user_path(cfg: Config, user: str | None, name: str) -> Path:
    """Pfad einer Pro-Nutzer-Datei; migriert Alt-Daten einmalig zum Betreiber."""
    user = sanitize(user)
    p = user_dir(cfg, user) / name
    if not p.exists():
        legacy = Path(cfg.store_dir) / name           # alte, gemeinsame Datei
        if legacy.exists() and user == owner_user(cfg):
            shutil.move(str(legacy), str(p))
    return p


def all_users(cfg: Config) -> list[str]:
    """Alle bekannten Nutzer: aus der Allowlist + bereits angelegte Verzeichnisse."""
    from stockai.notify import parse_chat_ids
    users: set[str] = {sanitize(c) for c in parse_chat_ids(os.environ.get(_CHAT_ENV))}
    base = Path(cfg.store_dir) / "users"
    if base.exists():
        users.update(p.name for p in base.iterdir() if p.is_dir())
    return sorted(users) or [DEFAULT_USER]


def load_prefs(cfg: Config, user: str | None) -> dict:
    p = user_path(cfg, user, _PREFS)
    if not p.exists():
        return {}
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}


def set_pref(cfg: Config, user: str | None, key: str, value) -> None:
    prefs = load_prefs(cfg, user)
    prefs[key] = value
    json.dump(prefs, open(user_path(cfg, user, _PREFS), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


def get_risk(cfg: Config, user: str | None) -> str:
    """Risikoneigung des Nutzers: defensiv | ausgewogen | offensiv."""
    r = str(load_prefs(cfg, user).get("risk", _DEFAULT_RISK)).lower()
    return r if r in RISK_LEVELS else _DEFAULT_RISK


def set_risk(cfg: Config, user: str | None, level: str) -> str | None:
    """Setzt die Risikoneigung; liefert die gesetzte Stufe oder None bei ungültig."""
    level = str(level).lower()
    if level not in RISK_LEVELS:
        return None
    set_pref(cfg, user, "risk", level)
    return level
