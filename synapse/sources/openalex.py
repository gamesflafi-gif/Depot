"""OpenAlex-Quelle: liefert rohe Werk-Datensätze (Stream).

OpenAlex ist CC0 (frei). Wir nutzen Cursor-Paginierung (stabil für große
Mengen), den „polite pool" via ``mailto`` und robustes Retry/Backoff. Im
Modus ``sample`` werden Offline-Beispieldaten geliefert (kein Netzwerk),
damit Tests und Demo ohne Internet laufen.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from collections.abc import Iterator

from synapse.config import Config

log = logging.getLogger(__name__)


def iter_works(cfg: Config, filter_str: str = "", max_records: int = 1000) -> Iterator[dict]:
    """Liefert rohe OpenAlex-Werke (als dicts). Stoppt nach ``max_records``."""
    if cfg.source_mode == "sample":
        from synapse.sample_data import SAMPLE_WORKS
        for i, w in enumerate(SAMPLE_WORKS):
            if i >= max_records:
                return
            yield w
        return

    yielded = 0
    cursor = "*"
    while cursor and yielded < max_records:
        params = {
            "per-page": min(cfg.per_page, max_records - yielded),
            "cursor": cursor,
        }
        if filter_str:
            params["filter"] = filter_str
        if cfg.mailto:
            params["mailto"] = cfg.mailto
        # WICHTIG: OpenAlex erwartet ':' und ',' im Filter WÖRTLICH (nicht
        # url-kodiert), sonst HTTP 400. Daher als "safe" markieren.
        url = cfg.openalex_base + "?" + urllib.parse.urlencode(params, safe=":,*")

        data = _get_json(url, cfg)
        results = data.get("results", [])
        if not results:
            return
        for w in results:
            yield w
            yielded += 1
            if yielded >= max_records:
                return
        cursor = (data.get("meta") or {}).get("next_cursor")


def _get_json(url: str, cfg: Config) -> dict:
    """HTTP-GET mit Retry/Backoff (Rate-Limit, Netzfehler)."""
    last_exc: Exception | None = None
    for attempt in range(cfg.max_retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Synapse/0.1"})
            with urllib.request.urlopen(req, timeout=cfg.request_timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 (bewusst breit: Netz ist unzuverlässig)
            last_exc = exc
            wait = 2 ** attempt
            log.warning("OpenAlex-Fehler (Versuch %d): %s – warte %ds",
                        attempt + 1, exc, wait)
            time.sleep(wait)
    raise RuntimeError(f"OpenAlex nicht erreichbar nach {cfg.max_retries} Versuchen: {last_exc}")
