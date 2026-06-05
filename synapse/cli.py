"""Kommandozeile für Synapse (Phase 0).

Beispiele:
    python -m synapse.cli doctor
    SYNAPSE_SOURCE=sample python -m synapse.cli ingest --limit 100
    python -m synapse.cli ingest --filter 'concepts.id:C41008148,from_publication_date:2023-01-01' --limit 5000
    python -m synapse.cli stats
"""
from __future__ import annotations

import argparse
import logging

from synapse.config import load_config
from synapse.storage import SynapseStore


def cmd_doctor(cfg, args) -> None:
    print("Synapse Doctor")
    print("=" * 40)
    print(f"  Datenverzeichnis : {cfg.data_dir}")
    print(f"  DuckDB-Datei     : {cfg.db_path}")
    print(f"  Quelle (Modus)   : {cfg.source_mode}")
    print(f"  mailto gesetzt   : {'ja' if cfg.mailto else 'nein (empfohlen für stabile API)'}")
    try:
        import duckdb  # noqa: F401
        print("  duckdb           : OK")
    except Exception as exc:  # noqa: BLE001
        print(f"  duckdb           : FEHLT ({exc})")
    with SynapseStore(cfg) as store:
        print(f"  Werke im Lake    : {store.count_works()}")
    print("\nBereit. 'ingest' lädt Daten, 'stats' zeigt den Bestand.")


def cmd_ingest(cfg, args) -> None:
    from synapse.ingest import ingest
    print(f"Lade Werke (Quelle: {cfg.source_mode}, Limit {args.limit}) …")
    try:
        res = ingest(cfg, filter_str=args.filter or "", max_records=args.limit)
    except RuntimeError as exc:
        print("\nFehler bei der Abfrage – wahrscheinlich ein ungültiger Filter:")
        print(f"  {exc}")
        print("\nTipp: ohne Filter funktioniert es (z.B. --limit 5000), oder nutze")
        print("  --filter 'from_publication_date:2023-01-01'")
        print("  --filter 'default.search:machine learning'")
        return
    print(f"  Neu/aktualisiert : {res.ingested}")
    print(f"  Fehlerhaft (DLQ) : {res.failed}")
    print(f"  Bestand gesamt   : {res.total_in_store}")
    if args.export:
        with SynapseStore(cfg) as store:
            path = store.export_parquet()
        print(f"  Parquet-Export   : {path}")


def cmd_corpus(cfg, args) -> None:
    from synapse.corpus import load_corpus, THEMES
    if cfg.source_mode != "sample" and not cfg.mailto:
        print("Hinweis: SYNAPSE_MAILTO setzen (E-Mail) für die stabile OpenAlex-API.\n")
    print(f"Baue Start-Korpus: {len(THEMES)} Themenfelder, je bis {args.per_theme} "
          f"Arbeiten, ab {args.since}, min. Zitationen {args.min_citations}.")
    res = load_corpus(cfg, per_theme=args.per_theme, since=args.since,
                      min_citations=args.min_citations, progress=print)
    print("\nZusammenfassung")
    print("=" * 40)
    for name, n in res.per_theme.items():
        print(f"  {name:28s}: +{n}")
    for name, why in res.skipped.items():
        print(f"  {name:28s}: übersprungen ({why})")
    print(f"\n  Neu/aktualisiert gesamt: {res.total_ingested}")
    print(f"  Bestand gesamt         : {res.total_in_store}")
    if args.build_index:
        from synapse.index import build_index
        print("\nBaue semantischen Index …")
        n = build_index(cfg, prefer=args.embedder, batch=args.batch,
                        max_chars=args.max_chars)
        print(f"  Indizierte Werke: {n}")
    else:
        print("\nNächster Schritt: python -m synapse.cli index")


def cmd_index(cfg, args) -> None:
    from synapse.index import build_index
    print("Baue semantischen Index (lokale Embeddings) …")
    n = build_index(cfg, prefer=args.embedder, batch=args.batch, max_chars=args.max_chars)
    if n == 0:
        print("  Keine Werke vorhanden. Erst Daten laden:")
        print("    python -m synapse.cli ingest --limit 3000")
        return
    print(f"  Indizierte Werke: {n}")


def cmd_search(cfg, args) -> None:
    from pathlib import Path
    from synapse.index import SearchEngine
    if not (Path(cfg.data_dir) / "index" / "index.json").exists():
        print("Kein Index gefunden. Bitte zuerst:")
        print("  python -m synapse.cli ingest --limit 3000")
        print("  python -m synapse.cli index")
        return
    eng = SearchEngine(cfg)
    hits = eng.search(args.query, k=args.k)
    if not hits:
        print("Keine Treffer.")
        return
    print(f"Top {len(hits)} zu: {args.query!r}")
    print("=" * 60)
    for i, h in enumerate(hits, 1):
        yr = h.year or "—"
        print(f"{i:2d}. [{h.score:.3f}] {h.title}  ({yr}, {h.venue}, {h.cited_by_count} Zit.)")
        if h.doi:
            print(f"     doi:{h.doi}")


