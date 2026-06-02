"""Zentrale Zeit-Helfer: alle *sichtbaren* Zeiten in deutscher Lokalzeit.

Interne Zeitstempel (Lern-Historie, Modellspeicher) bleiben in UTC; was der
Nutzer liest (Briefing, Alerts …), zeigt **Berliner Zeit** – inkl. Sommer-/
Winterzeit-Umstellung über ``zoneinfo``. Fällt die Zeitzonen-Datenbank aus,
wird auf UTC zurückgefallen (mit Hinweis), statt zu crashen.
"""
from __future__ import annotations

from datetime import datetime, timezone

_BERLIN = "Europe/Berlin"


def now_de() -> datetime:
    """Aktuelle Zeit in Berliner Lokalzeit (Fallback: UTC)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(_BERLIN))
    except Exception:
        return datetime.now(timezone.utc)


def now_de_str(fmt: str = "%d.%m.%Y, %H:%M Uhr") -> str:
    """Formatierte Berliner Zeit für die Anzeige."""
    return now_de().strftime(fmt)
