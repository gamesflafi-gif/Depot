"""Orchestrierung der Aktien-KI.

Verbindet Datenbeschaffung, Feature-Erzeugung, Lernen und Vorhersage zu
nachvollziehbaren Arbeitsschritten:

    build_history_dataset() – Trainings-Datensatz aus historischen Kursen
    snapshot_live()         – aktuellen Zustand (inkl. echtem News-Sentiment)
                              in den Feature-Store schreiben (für Selbstlernen)
    label_pending()         – fällige Snapshots mit realer Rendite labeln
    train()                 – Modell (neu) trainieren + Lernhistorie schreiben
    analyze()               – Live-Analyse: wer wird profitabel? wohin fließt Geld?

Hinweis zum News-Sentiment: Kostenlose, tagesgenaue Alt-News über 2 Jahre
gibt es nicht. Deshalb werden historische Trainingszeilen mit neutralem
Sentiment (0) gebootstrappt. Über ``snapshot_live`` + ``label_pending`` sammelt
die KI im Betrieb echte Sentiment-/Ergebnis-Paare und lernt das News-Signal
dadurch eigenständig dazu – ihre Präzision verbessert sich mit der Zeit.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from stockai.advisor import recommend
from stockai.config import Config
from stockai.data import provider
from stockai.features.sentiment import SENTIMENT_FEATURES, score_text
from stockai.features.technical import TECHNICAL_FEATURES, add_technical_features
from stockai.model.predictor import Predictor, TrainResult
from stockai.model.store import FeatureStore, ModelStore

log = logging.getLogger(__name__)

# Markt-/Querschnitts-Features: Kontext über alle Ticker hinweg
# ("wohin rotiert das Geld" – relative Stärke + Rang gegenüber den Peers).
MARKET_FEATURES = ["mkt_ret_5d", "rel_strength_20d", "xs_mom_rank", "xs_sent_rank"]

FEATURE_COLUMNS = TECHNICAL_FEATURES + MARKET_FEATURES + SENTIMENT_FEATURES
KEY_COLS = ["ticker", "date"]


def add_market_features(df: pd.DataFrame) -> pd.DataFrame:
    """Ergänzt Querschnitts-Features über alle Ticker je Datum.

    Neben Marktdurchschnitt und relativer Stärke werden **Perzentil-Ränge**
    innerhalb des Universums berechnet (cross-sectional Momentum/Sentiment –
    ein real belegter Effekt: relativ stärkste Werte tendieren weiterzulaufen).
    Bei nur einem Ticker ist der Rang neutral (0.5).
    """
    g = df.groupby("date")
    df["mkt_ret_5d"] = g["ret_5d"].transform("mean")
    df["rel_strength_20d"] = df["ret_20d"] - g["ret_20d"].transform("mean")
    df["xs_mom_rank"] = g["ret_20d"].rank(pct=True)
    if "sent_mean" in df.columns:
        df["xs_sent_rank"] = g["sent_mean"].rank(pct=True)
    else:
        df["xs_sent_rank"] = 0.5
    # Einzel-Ticker / fehlende Werte -> neutraler Rang
    df[["xs_mom_rank", "xs_sent_rank"]] = df[["xs_mom_rank", "xs_sent_rank"]].fillna(0.5)
    return df


# --------------------------------------------------------------------------- #
@dataclass
class TickerAnalysis:
    ticker: str
    last_price: float
    profit_probability: float
    sentiment_mean: float
    news_count: int
    rsi_14: float = 50.0
    momentum_5d: float = 0.0
    price_vs_high_20: float = 1.0
    volatility: float = 0.02
    expected_return: float | None = None
    top_headlines: list[dict] = field(default_factory=list)
    signal: str = ""
    action: str = "HALTEN"
    confidence: float = 0.5
    reasons: list[str] = field(default_factory=list)
    timing: str = ""


# --------------------------------------------------------------------------- #
def _target_from_prices(df: pd.DataFrame, horizon: int, threshold: float) -> pd.Series:
    """1, wenn die Rendite über ``horizon`` Handelstage > ``threshold`` ist."""
    future_return = df["Close"].shift(-horizon) / df["Close"] - 1.0
    return (future_return > threshold).astype("float")


def build_history_dataset(cfg: Config) -> pd.DataFrame:
    """Baut aus historischen Kursen einen gelabelten Trainingsdatensatz.

    Sentiment-Features werden hier neutral (0) gesetzt (siehe Modul-Doc).
    """
    frames: list[pd.DataFrame] = []
    for ticker in cfg.tickers:
        prices = provider.get_prices(cfg, ticker)
        if prices.empty or len(prices) < 60:
            log.warning("Überspringe %s (zu wenig Kurshistorie).", ticker)
            continue
        feat = add_technical_features(prices)
        feat["target"] = _target_from_prices(
            prices, cfg.horizon_days, cfg.profit_threshold
        )
        # Stetige Folge-Rendite als Ziel für das Expected-Return-Modell
        feat["fwd_ret"] = prices["Close"].shift(-cfg.horizon_days) / prices["Close"] - 1.0
        # News-Sentiment je Tag einfügen, damit das Modell daraus lernt.
        # Verfügbar (z.B. Demo) -> echte Reihe; sonst neutral (0).
        sent_hist = provider.get_sentiment_history(cfg, ticker)
        if sent_hist is not None and not sent_hist.empty:
            aligned = sent_hist.reindex(feat.index)
            for col in SENTIMENT_FEATURES:
                feat[col] = aligned[col].values if col in aligned else 0.0
            feat[SENTIMENT_FEATURES] = feat[SENTIMENT_FEATURES].fillna(0.0)
        else:
            for col in SENTIMENT_FEATURES:
                feat[col] = 0.0
        feat["ticker"] = ticker
        feat["date"] = feat.index.strftime("%Y-%m-%d")
        frames.append(feat.reset_index(drop=True))

    if not frames:
        return pd.DataFrame()
    data = pd.concat(frames, ignore_index=True)
    data = add_market_features(data)
    # Letzte ``horizon`` Zeilen je Ticker haben kein gültiges Label -> entfernen
    return data.dropna(subset=FEATURE_COLUMNS + ["target"])


# --------------------------------------------------------------------------- #
def _live_feature_row(cfg: Config, ticker: str) -> tuple[dict, list, float] | None:
    """Aktuelle technische + Sentiment-Features für einen Ticker.

    Returns (feature_dict, scored_news, last_price) oder None.
    """
    prices = provider.get_prices(cfg, ticker)
    if prices.empty or len(prices) < 60:
        return None
    feat = add_technical_features(prices).iloc[-1]
    last_price = float(prices["Close"].iloc[-1])

    news = provider.get_news(cfg, ticker)
    # Sentiment-Features konsistent zur Trainingsquelle (Demo: gekoppelte Reihe;
    # Live: Aggregat der aktuellen News).
    sent_features = provider.get_sentiment_features(cfg, ticker, news=news)
    scored_news = [(item, score_text(item.text)) for item in news]

    row: dict[str, float] = {f: float(feat[f]) for f in TECHNICAL_FEATURES}
    row.update({k: float(v) for k, v in sent_features.items()})
    return row, scored_news, last_price


def _augment_with_market(rows: list[dict]) -> None:
    """Ergänzt Markt-/relative-Stärke-/Rang-Features über die aktuellen Zeilen."""
    if not rows:
        return
    mkt5 = float(np.mean([r.get("ret_5d", 0.0) for r in rows]))
    mkt20 = float(np.mean([r.get("ret_20d", 0.0) for r in rows]))
    n = len(rows)
    mom = pd.Series([r.get("ret_20d", 0.0) for r in rows]).rank(pct=True)
    sent = pd.Series([r.get("sent_mean", 0.0) for r in rows]).rank(pct=True)
    for i, r in enumerate(rows):
        r["mkt_ret_5d"] = mkt5
        r["rel_strength_20d"] = float(r.get("ret_20d", 0.0) - mkt20)
        r["xs_mom_rank"] = float(mom.iloc[i]) if n > 1 else 0.5
        r["xs_sent_rank"] = float(sent.iloc[i]) if n > 1 else 0.5


def snapshot_live(cfg: Config) -> int:
    """Schreibt den aktuellen Zustand aller Ticker in den Feature-Store.

    Diese Snapshots haben zunächst kein Label (``target`` = NaN). Sobald der
    Horizont verstrichen ist, füllt ``label_pending`` die echte Rendite ein.
    """
    store = FeatureStore(cfg.store_dir)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows: list[dict] = []
    for ticker in cfg.tickers:
        result = _live_feature_row(cfg, ticker)
        if result is None:
            continue
        row, _, last_price = result
        row.update(
            {
                "ticker": ticker,
                "date": today,
                "snapshot_close": last_price,
                "target": np.nan,
            }
        )
        rows.append(row)
    _augment_with_market(rows)
    if not rows:
        return 0
    store.update(pd.DataFrame(rows), key_cols=KEY_COLS)
    return len(rows)


def label_pending(cfg: Config) -> int:
    """Labelt Snapshot-Zeilen, deren Vorhersage-Horizont verstrichen ist.

    Holt aktuelle Kurse und vergleicht sie mit dem Snapshot-Kurs.
    Returns: Anzahl neu gelabelter Zeilen.
    """
    store = FeatureStore(cfg.store_dir)
    df = store.load()
    if df.empty or "snapshot_close" not in df.columns:
        return 0

    pending = df[df["target"].isna() & df["snapshot_close"].notna()]
    if pending.empty:
        return 0

    cutoff = datetime.now(timezone.utc).date() - timedelta(days=cfg.horizon_days)
    labeled = 0
    for ticker in pending["ticker"].unique():
        prices = provider.get_prices_window(cfg, ticker, period="3mo")
        if prices.empty:
            continue
        for idx, row in pending[pending["ticker"] == ticker].iterrows():
            snap_date = datetime.strptime(row["date"], "%Y-%m-%d").date()
            if snap_date > cutoff:
                continue  # Horizont noch nicht erreicht
            future = prices[prices.index.date > snap_date]
            if future.empty:
                continue
            future_price = float(future["Close"].iloc[min(cfg.horizon_days - 1, len(future) - 1)])
            ret = future_price / float(row["snapshot_close"]) - 1.0
            df.loc[idx, "target"] = float(ret > cfg.profit_threshold)
            labeled += 1

    if labeled:
        store.update(df, key_cols=KEY_COLS)
    return labeled


# --------------------------------------------------------------------------- #
def _combined_training_data(cfg: Config) -> pd.DataFrame:
    """Bootstrap-Historie + gelabelte Live-Snapshots zusammenführen."""
    history = build_history_dataset(cfg)
    store_df = FeatureStore(cfg.store_dir).load()
    labeled_live = pd.DataFrame()
    if not store_df.empty and "target" in store_df.columns:
        labeled_live = store_df.dropna(subset=["target"])
        labeled_live = labeled_live[
            [c for c in FEATURE_COLUMNS + ["target", "ticker", "date"] if c in labeled_live.columns]
        ]
    frames = [f for f in [history, labeled_live] if not f.empty]
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    # Sicherstellen, dass alle Feature-Spalten existieren (Randfall: leere
    # Historie + Live-Zeilen ohne alle Spalten) -> sonst KeyError beim Training.
    for col in FEATURE_COLUMNS:
        if col not in combined.columns:
            combined[col] = np.nan
    # Nach Datum sortieren, damit der zeitliche Train/Test-Split korrekt ist
    # (sonst landen ganze Ticker im Test -> verzerrte Bewertung).
    if "date" in combined.columns:
        combined = combined.sort_values("date").reset_index(drop=True)
    return combined


def resolve_model_type(
    cfg: Config, data: pd.DataFrame, feature_names: list[str] | None = None
) -> tuple[str, list | None]:
    """Löst ``type: auto`` zu einem konkreten Modelltyp auf (per CV).

    Returns (model_type, ranking_oder_None).
    """
    model_type = cfg.model.get("type", "gradient_boosting")
    if model_type != "auto":
        return model_type, None
    from stockai.model.selection import select_best_model

    sel = select_best_model(
        data, feature_names or FEATURE_COLUMNS,
        random_state=int(cfg.model.get("random_state", 42)),
    )
    return sel.best_type, sel.ranking


def train(cfg: Config) -> TrainResult:
    """Trainiert das Modell neu und protokolliert die Güte in der Lernhistorie."""
    data = _combined_training_data(cfg)
    if data.empty:
        raise RuntimeError("Keine Trainingsdaten verfügbar (Netzwerk/Ticker prüfen).")

    random_state = int(cfg.model.get("random_state", 42))
    model_type, selected_via = resolve_model_type(cfg, data)
    if selected_via is not None:
        log.info("Auto-Auswahl: %s (Ranking: %s)", model_type, selected_via)

    model_store = ModelStore(cfg.model_dir)
    # Getunte Hyperparameter anwenden, sofern vorhanden (siehe 'tune')
    tuned = model_store.load_tuned_params(model_type)
    predictor = Predictor(
        feature_names=FEATURE_COLUMNS,
        model_type=model_type,
        random_state=random_state,
        calibrate=bool(cfg.model.get("calibrate", False)),
        params=tuned,
    )
    # Ehrliche Präzisionsschätzung per Zeitreihen-CV (vor dem finalen Fit)
    cv_metrics = predictor.cross_validate(data, target_col="target")
    result = predictor.train(
        data, target_col="target", test_size=float(cfg.model.get("test_size", 0.2))
    )
    result.cv_metrics = cv_metrics
    # Expected-Return-Modell (Regression) mittrainieren, falls Daten vorhanden
    predictor.fit_regressor(data, ret_col="fwd_ret")

    # Anzahl der real gelabelten Live-Snapshots direkt aus dem Store ablesen
    # (kein erneuter, teurer Aufbau des Historien-Datensatzes nötig).
    store_df = FeatureStore(cfg.store_dir).load()
    n_live_labeled = (
        int(store_df["target"].notna().sum())
        if not store_df.empty and "target" in store_df.columns
        else 0
    )

    model_store.save_model(predictor)
    model_store.append_history(
        {
            "model_type": predictor.model_type,
            "calibrated": predictor.calibrate,
            "n_samples": int(len(data)),
            "n_train": result.n_train,
            "n_test": result.n_test,
            "n_live_labeled": n_live_labeled,
            "metrics": result.metrics,
            "cv_metrics": result.cv_metrics,
            "selected_via": selected_via,
            "top_features": dict(list(result.feature_importance.items())[:8]),
        }
    )
    return result


# --------------------------------------------------------------------------- #
def learning_curve(cfg: Config, steps: int = 5) -> list[dict]:
    """Belegt die Selbstverbesserung: trainiert auf wachsenden Datenmengen.

    Auf einem festen, zeitlich späteren Holdout wird gemessen, wie die Güte mit
    mehr Trainingsdaten steigt. Jeder Punkt wird in die Lernhistorie geschrieben,
    sodass die steigende Präzision in CLI und Dashboard sichtbar wird.
    """
    data = _combined_training_data(cfg)
    if data.empty:
        raise RuntimeError("Keine Daten für die Lernkurve verfügbar.")
    data = data.dropna(subset=FEATURE_COLUMNS + ["target"]).reset_index(drop=True)

    holdout_start = int(len(data) * 0.8)
    train_pool, holdout = data.iloc[:holdout_start], data.iloc[holdout_start:]
    X_hold = holdout[FEATURE_COLUMNS].values
    y_hold = holdout["target"].astype(int).values

    # Modelltyp einmal auflösen (auto), damit alle Stufen vergleichbar sind
    model_type, _ = resolve_model_type(cfg, data)
    calibrate = bool(cfg.model.get("calibrate", False))

    model_store = ModelStore(cfg.model_dir)
    curve: list[dict] = []
    for frac in [(i + 1) / steps for i in range(steps)]:
        n = max(50, int(len(train_pool) * frac))
        subset = train_pool.iloc[:n]
        predictor = Predictor(
            feature_names=FEATURE_COLUMNS,
            model_type=model_type,
            random_state=int(cfg.model.get("random_state", 42)),
            calibrate=calibrate,
        )
        predictor.estimator.fit(subset[FEATURE_COLUMNS].values, subset["target"].astype(int).values)
        predictor.is_fitted = True
        metrics = predictor._evaluate(X_hold, y_hold)
        entry = {
            "model_type": predictor.model_type,
            "n_samples": int(n),
            "n_train": int(n),
            "n_test": int(len(holdout)),
            "stage": f"{int(frac * 100)}% der Trainingsdaten",
            "metrics": metrics,
        }
        model_store.append_history(entry)
        curve.append(entry)
        # Das auf den meisten Daten trainierte Modell als finales speichern
        if frac == 1.0:
            model_store.save_model(predictor)
    return curve


# --------------------------------------------------------------------------- #
def analyze(
    cfg: Config, retrain_if_missing: bool = True, universe: list[str] | None = None
) -> list[TickerAnalysis]:
    """Live-Analyse: berechnet je Ticker die Profitabilitäts-Wahrscheinlichkeit.

    Das Ranking zeigt, *wer* wahrscheinlich profitabel wird und *wohin*
    (relativ) das Kapital tendiert. ``universe`` überschreibt optional die zu
    bewertenden Ticker (z.B. Aktien + ETFs für den Sparplan).
    """
    model_store = ModelStore(cfg.model_dir)
    predictor = model_store.load_model()
    if predictor is None:
        if not retrain_if_missing:
            raise RuntimeError("Kein trainiertes Modell vorhanden. Bitte zuerst 'train'.")
        log.info("Kein Modell gefunden – trainiere zunächst …")
        train(cfg)
        predictor = model_store.load_model()

    # 1. Durchgang: Features je Ticker sammeln
    collected: list[tuple[str, dict, list, float]] = []
    rows: list[dict] = []
    for ticker in (universe if universe is not None else cfg.tickers):
        live = _live_feature_row(cfg, ticker)
        if live is None:
            continue
        row, scored_news, last_price = live
        collected.append((ticker, row, scored_news, last_price))
        rows.append(row)
    # Markt-/relative-Stärke-Features über alle Ticker ergänzen
    _augment_with_market(rows)

    # 2. Durchgang: Vorhersage + Empfehlung
    results: list[TickerAnalysis] = []
    for ticker, row, scored_news, last_price in collected:
        X = pd.DataFrame([row])[FEATURE_COLUMNS]
        proba = float(predictor.predict_proba(X)[0])
        er = predictor.predict_return(X)
        expected_return = float(er[0]) if er is not None else None

        scored_sorted = sorted(scored_news, key=lambda kv: abs(kv[1]), reverse=True)
        headlines = [
            {
                "title": item.title,
                "sentiment": round(score, 3),
                "source": item.source,
                "link": item.link,
            }
            for item, score in scored_sorted[:5]
        ]

        macd_hist = row.get("macd", 0.0) - row.get("macd_signal", 0.0)
        rec = recommend(
            profit_probability=proba,
            rsi_14=row.get("rsi_14", 50.0),
            momentum_5d=row.get("ret_5d", 0.0),
            price_vs_high_20=row.get("price_vs_high_20", 1.0),
            macd_hist=macd_hist,
            sentiment_mean=row.get("sent_mean", 0.0),
        )
        results.append(
            TickerAnalysis(
                ticker=ticker,
                last_price=last_price,
                profit_probability=proba,
                sentiment_mean=row.get("sent_mean", 0.0),
                news_count=int(row.get("news_count", 0)),
                rsi_14=row.get("rsi_14", 50.0),
                momentum_5d=row.get("ret_5d", 0.0),
                price_vs_high_20=row.get("price_vs_high_20", 1.0),
                volatility=float(row.get("vol_20d", 0.02) or 0.02),
                expected_return=expected_return,
                top_headlines=headlines,
                signal=_signal(proba),
                action=rec.action,
                confidence=rec.confidence,
                reasons=rec.reasons,
                timing=rec.timing,
            )
        )

    results.sort(key=lambda r: r.profit_probability, reverse=True)
    return results


def _signal(proba: float) -> str:
    if proba >= 0.60:
        return "STARK (Geld fließt wahrscheinlich hier hin)"
    if proba >= 0.52:
        return "leicht positiv"
    if proba <= 0.40:
        return "negativ (eher meiden)"
    return "neutral"
