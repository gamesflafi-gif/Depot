"""Kommandozeilen-Interface der Aktien-KI.

Beispiele:
    python -m stockai.cli train
    python -m stockai.cli analyze
    python -m stockai.cli snapshot     # aktuellen Zustand fürs Lernen sichern
    python -m stockai.cli label        # fällige Snapshots labeln
    python -m stockai.cli learn        # snapshot + label + train (ein Lernzyklus)
    python -m stockai.cli backtest
    python -m stockai.cli history
"""
from __future__ import annotations

import argparse
import logging
import sys

from stockai.config import load_config
from stockai import pipeline, backtest as bt
from stockai.model.store import ModelStore


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )


# --------------------------------------------------------------------------- #
def cmd_train(cfg, args) -> None:
    print("Trainiere Modell auf historischen Kursen + gesammelten Lerndaten …")
    result = pipeline.train(cfg)
    print(f"\n✔ Training abgeschlossen ({result.n_train} Train / {result.n_test} Test)")
    print("  Out-of-Sample-Metriken:")
    for k, v in result.metrics.items():
        print(f"    {k:10s}: {v:.3f}")
    print("\n  Wichtigste Merkmale:")
    for name, imp in list(result.feature_importance.items())[:8]:
        print(f"    {name:18s}: {imp:.3f}")


def cmd_analyze(cfg, args) -> None:
    print("Analysiere Aktien (Kurse + Live-News) …\n")
    results = pipeline.analyze(cfg)
    if not results:
        print("Keine Ergebnisse (Netzwerk/Ticker prüfen).")
        return

    print(f"{'Ticker':7s} {'Kurs':>9s} {'P(Profit)':>10s} {'Aktion':>11s} "
          f"{'RSI':>5s} {'Sentiment':>10s} {'News':>5s}")
    print("-" * 70)
    for r in results:
        print(
            f"{r.ticker:7s} {r.last_price:9.2f} {r.profit_probability:10.1%} "
            f"{r.action:>11s} {r.rsi_14:5.0f} {r.sentiment_mean:+10.2f} {r.news_count:5d}"
        )

    # Top-Empfehlungen ausführlich
    booming = [r for r in results if r.action in ("BOOM", "KAUFEN")]
    selling = [r for r in results if r.action == "VERKAUFEN"]

    if booming:
        print("\n🚀 Boom-/Kauf-Kandidaten (wohin das Geld tendiert):")
        for r in booming:
            print(f"\n  {r.ticker}  [{r.action}, Konfidenz {r.confidence:.0%}]")
            print(f"    Timing: {r.timing}")
            for reason in r.reasons:
                print(f"      • {reason}")

    if selling:
        print("\n💰 Verkaufs-/Gewinnmitnahme-Kandidaten:")
        for r in selling:
            print(f"\n  {r.ticker}  [VERKAUFEN, Konfidenz {r.confidence:.0%}]")
            print(f"    Timing: {r.timing}")
            for reason in r.reasons:
                print(f"      • {reason}")

    if args.headlines:
        print("\n📰 Wichtigste Schlagzeilen:")
        for r in results:
            if r.top_headlines:
                print(f"\n  {r.ticker}:")
                for h in r.top_headlines[:3]:
                    print(f"    [{h['sentiment']:+.2f}] {h['title']}")


def cmd_snapshot(cfg, args) -> None:
    n = pipeline.snapshot_live(cfg)
    print(f"✔ {n} Snapshot-Zeilen in den Feature-Store geschrieben.")


def cmd_label(cfg, args) -> None:
    n = pipeline.label_pending(cfg)
    print(f"✔ {n} fällige Snapshots mit realer Rendite gelabelt.")


def cmd_learn(cfg, args) -> None:
    """Ein kompletter Lernzyklus: labeln, snapshotten, neu trainieren."""
    labeled = pipeline.label_pending(cfg)
    snap = pipeline.snapshot_live(cfg)
    print(f"✔ {labeled} Zeilen gelabelt, {snap} neue Snapshots gesichert.")
    result = pipeline.train(cfg)
    auc = result.metrics.get("roc_auc", result.metrics.get("accuracy"))
    print(f"✔ Neu trainiert – aktuelle Güte (AUC/Acc): {auc:.3f}")


def cmd_backtest(cfg, args) -> None:
    print("Führe Walk-Forward-Backtest durch …")
    res = bt.run_backtest(cfg, prob_threshold=args.threshold)
    print(f"\n  Test-Tage:          {res.n_test}")
    print(f"  Accuracy:           {res.accuracy:.3f}")
    print(f"  Basisrate (Profit): {res.base_rate:.3f}")
    print(f"  Trefferquote (Sel): {res.selected_hit_rate:.3f}")
    print(f"  Mehrwert (Edge):    {res.edge:+.3f}  (Schwelle {res.threshold})")
    if res.edge and res.edge > 0:
        print("\n  → Das Modell liefert auf den Testdaten einen positiven Mehrwert.")
    else:
        print("\n  → Kein klarer Mehrwert – mehr Daten/Lernzyklen nötig.")


def cmd_history(cfg, args) -> None:
    history = ModelStore(cfg.model_dir).load_history()
    if not history:
        print("Noch keine Lernhistorie vorhanden. Erst 'train' ausführen.")
        return
    print(f"Lernhistorie ({len(history)} Trainingsläufe) – so wird die KI besser:\n")
    print(f"{'#':>3s} {'Zeitpunkt':25s} {'Samples':>8s} {'Acc':>6s} {'AUC':>6s} {'F1':>6s}")
    print("-" * 60)
    for i, h in enumerate(history, 1):
        m = h.get("metrics", {})
        print(
            f"{i:3d} {h.get('timestamp', '')[:19]:25s} {h.get('n_samples', 0):8d} "
            f"{m.get('accuracy', float('nan')):6.3f} "
            f"{m.get('roc_auc', float('nan')):6.3f} "
            f"{m.get('f1', float('nan')):6.3f}"
        )


# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="stockai", description="Lernende KI zur Aktien- & News-Analyse"
    )
    p.add_argument("-c", "--config", default=None, help="Pfad zur config.yaml")
    p.add_argument("-v", "--verbose", action="store_true", help="Ausführliche Logs")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("train", help="Modell (neu) trainieren")

    pa = sub.add_parser("analyze", help="Live-Analyse + Empfehlungen")
    pa.add_argument("--headlines", action="store_true", help="Schlagzeilen anzeigen")

    sub.add_parser("snapshot", help="Aktuellen Zustand fürs Lernen sichern")
    sub.add_parser("label", help="Fällige Snapshots labeln")
    sub.add_parser("learn", help="Voller Lernzyklus (label + snapshot + train)")

    pb = sub.add_parser("backtest", help="Strategie auf Historie testen")
    pb.add_argument("--threshold", type=float, default=0.55)

    sub.add_parser("history", help="Lernfortschritt anzeigen")
    return p


_COMMANDS = {
    "train": cmd_train,
    "analyze": cmd_analyze,
    "snapshot": cmd_snapshot,
    "label": cmd_label,
    "learn": cmd_learn,
    "backtest": cmd_backtest,
    "history": cmd_history,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    cfg = load_config(args.config)
    try:
        _COMMANDS[args.command](cfg, args)
    except Exception as exc:  # benutzerfreundliche Fehlermeldung
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
