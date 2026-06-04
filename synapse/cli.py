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
    res = ingest(cfg, filter_str=args.filter or "", max_records=args.limit)
    print(f"  Neu/aktualisiert : {res.ingested}")
    print(f"  Fehlerhaft (DLQ) : {res.failed}")
    print(f"  Bestand gesamt   : {res.total_in_store}")
    if args.export:
        with SynapseStore(cfg) as store:
            path = store.export_parquet()
        print(f"  Parquet-Export   : {path}")


def cmd_index(cfg, args) -> None:
    from synapse.index import build_index
    print("Baue semantischen Index (lokale Embeddings) …")
    n = build_index(cfg, prefer=args.embedder)
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


COMMANDS = {"doctor": cmd_doctor, "ingest": cmd_ingest, "stats": cmd_stats,
            "index": cmd_index, "search": cmd_search}


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

    pidx = sub.add_parser("index", help="semantischen Index bauen (lokale Embeddings)")
    pidx.add_argument("--embedder", default="auto", choices=["auto", "fastembed", "hash"],
                      help="auto = echtes Modell, sonst Offline-Hash")

    psr = sub.add_parser("search", help="semantische Suche")
    psr.add_argument("query", help="Suchanfrage (Idee/Frage in Worten)")
    psr.add_argument("--k", type=int, default=10, help="Anzahl Treffer")

    args = parser.parse_args(argv)
    cfg = load_config()
    COMMANDS[args.command](cfg, args)


if __name__ == "__main__":
    main()
