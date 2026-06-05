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


def fetch_by_doi(cfg: Config, doi: str) -> dict | None:
    """Holt eine Arbeit anhand ihres **DOI** aus OpenAlex – nur wenn sie dort
    offiziell registriert ist. Liefert None, wenn es den DOI nicht gibt.
    Damit lässt sich „belegte" Forschung verifizieren, bevor sie aufgenommen wird.
    """
    doi = doi.strip().replace("https://doi.org/", "").replace("http://doi.org/", "")
    doi = doi.replace("doi:", "").strip().lower()
    if not doi or "/" not in doi:
        return None
    params = {}
    if cfg.mailto:
        params["mailto"] = cfg.mailto
    qs = ("?" + urllib.parse.urlencode(params)) if params else ""
    url = f"https://api.openalex.org/works/https://doi.org/{doi}{qs}"
    try:
        return _get_json(url, cfg)
    except Exception:  # noqa: BLE001 (nicht gefunden = None)
        return None


def count_works(cfg: Config, query: str) -> int | None:
    """Wie viele Arbeiten gibt es **weltweit** zu einer Suchanfrage? (OpenAlex
    meta.count). Liefert None offline/bei Fehler."""
    if cfg.source_mode == "sample" or not query.strip():
        return None
    params = {"filter": f"default.search:{query}", "per-page": 1}
    if cfg.mailto:
        params["mailto"] = cfg.mailto
    url = cfg.openalex_base + "?" + urllib.parse.urlencode(params, safe=":,*")
    try:
        data = _get_json(url, cfg)
        return int((data.get("meta") or {}).get("count", 0))
    except Exception:  # noqa: BLE001
        return None


def _get_json(url: str, cfg: Config) -> dict:
    """HTTP-GET mit Retry/Backoff. Client-Fehler (4xx außer 429) werden NICHT
    wiederholt und mit der echten OpenAlex-Meldung gemeldet."""
    import urllib.error
    last_exc: Exception | None = None
    for attempt in range(cfg.max_retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Synapse/0.1"})
            with urllib.request.urlopen(req, timeout=cfg.request_timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8")[:600]
            except Exception:  # noqa: BLE001
                pass
            msg = f"OpenAlex HTTP {exc.code}: {body or exc.reason}\nURL: {url}"
            # 4xx (außer 429 Rate-Limit) = unsere Anfrage ist falsch -> nicht wiederholen
            if 400 <= exc.code < 500 and exc.code != 429:
                raise RuntimeError(msg)
            last_exc = RuntimeError(msg)
        except Exception as exc:  # noqa: BLE001 (Netz ist unzuverlässig)
            last_exc = exc
        wait = 2 ** attempt
        log.warning("OpenAlex-Fehler (Versuch %d): %s – warte %ds",
                    attempt + 1, last_exc, wait)
        time.sleep(wait)
    raise RuntimeError(f"OpenAlex nicht erreichbar nach {cfg.max_retries} Versuchen: {last_exc}")
