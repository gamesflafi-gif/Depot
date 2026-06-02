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
    model = ModelStore(cfg.model_dir).load_model()
    mtype = model.model_type if model else cfg.model.get("type")
    calib = " (kalibriert)" if model and model.calibrate else ""
    print(f"\n✔ Training abgeschlossen ({result.n_train} Train / {result.n_test} Test)")
    print(f"  Gewähltes Modell: {mtype}{calib}")
    cv = result.cv_metrics
    if cv:
        print("  Kreuzvalidierung (zeitlich, ehrliche Präzisionsschätzung):")
        print(f"    ROC-AUC : {cv.get('cv_roc_auc_mean', float('nan')):.3f} "
              f"± {cv.get('cv_roc_auc_std', float('nan')):.3f}")
        print(f"    Accuracy: {cv.get('cv_accuracy_mean', float('nan')):.3f} "
              f"± {cv.get('cv_accuracy_std', float('nan')):.3f}  "
              f"({cv.get('cv_folds', 0)} Folds)")
    print("  Finale Out-of-Sample-Metriken:")
    for k, v in result.metrics.items():
        print(f"    {k:10s}: {v:.3f}")
    print("\n  Wichtigste Merkmale:")
    for name, imp in list(result.feature_importance.items())[:8]:
        print(f"    {name:18s}: {imp:.3f}")


def cmd_compare(cfg, args) -> None:
    """Vergleicht Bar-Intervalle (z.B. Tagesdaten vs. Intraday) per CV."""
    from stockai.compare import compare_intervals

    print(f"Vergleiche Intervalle {args.intervals} (ehrliche Zeitreihen-CV) …\n")
    rows = compare_intervals(cfg, args.intervals)
    print(f"  {'Intervall':12s}{'Samples':>9s}{'CV-AUC':>9s}{'CV-Acc':>9s}")
    print("  " + "-" * 39)
    valid = []
    for r in rows:
        auc = r.get("auc", float("nan"))
        print(f"  {r['interval']:12s}{r['n']:9d}{auc:9.3f}{r.get('acc', float('nan')):9.3f}"
              + ("  ⚠ " + r["error"][:40] if r.get("error") else ""))
        if auc == auc:
            valid.append((r["interval"], auc))
    if len(valid) >= 2:
        best = max(valid, key=lambda t: t[1])
        print(f"\n  → Beste CV-AUC: {best[0]} ({best[1]:.3f}). "
              "Höhere AUC = präzisere Vorhersage.")
    else:
        print("\n  Zu wenige auswertbare Intervalle (Datenquelle/Keys prüfen).")


def cmd_alerts(cfg, args) -> None:
    """Prüft Live-Kurse auf starke Bewegungen; optional per Telegram."""
    from stockai import alerts as al
    from stockai import notify

    res = al.check_alerts(cfg, move_pct=args.move_pct)
    report = al.render_alerts(res)
    if not res.has_alerts:
        print("Keine starken Bewegungen.")
        return
    print(report)
    if args.notify:
        ok, channel = notify.notify(report)
        print(f"\n  Benachrichtigung ({channel}): " +
              ("gesendet ✔" if ok else "nicht gesendet"))


def cmd_monitor(cfg, args) -> None:
    """Near-realtime-Überwachung: prüft alle N Minuten auf starke Bewegungen."""
    import time
    from stockai import alerts as al
    from stockai import notify

    print(f"Live-Monitor aktiv (alle {args.interval} Min, Schwelle {args.move_pct}%). "
          "Beenden mit Strg+C.")
    while True:
        try:
            res = al.check_alerts(cfg, move_pct=args.move_pct)
            if res.has_alerts:
                report = al.render_alerts(res)
                print(report + "\n")
                if args.notify:
                    notify.notify(report)
        except Exception as exc:
            print(f"Monitor-Fehler: {exc}")
        time.sleep(max(1, args.interval) * 60)


def cmd_live(cfg, args) -> None:
    """Aktuelle Live-Kurse (Krypto via Binance, Aktien via Finnhub-Key)."""
    from stockai.data.live import get_quote

    syms = args.symbols if args.symbols else (cfg.tickers + cfg.etfs + cfg.crypto)
    print(f"{'Symbol':10s}{'Live-Kurs':>14s}{'Tag %':>10s}{'Quelle':>10s}")
    print("-" * 44)
    for s in syms:
        q = get_quote(s)
        if q:
            print(f"{s:10s}{q.price:14.2f}{q.change_pct:+10.2f}{q.source:>10s}")
        else:
            print(f"{s:10s}{'–':>14s}{'–':>10s}{'(kein Live)':>10s}")


