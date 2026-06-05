"""Forschungs-Assistent (Phase 3): beantwortet „Gibt es dazu schon Forschung?".

Statt nur Treffer zu listen, **analysiert** dieser Assistent die Forschungs-
landschaft zu einer Frage und sagt direkt:
- ob es das gibt (Anzahl weltweit + im eigenen Bestand),
- was es gibt (Hauptthemen, wichtigste & neueste Arbeiten),
- ob das Feld aktiv oder reif ist (Trend),
- welche Brücken in andere Felder es gibt.

Bewusst **faktenbasiert** (keine erfundenen Aussagen): alles stammt aus echten
Daten + Quellen. Kein großes Sprachmodell nötig – schnell und sicher auf 8 GB.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

# Füllwörter (DE/EN), die eine Frage zu einer brauchbaren Stichwort-Suche machen.
_STOP = {
    "gibt", "es", "forschung", "studien", "studie", "zu", "zum", "zur", "über",
    "was", "ist", "sind", "der", "die", "das", "und", "oder", "ein", "eine",
    "welche", "wie", "viel", "viele", "schon", "bereits", "dazu", "etwas",
    "there", "is", "are", "research", "studies", "study", "on", "about", "what",
    "the", "a", "an", "of", "for", "papers", "any", "do", "does", "exist",
}


def _keywords(q: str) -> str:
    """Reduziert eine (auch deutsche) Frage auf Stichworte für die Zählung."""
    toks = [t for t in re.findall(r"[A-Za-zÄÖÜäöüß0-9]+", q.lower()) if t not in _STOP]
    return " ".join(toks) if toks else q


@dataclass
class Briefing:
    question: str
    verdict: str = ""
    activity: str = ""
    worldwide_count: int | None = None
    local_count: int = 0
    year_min: int | None = None
    year_max: int | None = None
    themes: list = field(default_factory=list)         # Hauptthemen
    top_works: list = field(default_factory=list)       # einflussreichste (dicts)
    recent_works: list = field(default_factory=list)    # neueste (dicts)
    bridges: list = field(default_factory=list)         # Feld-Brücken (dicts)
    results: list = field(default_factory=list)         # volle Trefferliste (dicts)


def analyze(cfg, question: str, k: int = 30) -> Briefing:
    from synapse.index import SearchEngine
    from synapse.storage import SynapseStore
    from synapse.sources.openalex import count_works

    now = datetime.now().year
    b = Briefing(question=question)
    eng = SearchEngine(cfg)
    hits = eng.search(question, k=k)
    b.results = [h.__dict__ for h in hits]
    b.local_count = len(hits)
    b.worldwide_count = count_works(cfg, _keywords(question))   # Stichworte statt Fragesatz

    if not hits:
        b.verdict = ("Dazu finde ich in unserem Bestand nichts Passendes – "
                     "möglicherweise eine Lücke, oder das Thema fehlt im Bestand "
                     "(dann gezielt mehr Daten laden).")
        return b

    # Felder/Themen der Treffer
    ids = [h.id for h in hits]
    with SynapseStore(cfg) as store:
        info = store.fetch_by_ids(ids)
    fields = Counter(info.get(h.id, {}).get("field", "") for h in hits
                     if info.get(h.id, {}).get("field"))
    b.themes = [f for f, _ in fields.most_common(5)]

    years = [h.year for h in hits if h.year]
    if years:
        b.year_min, b.year_max = min(years), max(years)
    recent = [h for h in hits if h.year and h.year >= now - 3]

    def _d(h):
        return {"id": h.id, "title": h.title, "year": h.year, "doi": h.doi,
                "venue": h.venue, "cited_by_count": h.cited_by_count}
    b.top_works = [_d(h) for h in sorted(hits, key=lambda h: h.cited_by_count,
                                         reverse=True)[:3]]
    b.recent_works = [_d(h) for h in sorted(recent, key=lambda h: -(h.year or 0))[:3]]

    # Brücken in andere Felder (vom besten Treffer)
    conn = eng.connections(hits[0].id, k=8)
    if conn:
        _, conns = conn
        b.bridges = [{"title": c.title, "field": c.field, "doi": c.doi, "id": c.id}
                     for c in conns if c.cross_field][:3]

    # Verdikt + Aktivität ----------------------------------------------------
    # Ehrlich: die Welt-Zahl ist nur ein Anhaltspunkt (Stichwort-Suche), keine
    # absolute Wahrheit – darum keine voreiligen „Lücke"-Behauptungen.
    wc = b.worldwide_count
    if wc is not None and wc > 1000:
        b.verdict = f"Ja – dazu gibt es umfangreiche Forschung (~{wc:,} Arbeiten weltweit)."
    elif wc is not None and wc > 100:
        b.verdict = f"Ja, dazu gibt es Forschung (~{wc:,} Arbeiten weltweit)."
    elif wc is not None and wc > 0:
        b.verdict = (f"Zu diesen Stichworten findet OpenAlex nur ~{wc} Treffer. "
                     "Das muss keine Lücke sein – oft helfen andere/englische "
                     "Stichworte. Unten zeige ich die nächstliegenden Arbeiten.")
    else:
        b.verdict = (f"In unserem (begrenzten) Bestand finde ich {b.local_count} "
                     "thematisch nächstliegende Arbeiten – für ein vollständiges "
                     "Bild bitte mehr Daten laden.")

    frac_recent = len(recent) / max(1, len(hits))
    if frac_recent >= 0.4:
        b.activity = "aktives, schnell wachsendes Feld"
    elif b.year_max and b.year_max >= now - 2:
        b.activity = "etabliertes Feld mit weiterhin neuer Forschung"
    else:
        b.activity = "eher reifes/älteres Feld"
    return b


def render(b: Briefing) -> str:
    lines = [f"Frage: {b.question}", "=" * 60, b.verdict.replace("**", "")]
    if b.activity:
        lines.append(f"Einordnung: {b.activity}.")
    if b.year_min:
        lines.append(f"Zeitraum im Bestand: {b.year_min}–{b.year_max} "
                     f"({b.local_count} Treffer).")
    if b.themes:
        lines.append("Hauptthemen: " + ", ".join(b.themes))
    if b.top_works:
        lines.append("\nEinflussreichste Arbeiten:")
        for w in b.top_works:
            lines.append(f"  • {w['title']} ({w['year']}, {w['cited_by_count']} Zit.)")
    if b.recent_works:
        lines.append("\nNeueste Arbeiten:")
        for w in b.recent_works:
            lines.append(f"  • {w['title']} ({w['year']})")
    if b.bridges:
        lines.append("\nBrücken in andere Felder:")
        for c in b.bridges:
            lines.append(f"  • {c['title']}  → {c['field']}")
    lines.append("\nKeine Beratung – Information mit Quellen.")
    return "\n".join(lines)