def cmd_stats(cfg, args) -> None:
    with SynapseStore(cfg) as store:
        s = store.stats()
    print("Bestand im Daten-Lake")
    print("=" * 40)
    for k, v in s.items():
        print(f"  {k:14s}: {v}")


def cmd_project(cfg, args) -> None:
    from synapse import projects
    act = args.action
    if act == "list":
        for p in projects.list_projects(cfg):
            print(f"  {p['id']}  | {p['title']}  ({p['area'] or '—'}, "
                  f"{p['contributions']} Beiträge, {p['status']})")
        return
    if act == "new":
        r = projects.create_project(cfg, args.title or "", area=args.area or "",
                                    description=args.desc or "", owner_name=args.owner or "")
        print(r.message)
        if r.ok:
            print(f"  ID: {r.data['id']}")
            print(f"  Owner-Token (sichern!): {r.data['owner_token']}")
        return
    if act == "show":
        d = projects.get_project(cfg, args.title or "")
        if not d:
            print("Projekt nicht gefunden.")
            return
        print(f"{d['title']}  ({d['area']})  – von {d['owner_name']}")
        print(d["description"])
        print(f"\nBeiträge ({len(d['contributions'])}):")
        for c in d["contributions"]:
            print(f"  [{c['trust_level']}] {c['kind']}: {c['title']}  – {c['contributor_name']}")
        return


def cmd_submit(cfg, args) -> None:
    from synapse.ingest import submit_doi
    print(f"Prüfe DOI {args.doi} (OpenAlex/Crossref) …")
    res = submit_doi(cfg, args.doi)
    print(("✓ " + res.title + " — " if res.ok else "✗ ") + res.message)


def cmd_ask(cfg, args) -> None:
    from pathlib import Path
    from synapse import assistant
    if not (Path(cfg.data_dir) / "index" / "index.json").exists():
        print("Kein Index. Bitte erst 'ingest' + 'index'.")
        return
    print("Analysiere Forschungslage …\n")
    print(assistant.render(assistant.analyze(cfg, args.question)))


def cmd_connections(cfg, args) -> None:
    from pathlib import Path
    from synapse.index import SearchEngine
    if not (Path(cfg.data_dir) / "index" / "index.json").exists():
        print("Kein Index. Bitte erst 'ingest' + 'index'.")
        return
    res = SearchEngine(cfg).connections(args.work_id, k=args.k)
    if res is None:
        print(f"Werk {args.work_id} nicht im Index.")
        return
    field, conns = res
    print(f"Verbindungen zu {args.work_id}  (Feld: {field or '—'})")
    print("=" * 60)
    for c in conns:
        bridge = f"   ↔ BRÜCKE → {c.field}" if c.cross_field else ""
        print(f"[{c.similarity:.3f}] {c.title}{bridge}")


def cmd_brain(cfg, args) -> None:
    from synapse import brain
    print("Trainiere Ranking-Gehirn aus Klick-Feedback …")
    res = brain.train(cfg)
    print(f"  Klicks ausgewertet: {res.n_clicks}")
    print(f"  Status: {res.note}")
    if res.weights:
        print("  Gewichte:", {k: res.weights[k] for k in res.weights})


def cmd_serve(cfg, args) -> None:
    import uvicorn
    from synapse.web import create_app
    print(f"Starte Web-Oberfläche auf http://{args.host}:{args.port}  (Strg+C beendet)")
    uvicorn.run(create_app(cfg), host=args.host, port=args.port)


def cmd_maintenance(cfg, args) -> None:
    """Abgelaufene Sitzungen + alte Login-Versuche aufräumen (per Timer nutzbar)."""
    from synapse import accounts
    res = accounts.cleanup_expired(cfg)
    print(f"Aufgeräumt: {res['sessions_removed']} Sitzungen, "
          f"{res['attempts_removed']} Login-Versuche entfernt.")