def cmd_doctor(cfg, args) -> None:
    """Diagnose: Konfiguration + Erreichbarkeit der Live-Datenquellen prüfen."""
    import os
    import urllib.request

    print("Diagnose der Aktien-KI\n" + "=" * 40)
    source = cfg.raw.get("data_source", "live")
    print(f"  Datenquelle (config):  {source}")
    print(f"  Ticker:                {', '.join(cfg.tickers)}")
    print(f"  Modelltyp:             {cfg.model.get('type')} "
          f"(calibrate={cfg.model.get('calibrate', False)})")
    key_set = bool(os.environ.get("STOCKAI_NEWSAPI_KEY"))
    print(f"  NewsAPI-Key gesetzt:   {'ja' if key_set else 'nein'}")
    from stockai import notify as _nf
    if _nf.telegram_configured():
        chan = "Telegram"
    elif _nf.webhook_configured():
        chan = "Webhook"
    else:
        chan = "keiner"
    print(f"  Benachrichtigung:      {chan}")

    def _reach(url: str) -> str:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "stockai-doctor"})
            with urllib.request.urlopen(req, timeout=6) as r:
                return f"erreichbar (HTTP {r.status})"
        except Exception as exc:
            msg = str(getattr(exc, "code", exc))
            return f"NICHT erreichbar ({msg})"

    print(f"  Kursquelle:            {cfg.raw.get('price_source', 'auto')}")
    import os as _os
    al = bool(_os.environ.get("STOCKAI_ALPACA_KEY") and _os.environ.get("STOCKAI_ALPACA_SECRET"))
    td = bool(_os.environ.get("STOCKAI_TWELVEDATA_KEY"))
    fh = bool(_os.environ.get("STOCKAI_FINNHUB_KEY"))
    stock_src = ("Alpaca" if al else "Twelve Data" if td else "Finnhub" if fh else "kein Key")
    print(f"  Bar-Intervall (config):{cfg.history_interval:>8s}")
    print(f"  Live/Intraday-Aktien:  {stock_src}   (Krypto: Binance, frei)")
    print("\n  Erreichbarkeit der Datenquellen:")
    print(f"    Yahoo Finance:  {_reach('https://query1.finance.yahoo.com')}")
    print(f"    Stooq (direkt): {_reach('https://stooq.com')}")
    print(f"    Binance (Krypto-Live): {_reach('https://api.binance.com')}")
    print(f"    Google News:    {_reach('https://news.google.com')}")
    if key_set:
        print(f"    NewsAPI.org:    {_reach('https://newsapi.org')}")

    print("\n  Empfehlung:")
    if source == "demo":
        print("    • Demo-Modus aktiv – läuft offline. Für echte Daten in")
        print("      config.yaml 'data_source: live' setzen (Netzwerk nötig).")
    else:
        print("    • Live-Modus aktiv. Sind Hosts oben NICHT erreichbar, muss die")
        print("      Netzwerk-Policy der Umgebung diese freigeben.")
    if not key_set:
        print("    • Optional mehr News: export STOCKAI_NEWSAPI_KEY=… (newsapi.org)")


def cmd_tune(cfg, args) -> None:
    """Sucht die besten Hyperparameter (Zeitreihen-CV) und speichert sie."""
    from stockai.model.tuning import tune_model
    from stockai.model.predictor import AUTO_CANDIDATES

    data = pipeline._combined_training_data(cfg)
    if data.empty:
        print("Keine Daten verfügbar.")
        return
    model_type, _ = pipeline.resolve_model_type(cfg, data)
    print(f"Tune Hyperparameter für '{model_type}' (Zeitreihen-CV) …\n")
    res = tune_model(data, pipeline.FEATURE_COLUMNS, model_type,
                     random_state=int(cfg.model.get("random_state", 42)))
    if not res.best_params:
        print(f"Für '{model_type}' ist kein Suchraum definiert "
              f"(z.B. ensemble/sgd_online).")
        return
    print(f"  Beste CV-AUC: {res.best_score:.3f}  "
          f"({res.n_candidates} Kombinationen getestet)")
    print("  Beste Parameter:")
    for k, v in res.best_params.items():
        print(f"    {k}: {v}")
    ModelStore(cfg.model_dir).save_tuned_params(model_type, res.best_params, res.best_score)
    print("\n  ✔ Gespeichert – werden beim nächsten 'train' automatisch angewandt.")


