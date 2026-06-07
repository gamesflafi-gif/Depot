"""Kommandozeile für Gridiron.

Beispiele:
    GRIDIRON_SOURCE=sample python -m gridiron.cli ingest
    python -m gridiron.cli stats
    python -m gridiron.cli train
    python -m gridiron.cli scout KC --season 2024
    python -m gridiron.cli predict --team KC --down 3 --ydstogo 8 --yardline 65
"""
from __future__ import annotations

import argparse
import logging

from gridiron.config import load_config
from gridiron.storage import GridironStore


def cmd_doctor(cfg, args) -> None:
    print("Gridiron Doctor")
    print("=" * 40)
    print(f"  Datenverzeichnis : {cfg.data_dir}")
    print(f"  Quelle (Modus)   : {cfg.source_mode}")
    print(f"  Saisons          : {cfg.seasons}")
    try:
        import duckdb, sklearn  # noqa: F401
        print("  duckdb/sklearn   : OK")
    except Exception as exc:  # noqa: BLE001
        print(f"  Abhängigkeiten   : FEHLT ({exc})")
    with GridironStore(cfg) as store:
        print(f"  Plays im Lake    : {store.count_plays()}")
    print("\nBereit. 'ingest' lädt Daten, 'train' baut das Modell, 'scout' analysiert.")


def cmd_ingest(cfg, args) -> None:
    from gridiron.ingest import ingest
    seasons = args.seasons or cfg.seasons
    print(f"Lade Play-by-Play (Quelle: {cfg.source_mode}, Saisons {seasons}) …")
    try:
        res = ingest(cfg, seasons=seasons)
    except RuntimeError as exc:
        print(f"\nFehler beim Laden:\n  {exc}")
        return
    print(f"  Neu/aktualisiert : {res.inserted}")
    print(f"  Bestand gesamt   : {res.total_in_store}")


def cmd_stats(cfg, args) -> None:
    with GridironStore(cfg) as store:
        s = store.stats()
        teams = store.teams()
    print("Bestand im Daten-Lake")
    print("=" * 40)
    for k, v in s.items():
        print(f"  {k:14s}: {v}")
    if teams:
        print(f"  Teams         : {', '.join(teams)}")


def cmd_train(cfg, args) -> None:
    from gridiron.model import train
    print("Trainiere Pass/Lauf-Modell (CPU) …")
    r = train(cfg)
    if not r.trained:
        print(f"  Nicht trainiert: {r.message}")
        return
    print(f"  Plays            : {r.n}")
    print(f"  Treffergenauigk. : {r.accuracy:.3f}  (Baseline {r.baseline:.3f})")
    print(f"  LogLoss          : {r.logloss:.3f}")
    lift = (r.accuracy - r.baseline) * 100
    print(f"  Mehrwert ggü. Raten: {lift:+.1f} Prozentpunkte")


def cmd_scout(cfg, args) -> None:
    from gridiron.tendencies import scout, render
    rep = scout(cfg, args.team.upper(), season=args.season)
    print(render(rep))


def cmd_predict(cfg, args) -> None:
    from gridiron.model import Predictor
    try:
        pred = Predictor(cfg)
    except FileNotFoundError as exc:
        print(exc)
        return
    sit = {"team": args.team.upper(), "down": args.down, "ydstogo": args.ydstogo,
           "yardline_100": args.yardline, "score_differential": args.score_diff,
           "qtr": args.qtr, "game_seconds_remaining": args.gsr,
           "shotgun": args.shotgun, "no_huddle": args.no_huddle}
    a = pred.assess(sit)
    print(f"Situation: {args.team.upper()} | {args.down}. & {args.ydstogo}, "
          f"{args.yardline} Yards zur EZ, Q{args.qtr}, Diff {args.score_diff}"
          f"{', Shotgun' if args.shotgun else ''}")
    print("=" * 50)
    print(f"  Pass-Wahrscheinlichkeit : {a['pass_prob'] * 100:.0f}%")
    print(f"  Lauf-Wahrscheinlichkeit : {a['run_prob'] * 100:.0f}%")
    print(f"  Wahrscheinlicher Call   : {a['likely']}")
    print(f"  Vorhersehbarkeit        : {a['predictability'] * 100:.0f}%  "
          f"({'klare Tendenz' if a['predictability'] > 0.4 else 'ausgeglichen'})")


def cmd_serve(cfg, args) -> None:
    import uvicorn
    from gridiron.web import create_app
    print(f"Starte Gridiron-Web auf http://{args.host}:{args.port}  (Strg+C beendet)")
    uvicorn.run(create_app(cfg), host=args.host, port=args.port)


COMMANDS = {"doctor": cmd_doctor, "ingest": cmd_ingest, "stats": cmd_stats,
            "train": cmd_train, "scout": cmd_scout, "predict": cmd_predict,
            "serve": cmd_serve}


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="gridiron",
                                     description="Gridiron – NFL-Scouting & Tendenzen")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="Umgebung & Bestand prüfen")

    pi = sub.add_parser("ingest", help="Play-by-Play laden (nflverse)")
    pi.add_argument("--seasons", type=int, nargs="*", help="z.B. --seasons 2023 2024")

    sub.add_parser("stats", help="Bestand anzeigen")
    sub.add_parser("train", help="Pass/Lauf-Modell trainieren")

    ps = sub.add_parser("scout", help="Scouting-Report für ein Team")
    ps.add_argument("team", help="Team-Kürzel, z.B. KC, BUF, SF")
    ps.add_argument("--season", type=int, default=None)

    pp = sub.add_parser("predict", help="Live-Vorhersage Pass/Lauf")
    pp.add_argument("--team", required=True)
    pp.add_argument("--down", type=int, default=1)
    pp.add_argument("--ydstogo", type=int, default=10)
    pp.add_argument("--yardline", type=int, default=50, help="Yards bis zur gegn. EZ")
    pp.add_argument("--score-diff", dest="score_diff", type=int, default=0)
    pp.add_argument("--qtr", type=int, default=1)
    pp.add_argument("--gsr", type=int, default=1800, help="Restsekunden im Spiel")
    pp.add_argument("--shotgun", action="store_true")
    pp.add_argument("--no-huddle", dest="no_huddle", action="store_true")

    pse = sub.add_parser("serve", help="Web-Oberfläche (folgt)")
    pse.add_argument("--host", default="0.0.0.0")
    pse.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    cfg = load_config()
    COMMANDS[args.command](cfg, args)


if __name__ == "__main__":
    main()
