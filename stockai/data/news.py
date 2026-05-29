"""News-Beschaffung über kostenlose RSS-Feeds (kein API-Key nötig).

Quellen:
    * Yahoo Finance Headline-Feed pro Ticker
    * Google News Suche pro Ticker
    * Optional NewsAPI.org, falls die Umgebungsvariable STOCKAI_NEWSAPI_KEY
      gesetzt ist (kostenloser Key auf newsapi.org)

Der RSS-Parser nutzt ausschließlich die Python-Standardbibliothek
(urllib + xml.etree), damit das Projekt ohne fragile Build-Abhängigkeiten
überall läuft.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus
from xml.etree import ElementTree as ET

log = logging.getLogger(__name__)

_YAHOO_RSS = (
    "https://feeds.finance.yahoo.com/rss/2.0/headline"
    "?s={ticker}&region=US&lang=en-US"
)
_GOOGLE_RSS = (
    "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
)
_NEWSAPI_URL = (
    "https://newsapi.org/v2/everything?q={query}&language=en&sortBy=publishedAt"
    "&pageSize={limit}&apiKey={key}"
)
_USER_AGENT = "Mozilla/5.0 (compatible; stockai/0.1; +https://example.local)"
_TAG_RE = re.compile(r"<[^>]+>")
_NEWSAPI_KEY_ENV = "STOCKAI_NEWSAPI_KEY"


@dataclass
class NewsItem:
    ticker: str
    title: str
    summary: str
    link: str
    published: datetime | None
    source: str

    @property
    def text(self) -> str:
        """Zusammengeführter Text für die Sentiment-Analyse."""
        return f"{self.title}. {self.summary}".strip()


def _strip_html(text: str) -> str:
    return _TAG_RE.sub("", text or "").strip()


def _parse_date(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        dt = parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass
    try:  # ISO-8601 (z.B. NewsAPI: 2026-05-29T10:00:00Z)
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _fetch_url(url: str) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read()
    except Exception as exc:
        log.warning("RSS-Abruf fehlgeschlagen (%s): %s", url, exc)
        return None


def _parse_rss(raw: bytes, ticker: str, source: str, limit: int) -> list[NewsItem]:
    items: list[NewsItem] = []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        log.warning("RSS-Parsing (%s) fehlgeschlagen: %s", source, exc)
        return items

    # RSS 2.0: channel/item ; robust gegenüber Namespaces
    for item in root.iter("item"):
        if len(items) >= limit:
            break
        title = item.findtext("title", default="")
        summary = item.findtext("description", default="")
        link = item.findtext("link", default="")
        pub = item.findtext("pubDate", default="")
        items.append(
            NewsItem(
                ticker=ticker,
                title=_strip_html(title),
                summary=_strip_html(summary),
                link=(link or "").strip(),
                published=_parse_date(pub),
                source=source,
            )
        )
    return items


def _fetch_feed(url: str, ticker: str, source: str, limit: int) -> list[NewsItem]:
    raw = _fetch_url(url)
    if raw is None:
        return []
    return _parse_rss(raw, ticker, source, limit)


def _fetch_newsapi(ticker: str, query: str, limit: int) -> list[NewsItem]:
    """Optionale NewsAPI.org-Quelle – aktiv nur, wenn ein Key gesetzt ist."""
    key = os.environ.get(_NEWSAPI_KEY_ENV)
    if not key:
        return []
    url = _NEWSAPI_URL.format(query=query, limit=min(limit, 100), key=key)
    raw = _fetch_url(url)
    if raw is None:
        return []
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if payload.get("status") != "ok":
        log.warning("NewsAPI-Antwort nicht ok: %s", payload.get("message", ""))
        return []
    items: list[NewsItem] = []
    for art in payload.get("articles", [])[:limit]:
        items.append(
            NewsItem(
                ticker=ticker,
                title=(art.get("title") or "").strip(),
                summary=(art.get("description") or "").strip(),
                link=(art.get("url") or "").strip(),
                published=_parse_date(art.get("publishedAt")),
                source="newsapi",
            )
        )
    return items


def fetch_news(
    ticker: str,
    company_name: str | None = None,
    limit: int = 25,
) -> list[NewsItem]:
    """Holt aktuelle Headlines zu einem Ticker aus mehreren RSS-Quellen.

    Dedupliziert nach Titel und liefert maximal ``limit`` Einträge.
    """
    query = quote_plus(company_name or ticker)
    results: list[NewsItem] = []
    results += _fetch_feed(_YAHOO_RSS.format(ticker=ticker), ticker, "yahoo", limit)
    results += _fetch_feed(_GOOGLE_RSS.format(query=query), ticker, "google", limit)
    results += _fetch_newsapi(ticker, query, limit)

    # Deduplizieren nach (normalisiertem) Titel
    seen: set[str] = set()
    unique: list[NewsItem] = []
    for item in results:
        key = item.title.strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(item)

    # Neueste zuerst (Einträge ohne Datum ans Ende)
    unique.sort(
        key=lambda i: i.published or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return unique[:limit]