def cmd_scorecard(cfg, args) -> None:
    """Bewertet die Treffsicherheit der Empfehlungen (Walk-Forward)."""
    from stockai import scorecard as sc

    print("Bewerte historische Empfehlungen (Walk-Forward) …\n")
    card = sc.evaluate_recommendations(cfg, prob_threshold=args.threshold)
    print(f"  Empfehlungen gesamt: {card.n_recommendations}")
    print(f"  Trefferquote (handlungsrelevant, ohne HALTEN): {card.overall_hit_rate:.1%}")
    if card.buy_avg_return == card.buy_avg_return:
        print(f"  Ø Rendite nach KAUF-Signal:    {card.buy_avg_return:+.2%}")
    if card.sell_avg_return == card.sell_avg_return:
        print(f"  Ø Rendite nach VERKAUF-Signal: {card.sell_avg_return:+.2%}")

    print(f"\n  {'Aktion':12s}{'Anzahl':>8s}{'Treffer':>10s}{'Ø Rendite':>12s}")
    print("  " + "-" * 42)
    for action in ("BOOM", "KAUFEN", "HALTEN", "VERKAUFEN", "MEIDEN"):
        a = card.by_action.get(action)
        if a:
            print(f"  {action:12s}{a['count']:8d}{a['hit_rate']:10.1%}{a['avg_return']:+12.2%}")

    print(f"\n  Kalibrierung (vorhergesagt vs. tatsächlich profitabel):")
    print(f"  {'P-Bereich':12s}{'Anzahl':>8s}{'Vorhergesagt':>14s}{'Tatsächlich':>13s}")
    print("  " + "-" * 47)
    for c in card.calibration:
        print(f"  {c['bin']:12s}{c['count']:8d}{c['predicted']:14.1%}{c['actual']:13.1%}")


def cmd_ablation(cfg, args) -> None:
    """Misst den Beitrag der News: Technik vs. News vs. kombiniert (CV-AUC)."""
    from stockai.features.technical import TECHNICAL_FEATURES
    from stockai.features.sentiment import SENTIMENT_FEATURES
    from stockai.model.predictor import Predictor

    data = pipeline._combined_training_data(cfg)
    if data.empty:
        print("Keine Daten verfügbar.")
        return
    model_type, _ = pipeline.resolve_model_type(cfg, data)
    rs = int(cfg.model.get("random_state", 42))
    groups = {
        "Nur Technik + Markt": TECHNICAL_FEATURES + pipeline.MARKET_FEATURES,
        "Nur News-Sentiment": SENTIMENT_FEATURES,
        "Kombiniert (alle)": pipeline.FEATURE_COLUMNS,
    }
    print(f"News-Ablation (Modell: {model_type}, Zeitreihen-CV)\n")
    print(f"  {'Feature-Set':24s}{'CV ROC-AUC':>14s}{'CV Accuracy':>14s}")
    print("  " + "-" * 52)
    aucs = {}
    for name, feats in groups.items():
        cv = Predictor(feats, model_type=model_type, random_state=rs).cross_validate(data)
        auc = cv.get("cv_roc_auc_mean", float("nan"))
        acc = cv.get("cv_accuracy_mean", float("nan"))
        aucs[name] = auc
        print(f"  {name:24s}{auc:14.3f}{acc:14.3f}")
    tech = aucs.get("Nur Technik + Markt")
    comb = aucs.get("Kombiniert (alle)")
    if tech == tech and comb == comb:
        delta = comb - tech
        print(f"\n  → News-Beitrag zur Genauigkeit: {delta:+.3f} AUC "
              f"({'hilft' if delta > 0 else 'kein Mehrwert'}).")


def cmd_sweep(cfg, args) -> None:
    """Mehr Backtesting: Strategie über ein Raster aus Schwelle × Positionen."""
    from stockai import strategy as strat

    period = args.period
    print(f"Parameter-Sweep (Walk-Forward, retrain_every={args.retrain_every})…\n")
    print(f"  {'Schwelle':>9s}{'Top-K':>7s}{'Gesamt':>11s}{'CAGR':>9s}"
          f"{'Sharpe':>8s}{'MaxDD':>9s}")
    print("  " + "-" * 53)
    best = None
    for thr in args.thresholds:
        for k in args.top_k:
            try:
                res = strat.run_strategy_backtest(
                    cfg, prob_threshold=thr, top_k=k, period=period,
                    retrain_every=args.retrain_every, train_frac=args.train_frac,
                )
            except Exception as exc:
                print(f"  {thr:9.2f}{k:7d}   Fehler: {exc}")
                continue
            m = res.metrics
            print(f"  {thr:9.2f}{k:7d}{m['total_return']:11.1%}{res.cagr:9.1%}"
                  f"{m['sharpe']:8.2f}{m['max_drawdown']:9.1%}")
            score = m["sharpe"]
            if best is None or score > best[0]:
                best = (score, thr, k)
    if best:
        print(f"\n  → Beste Sharpe-Ratio bei Schwelle {best[1]:.2f}, Top-{best[2]}.")