def cmd_security(cfg, args) -> None:
    """Sicherheits-Selbstcheck: warnt vor unsicheren Betriebs-Einstellungen."""
    print("Synapse Security-Check")
    print("=" * 40)
    ok = True
    https = "OK (Secure-Cookies aktiv)" if cfg.https else \
        "WARNUNG: SYNAPSE_HTTPS nicht gesetzt – nur hinter HTTPS-Proxy betreiben!"
    if not cfg.https:
        ok = False
    print(f"  HTTPS-Modus      : {https}")
    print(f"  mailto gesetzt   : {'ja' if cfg.mailto else 'nein (empfohlen)'}")
    with SynapseStore(cfg) as store:
        users = int(store.con.execute("SELECT COUNT(*) FROM users").fetchone()[0])
        sess = int(store.con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
    print(f"  Konten           : {users}")
    print(f"  aktive Sitzungen : {sess}")
    print("  Passwort-Hash    : scrypt (gesalzen)")
    print("  Brute-Force      : Lockout je Konto + IP aktiv")
    print("\n" + ("Alles gut." if ok else
                  "Bitte WARNUNG(en) oben beheben, bevor du öffentlich gehst."))


COMMANDS = {"doctor": cmd_doctor, "ingest": cmd_ingest, "stats": cmd_stats,
            "index": cmd_index, "search": cmd_search, "serve": cmd_serve,
            "brain": cmd_brain, "connections": cmd_connections, "ask": cmd_ask,
            "submit": cmd_submit, "project": cmd_project, "corpus": cmd_corpus,
            "maintenance": cmd_maintenance, "security": cmd_security}


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="synapse", description="Synapse – Wissenschafts-Entdeckungsmaschine")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="Umgebung & Bestand prüfen")

    pi = sub.add_parser("ingest", help="Werke aus OpenAlex laden")
    pi.add_argument("--filter", default="", help="OpenAlex-Filter (z.B. Konzept/Datum)")
    pi.add_argument("--limit", type=int, default=1000, help="max. Anzahl Werke")
    pi.add_argument("--export", action="store_true", help="danach als Parquet exportieren")

    sub.add_parser("stats", help="Bestand anzeigen")

    pc = sub.add_parser("corpus", help="kuratierten Start-Korpus der Fokusfelder laden")
    pc.add_argument("--per-theme", type=int, default=2000, help="max. Arbeiten je Themenfeld")
    pc.add_argument("--since", type=int, default=2015, help="ab Publikationsjahr")
    pc.add_argument("--min-citations", type=int, default=0, help="Mindest-Zitationen (0=aus)")
    pc.add_argument("--build-index", action="store_true", help="danach gleich indizieren")
    pc.add_argument("--embedder", default="auto", choices=["auto", "fastembed", "hash"])
    pc.add_argument("--batch", type=int, default=64)
    pc.add_argument("--max-chars", type=int, default=1200)

    pidx = sub.add_parser("index", help="semantischen Index bauen (lokale Embeddings)")
    pidx.add_argument("--embedder", default="auto", choices=["auto", "fastembed", "hash"],
                      help="auto = echtes Modell, sonst Offline-Hash")
    pidx.add_argument("--batch", type=int, default=64, help="Batch-Größe (kleiner = weniger RAM)")
    pidx.add_argument("--max-chars", type=int, default=1200, help="max. Textlänge je Werk")

    psr = sub.add_parser("search", help="semantische Suche")
    psr.add_argument("query", help="Suchanfrage (Idee/Frage in Worten)")
    psr.add_argument("--k", type=int, default=10, help="Anzahl Treffer")

    pse = sub.add_parser("serve", help="Web-Oberfläche starten")
    pse.add_argument("--host", default="0.0.0.0")
    pse.add_argument("--port", type=int, default=8000)

    sub.add_parser("maintenance", help="abgelaufene Sitzungen/Login-Versuche aufräumen")
    sub.add_parser("security", help="Sicherheits-Selbstcheck der Betriebs-Einstellungen")

    sub.add_parser("brain", help="Ranking-Gehirn aus Klick-Feedback trainieren")

    pco = sub.add_parser("connections", help="verwandte Arbeiten + Feld-Brücken zu einem Werk")
    pco.add_argument("work_id", help="OpenAlex-ID, z.B. W2741809807")
    pco.add_argument("--k", type=int, default=8)

    pa = sub.add_parser("ask", help="Forschungs-Assistent: Frage -> Einordnung mit Quellen")
    pa.add_argument("question", help="deine Forschungsfrage in Worten")

    psu = sub.add_parser("submit", help="eigene Arbeit per DOI beitragen (wird geprüft)")
    psu.add_argument("doi", help="DOI, z.B. 10.1038/s41586-021-03819-2")

    pp = sub.add_parser("project", help="Forschungs-Projekte (anlegen/auflisten/ansehen)")
    pp.add_argument("action", choices=["list", "new", "show"])
    pp.add_argument("title", nargs="?", help="Titel (new) oder Projekt-ID (show)")
    pp.add_argument("--area", default="")
    pp.add_argument("--desc", default="")
    pp.add_argument("--owner", default="")

    args = parser.parse_args(argv)
    cfg = load_config()
    COMMANDS[args.command](cfg, args)


if __name__ == "__main__":
    main()