def cmd_evaluate(cfg, args) -> None:
    """Vergleicht mehrere Modelltypen per Zeitreihen-Kreuzvalidierung."""
    from stockai.model.predictor import AUTO_CANDIDATES, Predictor

    print("Vergleiche Modelle per zeitlicher Kreuzvalidierung …\n")
    data = pipeline._combined_training_data(cfg)
    if data.empty:
        print("Keine Daten verfügbar.")
        return
    print(f"{'Modell':24s} {'AUC':>14s} {'Accuracy':>14s} {'F1':>7s}")
    print("-" * 62)
    rows = []
    for mtype in AUTO_CANDIDATES + ["ensemble", "stacking"]:
        cv = Predictor(pipeline.FEATURE_COLUMNS, model_type=mtype,
                       random_state=int(cfg.model.get("random_state", 42))).cross_validate(data)
        if not cv:
            continue
        rows.append((mtype, cv))
        print(f"{mtype:24s} "
              f"{cv.get('cv_roc_auc_mean', float('nan')):.3f}±{cv.get('cv_roc_auc_std', 0):.3f}  "
              f"{cv.get('cv_accuracy_mean', float('nan')):.3f}±{cv.get('cv_accuracy_std', 0):.3f}  "
              f"{cv.get('cv_f1_mean', float('nan')):6.3f}")
    if rows:
        best = max(rows, key=lambda r: (r[1].get('cv_roc_auc_mean') or 0))
        print(f"\n  Beste mittlere CV-AUC: {best[0]} "
              f"({best[1].get('cv_roc_auc_mean', float('nan')):.3f})")


def cmd_analyze(cfg, args) -> None:
    print("Analysiere Aktien (Kurse + News) …\n")
    results = pipeline.analyze(cfg)
    if not results:
        print("Keine Ergebnisse (Netzwerk/Ticker prüfen).")
        return

    print(f"{'Ticker':7s} {'Typ':>7s} {'Kurs':>10s} {'P(Profit)':>10s} {'E[Rendite]':>11s} "
          f"{'Aktion':>11s} {'RSI':>5s} {'Sentiment':>10s}")
    print("-" * 84)
    for r in results:
        er = f"{r.expected_return:+.1%}" if r.expected_return is not None else "  –"
        print(
            f"{r.ticker:7s} {r.asset_class:>7s} {r.last_price:10.2f} "
            f"{r.profit_probability:10.1%} {er:>11s} "
            f"{r.action:>11s} {r.rsi_14:5.0f} {r.sentiment_mean:+10.2f}"
        )

    # Top-Empfehlungen ausführlich
    booming = [r for r in results if r.action in ("BOOM", "KAUFEN")]
    selling = [r for r in results if r.action == "VERKAUFEN"]

    if booming:
        print("\n🚀 Boom-/Kauf-Kandidaten (wohin das Geld tendiert):")
        for r in booming:
            print(f"\n  {r.ticker}  [{r.action}, Konfidenz {r.confidence:.0%}]")
            if r.horizon_probs:
                hz = " · ".join(f"{h}T {p:.0%}" for h, p in sorted(r.horizon_probs.items()))
                print(f"    Horizonte: {hz}")
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


def cmd_simulate(cfg, args) -> None:
    """Lernkurve: zeigt, wie die Güte mit mehr Trainingsdaten steigt."""
    print("Simuliere Lernfortschritt (Training auf wachsenden Datenmengen) …\n")
    curve = pipeline.learning_curve(cfg, steps=args.steps)
    print(f"{'Stufe':28s} {'Samples':>8s} {'Acc':>6s} {'AUC':>6s} {'F1':>6s}")
    print("-" * 58)
    for entry in curve:
        m = entry["metrics"]
        print(
            f"{entry['stage']:28s} {entry['n_samples']:8d} "
            f"{m.get('accuracy', float('nan')):6.3f} "
            f"{m.get('roc_auc', float('nan')):6.3f} "
            f"{m.get('f1', float('nan')):6.3f}"
        )
    first = curve[0]["metrics"].get("roc_auc")
    last = curve[-1]["metrics"].get("roc_auc")
    if first is not None and last is not None:
        delta = last - first
        trend = "↑ besser" if delta > 0 else "↓ schlechter" if delta < 0 else "→ gleich"
        print(f"\n  AUC von {first:.3f} → {last:.3f}  ({trend}, Δ {delta:+.3f})")
    print("\n  → Die Lernhistorie wurde aktualisiert (siehe 'history' / Dashboard).")


def cmd_portfolio(cfg, args) -> None:
    """Konkreter Allokationsvorschlag auf Basis der Analyse."""
    from stockai.portfolio import build_portfolio

    print(f"Erstelle Portfolio-Vorschlag für {args.capital:,.0f} Kapital …\n")
    analyses = pipeline.analyze(cfg)
    if not analyses:
        print("Keine Analyse-Ergebnisse (Netzwerk/Ticker prüfen).")
        return
    pf = build_portfolio(
        analyses, capital=args.capital, max_position_pct=args.max_position,
        sectors=cfg.sectors, max_sector_pct=args.max_sector,
    )
    if not pf.allocations:
        print("Aktuell keine Kaufkandidaten – Empfehlung: investiert nicht / abwarten.")
    else:
        print(f"{'Ticker':7s} {'Aktion':>8s} {'Anteil':>8s} {'Betrag':>12s} "
              f"{'Stück':>10s} {'Kurs':>9s}")
        print("-" * 62)
        for a in pf.allocations:
            print(
                f"{a.ticker:7s} {a.action:>8s} {a.weight:8.1%} {a.amount:12,.2f} "
                f"{a.shares:10.3f} {a.last_price:9.2f}"
            )
        print("-" * 62)
        print(f"{'Investiert':7s} {'':>8s} {pf.invested / pf.capital:8.1%} "
              f"{pf.invested:12,.2f}")
        print(f"{'Cash':7s} {'':>8s} {pf.cash / pf.capital:8.1%} {pf.cash:12,.2f}")
    if pf.sells:
        print(f"\n  Verkaufen/Meiden: {', '.join(pf.sells)}")


def cmd_strategy(cfg, args) -> None:
    """Walk-Forward-Strategie-Backtest mit P&L, Sharpe und Equity-Kurve."""
    from stockai import strategy as strat

    period = getattr(args, "period", None)
    capital = getattr(args, "capital", 1.0)
    print("Simuliere die Strategie über die Historie (Walk-Forward) …\n")
    res = strat.run_strategy_backtest(
        cfg, prob_threshold=args.threshold, top_k=args.top_k,
        period=period, initial_capital=capital,
        retrain_every=getattr(args, "retrain_every", 1),
        train_frac=getattr(args, "train_frac", 0.4),
        cost_bps=getattr(args, "cost_bps", 10.0),
        regime_filter=not getattr(args, "no_regime", False),
    )
    m, b = res.metrics, res.benchmark_metrics
    print(f"  Zeitraum:            ~{res.years:.1f} Jahre, {res.n_rebalances} Rebalancings "
          f"(netto, Kosten {getattr(args, 'cost_bps', 10.0):.0f} bps)")
    print(f"  {'':22s}{'KI-Strategie':>14s}{'Buy & Hold':>14s}")
    print("  " + "-" * 50)
    print(f"  {'Gesamtrendite':22s}{m['total_return']:13.1%}{b['total_return']:14.1%}")
    print(f"  {'Ø Rendite p.a. (CAGR)':22s}{res.cagr:13.1%}{'':>14s}")
    print(f"  {'Sharpe-Ratio':22s}{m['sharpe']:13.2f}{b['sharpe']:14.2f}")
    print(f"  {'Max. Drawdown':22s}{m['max_drawdown']:13.1%}{b['max_drawdown']:14.1%}")
    print(f"  {'Trefferquote':22s}{m['win_rate']:13.1%}{b['win_rate']:14.1%}")

    if capital and capital != 1.0:
        cur = "€"
        print(f"\n  Startkapital:        {capital:,.2f}{cur}")
        print(f"  Endwert KI:          {res.final_value:,.2f}{cur}  "
              f"(Gewinn/Verlust {res.final_value - capital:+,.2f}{cur})")
        print(f"  Endwert Buy & Hold:  {res.benchmark_value:,.2f}{cur}  "
              f"(Gewinn/Verlust {res.benchmark_value - capital:+,.2f}{cur})")

    edge = m["total_return"] - b["total_return"]
    if edge > 0:
        print(f"\n  → Die KI-Strategie schlägt Buy & Hold um {edge:+.1%}.")
    else:
        print(f"\n  → Die KI-Strategie liegt {edge:+.1%} hinter Buy & Hold.")

    if not args.no_chart:
        path = strat.plot_equity_curve(res, args.out)
        print(f"\n  Equity-Kurve gespeichert: {path}")


def cmd_briefing(cfg, args) -> None:
    """Tägliches Briefing mit Moves-Alerts; optional per Telegram/Webhook."""
    from stockai import briefing as bf
    from stockai import notify

    print("Erstelle Briefing (Analyse + Veränderungen) …\n")
    br = bf.build_briefing(cfg, top_n=args.top_n)
    report = bf.render_briefing(br, cfg)
    print(report)
    if args.notify:
        ok, channel = notify.notify(report)
        print(f"\n  Benachrichtigung ({channel}): " +
              ("gesendet ✔" if ok else "nicht gesendet (Kanal/Netz prüfen, siehe 'doctor')"))


def cmd_evolve(cfg, args) -> None:
    """Selbst-Weiterentwicklung: Modelle vergleichen, bestes tunen & übernehmen."""
    from stockai.model.predictor import AUTO_CANDIDATES, Predictor
    from stockai.model.tuning import tune_model

    data = pipeline._combined_training_data(cfg)
    if data.empty:
        print("Keine Daten verfügbar.")
        return
    rs = int(cfg.model.get("random_state", 42))

    print("Vergleiche Modelle (Zeitreihen-CV) …")
    scored = []
    for mtype in AUTO_CANDIDATES + ["ensemble", "stacking"]:
        cv = Predictor(pipeline.FEATURE_COLUMNS, model_type=mtype,
                       random_state=rs).cross_validate(data)
        auc = cv.get("cv_roc_auc_mean")
        if auc is not None and auc == auc:
            scored.append((mtype, float(auc)))
            print(f"  {mtype:24s} AUC {auc:.3f}")
    if not scored:
        print("Zu wenige Daten für eine Auswertung.")
        return
    scored.sort(key=lambda t: t[1], reverse=True)
    best_type, best_auc = scored[0]
    print(f"\n  → Bestes Modell: {best_type} (AUC {best_auc:.3f})")

    # Bestes Modell tunen und Parameter persistieren
    print("  Optimiere Hyperparameter des besten Modells …")
    res = tune_model(data, pipeline.FEATURE_COLUMNS, best_type, random_state=rs)
    store = ModelStore(cfg.model_dir)
    if res.best_params:
        store.save_tuned_params(best_type, res.best_params, res.best_score)
        print(f"  Beste Parameter (CV-AUC {res.best_score:.3f}): {res.best_params}")
    store.save_preferred_model(best_type)

    # Feature-Auswahl: schlanke Teilmenge testen (weniger Rauschen)
    print("  Prüfe schlankere Feature-Auswahl …")
    store.clear_selected_features()
    selected, full_auc, sel_auc = pipeline.select_features(
        data, best_type, rs, cfg.horizon_days)
    chosen_feats = "alle"
    if (sel_auc == sel_auc and full_auc == full_auc        # nicht NaN
            and sel_auc >= full_auc - 0.003 and len(selected) < len(pipeline.FEATURE_COLUMNS)):
        store.save_selected_features(selected)
        chosen_feats = f"{len(selected)}/{len(pipeline.FEATURE_COLUMNS)}"
        print(f"    → schlanker: {len(selected)} Features (AUC {sel_auc:.3f} "
              f"vs voll {full_auc:.3f}) übernommen.")
    else:
        print("    → volle Feature-Liste bleibt am besten.")

    # finales Training (nutzt Champion + getunte Params + Feature-Auswahl)
    result = pipeline.train(cfg)
    store.append_history({
        "event": "evolve", "chosen_model": best_type, "features": chosen_feats,
        "candidate_ranking": scored,
        "metrics": result.metrics, "cv_metrics": result.cv_metrics,
    })
    auc = result.metrics.get("roc_auc", result.metrics.get("accuracy"))
    print(f"\n  ✔ Neu trainiert & übernommen (finale Güte ~{auc:.3f}).")
    print("  Die KI hat ihre Konfiguration selbst verbessert.")


def cmd_bot(cfg, args) -> None:
    """Startet den interaktiven Telegram-Bot (läuft dauerhaft)."""
    from stockai.telegram_bot import run_bot

    print("Starte Telegram-Bot (Polling). Beenden mit Strg+C.")
    run_bot(cfg)


def cmd_top(cfg, args) -> None:
    """Wöchentlicher Top-N-Überblick in beide Richtungen; optional per Telegram."""
    from stockai import briefing as bf
    from stockai import notify

    print(f"Erstelle Top-{args.n}-Überblick …\n")
    top, bottom = bf.build_top(cfg, n=args.n)
    report = bf.render_top(top, bottom, args.n)
    print(report)
    if args.notify:
        ok, channel = notify.notify(report)
        print(f"\n  Benachrichtigung ({channel}): " +
              ("gesendet ✔" if ok else "nicht gesendet (Kanal/Netz prüfen, siehe 'doctor')"))


def cmd_sparplan(cfg, args) -> None:
    """Erstellt einen Core-Satellite-Sparplan aus den aktuellen Analysen."""
    from stockai.savings_plan import build_savings_plan
    from stockai import notify

    print(f"Erstelle Sparplan für {args.monthly:.0f}€/Monat "
          f"(Core/ETF-Anteil {args.core_share:.0%}) …\n")
    plan = build_savings_plan(
        cfg, monthly_amount=args.monthly, core_share=args.core_share,
        max_stock_weight=args.max_position, max_stocks=args.max_stocks,
    )
    print(f"{'Instrument':12s}{'Typ':>7s}{'€/Monat':>10s}{'Anteil':>9s}"
          f"{'Aktion':>11s}{'P(Profit)':>11s}")
    print("-" * 62)
    for p in plan.positions:
        print(f"{p.instrument:12s}{p.kind:>7s}{p.monthly:10.2f}{p.weight:9.0%}"
              f"{p.action:>11s}{p.probability:11.0%}")
    print("-" * 62)
    total = sum(p.monthly for p in plan.positions)
    print(f"{'Summe':12s}{'':>7s}{total:10.2f}{total / args.monthly:9.0%}")
    if plan.notes:
        print("\nHinweise:")
        for n in plan.notes:
            print(f"  • {n}")

    if args.report:
        report = notify.render_savings_plan(plan)
        with open(args.report, "w", encoding="utf-8") as fh:
            fh.write(report)
        print(f"\n  Report gespeichert: {args.report}")
    if args.notify:
        report = notify.render_savings_plan(plan)
        ok, channel = notify.notify(report)
        print(f"\n  Benachrichtigung ({channel}): " +
              ("gesendet ✔" if ok else "nicht gesendet (Kanal/Netz prüfen, siehe 'doctor')"))


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
    p.add_argument("--source", choices=["demo", "live"], default=None,
                   help="Datenquelle überschreiben (ohne config.yaml zu ändern)")
    sub = p.add_subparsers(dest="command", required=True)

    pl = sub.add_parser("live", help="Aktuelle Live-Kurse (Krypto frei, Aktien via Key)")
    pl.add_argument("symbols", nargs="*", help="Symbole (leer = alle aus config)")

    pc = sub.add_parser("compare", help="Bar-Intervalle vergleichen (Tagesdaten vs. Intraday)")
    pc.add_argument("--intervals", nargs="+", default=["1d", "15m"],
                    help="zu vergleichende Intervalle (z.B. 1d 1h 15m)")

    pa = sub.add_parser("alerts", help="Live-Alerts: starke Bewegungen melden")
    pa.add_argument("--move-pct", type=float, default=3.0, help="Schwelle in %")
    pa.add_argument("--notify", action="store_true")

    pm = sub.add_parser("monitor", help="Near-realtime-Überwachung (Dauerschleife)")
    pm.add_argument("--interval", type=int, default=10, help="Minuten zwischen Checks")
    pm.add_argument("--move-pct", type=float, default=3.0, help="Schwelle in %")
    pm.add_argument("--notify", action="store_true")

    sub.add_parser("doctor", help="Konfiguration & Datenquellen-Erreichbarkeit prüfen")
    sub.add_parser("train", help="Modell (neu) trainieren")
    sub.add_parser("evaluate", help="Modelltypen per Kreuzvalidierung vergleichen")
    sub.add_parser("ablation", help="Beitrag der News messen (Technik vs. News vs. beides)")
    sub.add_parser("tune", help="Hyperparameter optimieren (und speichern)")

    psw = sub.add_parser("sweep", help="Mehr Backtesting: Raster aus Schwelle × Top-K")
    psw.add_argument("--thresholds", type=float, nargs="+", default=[0.52, 0.55, 0.60])
    psw.add_argument("--top-k", type=int, nargs="+", default=[2, 3, 5])
    psw.add_argument("--period", default=None, help="Zeitraum, z.B. 5y/10y")
    psw.add_argument("--retrain-every", type=int, default=5)
    psw.add_argument("--train-frac", type=float, default=0.3)

    psc = sub.add_parser("scorecard", help="Treffsicherheit der Empfehlungen bewerten")
    psc.add_argument("--threshold", type=float, default=0.55)

    pa = sub.add_parser("analyze", help="Live-Analyse + Empfehlungen")
    pa.add_argument("--headlines", action="store_true", help="Schlagzeilen anzeigen")

    sub.add_parser("snapshot", help="Aktuellen Zustand fürs Lernen sichern")
    sub.add_parser("label", help="Fällige Snapshots labeln")
    sub.add_parser("learn", help="Voller Lernzyklus (label + snapshot + train)")

    ps = sub.add_parser("simulate", help="Lernkurve: Güte vs. Datenmenge zeigen")
    ps.add_argument("--steps", type=int, default=5, help="Anzahl Datenmengen-Stufen")

    pp = sub.add_parser("portfolio", help="Allokationsvorschlag (wohin wie viel)")
    pp.add_argument("--capital", type=float, default=10_000.0, help="Gesamtkapital")
    pp.add_argument("--max-position", type=float, default=0.25,
                    help="Max. Anteil je Position (0..1)")
    pp.add_argument("--max-sector", type=float, default=0.40,
                    help="Max. Anteil je Branche (0..1)")

    pbf = sub.add_parser("briefing", help="Tägliches Briefing mit Moves-Alerts")
    pbf.add_argument("--top-n", type=int, default=5)
    pbf.add_argument("--notify", action="store_true", help="per Telegram/Webhook senden")

    sub.add_parser("bot", help="Interaktiven Telegram-Bot starten (dauerhaft)")
    sub.add_parser("evolve", help="Selbst-Weiterentwicklung: bestes Modell wählen & tunen")

    pt = sub.add_parser("top", help="Top-N in beide Richtungen (z.B. wöchentlich)")
    pt.add_argument("--n", type=int, default=5)
    pt.add_argument("--notify", action="store_true", help="per Telegram/Webhook senden")

    psp = sub.add_parser("sparplan", help="Sparplan (ETF-Core + beste Aktien) erstellen")
    psp.add_argument("--monthly", type=float, default=100.0, help="Sparbetrag €/Monat")
    psp.add_argument("--core-share", type=float, default=0.5,
                     help="Anteil in breite ETFs (0..1)")
    psp.add_argument("--max-position", type=float, default=0.15,
                     help="Max. Anteil je Einzelaktie")
    psp.add_argument("--max-stocks", type=int, default=5, help="Max. Einzelaktien")
    psp.add_argument("--report", default=None, help="Report als Markdown speichern")
    psp.add_argument("--notify", action="store_true",
                     help="Report an STOCKAI_WEBHOOK_URL senden")

    pst = sub.add_parser("strategy", help="P&L-Backtest + Equity-Kurve vs. Buy&Hold")
    pst.add_argument("--threshold", type=float, default=0.55)
    pst.add_argument("--top-k", type=int, default=3, help="Max. Positionen je Rebalancing")
    pst.add_argument("--capital", type=float, default=1.0, help="Startkapital in € (z.B. 500)")
    pst.add_argument("--period", default=None,
                     help="Zeitraum, z.B. 10y (überschreibt history_period)")
    pst.add_argument("--retrain-every", type=int, default=1,
                     help="Modell nur alle N Rebalancings neu trainieren (schneller)")
    pst.add_argument("--train-frac", type=float, default=0.4,
                     help="Anteil der Historie als Anfangs-Training (Rest wird gehandelt)")
    pst.add_argument("--cost-bps", type=float, default=10.0,
                     help="Transaktionskosten je Umschichtung in Basispunkten (10 = 0,1%)")
    pst.add_argument("--no-regime", action="store_true",
                     help="Regime-Bremse deaktivieren (immer voll investiert)")
    pst.add_argument("--out", default="equity_curve.png", help="Pfad für den Chart")
    pst.add_argument("--no-chart", action="store_true", help="Keinen Chart erzeugen")

    pb = sub.add_parser("backtest", help="Signalgüte auf Historie testen (Edge)")
    pb.add_argument("--threshold", type=float, default=0.55)

    sub.add_parser("history", help="Lernfortschritt anzeigen")
    return p


_COMMANDS = {
    "doctor": cmd_doctor,
    "live": cmd_live,
    "compare": cmd_compare,
    "alerts": cmd_alerts,
    "monitor": cmd_monitor,
    "train": cmd_train,
    "evaluate": cmd_evaluate,
    "ablation": cmd_ablation,
    "sweep": cmd_sweep,
    "tune": cmd_tune,
    "scorecard": cmd_scorecard,
    "analyze": cmd_analyze,
    "snapshot": cmd_snapshot,
    "label": cmd_label,
    "learn": cmd_learn,
    "simulate": cmd_simulate,
    "portfolio": cmd_portfolio,
    "briefing": cmd_briefing,
    "bot": cmd_bot,
    "evolve": cmd_evolve,
    "top": cmd_top,
    "sparplan": cmd_sparplan,
    "strategy": cmd_strategy,
    "backtest": cmd_backtest,
    "history": cmd_history,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    cfg = load_config(args.config)
    if args.source:  # globales Flag überschreibt config + Env
        cfg.raw["data_source"] = args.source
    try:
        _COMMANDS[args.command](cfg, args)
    except Exception as exc:  # benutzerfreundliche Fehlermeldung
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
