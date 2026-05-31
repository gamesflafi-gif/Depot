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
# ("wohin rotiert das Geld" + Markt-Regime: Trend & Volatilitätslage).
MARKET_FEATURES = ["mkt_ret_5d", "rel_strength_20d", "xs_mom_rank", "xs_sent_rank",
                   "mkt_trend", "mkt_vol"]

# Muster-Gedächtnis: erwartete Folge-Rendite für den aktuellen, wiederkehrenden
# Kurs-Zustand + Analog-Mustererkennung (ähnliche historische Kursverläufe).
PATTERN_FEATURES = ["pattern_mem", "analog_mem"]

# Individuelles "Eigenprofil" je Wert: wie sich genau dieser Titel bisher
# verhalten hat (kausale, historische Profitrate) – Individualität pro Aktie.
INDIVIDUAL_FEATURES = ["ticker_bias"]

FEATURE_COLUMNS = (
    TECHNICAL_FEATURES + MARKET_FEATURES + SENTIMENT_FEATURES
    + PATTERN_FEATURES + INDIVIDUAL_FEATURES
)
KEY_COLS = ["ticker", "date"]


def ticker_bias(prices: pd.DataFrame, horizon: int, threshold: float = 0.0) -> pd.Series:
    """Individuelles Eigenprofil eines Wertes (kausale historische Profitrate).

    Anteil der bisherigen Tage, an denen der Titel über den Horizont profitabel
    war – nur aus bereits bekannten (vergangenen) Ergebnissen gebildet. So lernt
    das Modell die *individuelle* Tendenz jedes Wertes, ohne in die Zukunft zu
    schauen.
    """
    cl = prices["Close"]
    n = len(cl)
    out = np.full(n, np.nan)
    fwd = (cl.shift(-horizon) / cl - 1)
    tgt = np.where(fwd.isna().values, np.nan, (fwd.values > threshold).astype(float))
    s = 0.0
    c = 0
    for t in range(n):
        j = t - horizon                      # Ergebnis von Tag j ist an Tag j+h bekannt
        if j >= 0 and not np.isnan(tgt[j]):
            s += tgt[j]
            c += 1
        if c > 0:
            out[t] = s / c
    return pd.Series(out, index=prices.index)


def pattern_memory(prices: pd.DataFrame, horizon: int) -> pd.Series:
    """Kausales Muster-Gedächtnis je Handelstag.

    Der aktuelle Zustand wird grob klassifiziert (Momentum-Vorzeichen × RSI-Zone).
    Der Wert ist die **durchschnittliche Folge-Rendite**, die in der Vergangenheit
    auf *denselben* Zustand folgte – es werden nur bereits bekannte (vergangene)
    Ergebnisse genutzt (kein Blick in die Zukunft). So erkennt das Modell
    wiederkehrende Kursmuster und nutzt deren historischen Ausgang.
    """
    from collections import defaultdict

    cl = prices["Close"]
    n = len(cl)
    out = np.full(n, np.nan)
    if n < 40:
        return pd.Series(out, index=prices.index)

    ret5 = cl.pct_change(5).values
    delta = cl.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = (100 - 100 / (1 + rs)).values
    fwd = (cl.shift(-horizon) / cl - 1).values

    def state_of(i: int):
        if np.isnan(ret5[i]) or np.isnan(rsi[i]):
            return None
        mom = 1 if ret5[i] > 0 else (-1 if ret5[i] < 0 else 0)
        zone = 0 if rsi[i] < 30 else (2 if rsi[i] > 70 else 1)
        return mom * 10 + zone

    mem_sum: dict = defaultdict(float)
    mem_cnt: dict = defaultdict(int)
    for t in range(n):
        j = t - horizon                      # Ergebnis von Tag j ist an Tag j+h bekannt
        if j >= 0 and not np.isnan(fwd[j]):
            sj = state_of(j)
            if sj is not None:
                mem_sum[sj] += fwd[j]
                mem_cnt[sj] += 1
        st = state_of(t)
        if st is not None and mem_cnt[st] > 0:
            out[t] = mem_sum[st] / mem_cnt[st]
    return pd.Series(out, index=prices.index)


def analog_memory(
    prices: pd.DataFrame, horizon: int, window: int = 8, k: int = 20,
    max_hist: int = 756,
) -> pd.Series:
    """Analog-Mustererkennung: ähnliche historische Kursverläufe finden & merken.

    Für jeden Tag wird die *Form* der jüngsten ``window`` Tagesrenditen
    (z-normiert, also skalenunabhängig) mit allen früheren Fenstern verglichen.
    Aus den ``k`` ähnlichsten **vergangenen** Mustern wird die durchschnittliche
    Folge-Rendite gebildet – „als der Kurs zuletzt so aussah, ging es danach im
    Schnitt um X%". Kausal: nur Fenster, deren Ausgang bereits bekannt ist.
    """
    close = prices["Close"]
    n = len(close)
    out = np.full(n, np.nan)
    if n < window + horizon + 30:
        return pd.Series(out, index=prices.index)

    r = close.pct_change().values
    fwd = (close.shift(-horizon) / close - 1).values

    # Z-normierte Form-Fenster je Endindex i
    W = np.full((n, window), np.nan, dtype=float)
    for i in range(window - 1, n):
        seg = r[i - window + 1:i + 1]
        if np.isnan(seg).any():
            continue
        sd = seg.std()
        W[i] = (seg - seg.mean()) / sd if sd > 1e-9 else 0.0

    for t in range(window - 1, n):
        if np.isnan(W[t]).any():
            continue
        hi = t - horizon                     # nur Muster mit bekanntem Ausgang
        lo = max(window - 1, hi - max_hist + 1)
        if hi < lo:
            continue
        cand = W[lo:hi + 1]
        cf = fwd[lo:hi + 1]
        valid = ~np.isnan(cand).any(axis=1) & ~np.isnan(cf)
        if valid.sum() < 5:
            continue
        cw = cand[valid]
        cfv = cf[valid]
        dist = ((cw - W[t]) ** 2).sum(axis=1)
        kk = min(k, len(dist))
        idx = np.argpartition(dist, kk - 1)[:kk]
        out[t] = float(np.mean(cfv[idx]))
    return pd.Series(out, index=prices.index)


def universe(cfg: Config) -> list[str]:
    """Alle beobachteten Werte über die Anlageklassen hinweg (dedupliziert):
    Aktien + ETFs + Krypto."""
    seen: list[str] = []
    for t in list(cfg.tickers) + list(cfg.etfs) + list(getattr(cfg, "crypto", [])):
        if t not in seen:
            seen.append(t)
    return seen


def asset_class(cfg: Config, ticker: str) -> str:
    """Anlageklasse eines Tickers: 'Krypto', 'ETF' oder 'Aktie'."""
    if ticker in getattr(cfg, "crypto", []):
        return "Krypto"
    if ticker in cfg.etfs:
        return "ETF"
    return "Aktie"


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
    # Markt-Regime: breiter Trend (Abstand zur SMA50) + Volatilitätslage je Datum
    df["mkt_trend"] = g["dist_sma50"].transform("mean") if "dist_sma50" in df else 0.0
    df["mkt_vol"] = g["vol_20d"].transform("mean") if "vol_20d" in df else 0.0
    df[["mkt_trend", "mkt_vol"]] = df[["mkt_trend", "mkt_vol"]].fillna(0.0)
    return df


# --------------------------------------------------------------------------- #
@dataclass
class TickerAnalysis:
    ticker: str
    last_price: float
    profit_probability: float
    sentiment_mean: float
    news_count: int
    asset_class: str = "Aktie"
    rsi_14: float = 50.0
    momentum_5d: float = 0.0
    price_vs_high_20: float = 1.0
    volatility: float = 0.02
    expected_return: float | None = None
    horizon_probs: dict = field(default_factory=dict)
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
    for ticker in universe(cfg):
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
        # Ziel je zusätzlichem Horizont (kurz-/mittelfristige Einschätzung)
        for h in cfg.horizons:
            fr = prices["Close"].shift(-h) / prices["Close"] - 1.0
            feat[f"target_h{h}"] = (fr > cfg.profit_threshold).astype("float")
        # Muster-Gedächtnis (wiederkehrende Kurs-Zustände) + Analog-Muster
        feat["pattern_mem"] = pattern_memory(prices, cfg.horizon_days).values
        feat["analog_mem"] = analog_memory(prices, cfg.horizon_days).values
        feat["ticker_bias"] = ticker_bias(prices, cfg.horizon_days, cfg.profit_threshold).values
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
    # Muster-Gedächtnis + Analog-Muster für den aktuellen (letzten) Tag
    pm = pattern_memory(prices, cfg.horizon_days).iloc[-1]
    row["pattern_mem"] = float(pm) if pm == pm else 0.0  # NaN -> 0
    am = analog_memory(prices, cfg.horizon_days).iloc[-1]
    row["analog_mem"] = float(am) if am == am else 0.0
    tb = ticker_bias(prices, cfg.horizon_days, cfg.profit_threshold).iloc[-1]
    row["ticker_bias"] = float(tb) if tb == tb else 0.5
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
    mkt_trend = float(np.mean([r.get("dist_sma50", 0.0) for r in rows]))
    mkt_vol = float(np.mean([r.get("vol_20d", 0.0) for r in rows]))
    for i, r in enumerate(rows):
        r["mkt_ret_5d"] = mkt5
        r["rel_strength_20d"] = float(r.get("ret_20d", 0.0) - mkt20)
        r["xs_mom_rank"] = float(mom.iloc[i]) if n > 1 else 0.5
        r["xs_sent_rank"] = float(sent.iloc[i]) if n > 1 else 0.5
        r["mkt_trend"] = mkt_trend
        r["mkt_vol"] = mkt_vol


def snapshot_live(cfg: Config) -> int:
    """Schreibt den aktuellen Zustand aller Ticker in den Feature-Store.

    Diese Snapshots haben zunächst kein Label (``target`` = NaN). Sobald der
    Horizont verstrichen ist, füllt ``label_pending`` die echte Rendite ein.
    """
    store = FeatureStore(cfg.store_dir)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows: list[dict] = []
    for ticker in universe(cfg):
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
    # Von 'evolve' gewählter Champion hat Vorrang (Selbst-Weiterentwicklung)
    preferred = ModelStore(cfg.model_dir).load_preferred_model()
    if preferred:
        return preferred, None
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
    # Klassifizierer je zusätzlichem Horizont (kurz-/mittelfristige Sicht)
    for h in cfg.horizons:
        predictor.fit_horizon(h, data, f"target_h{h}")

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
    cfg: Config, retrain_if_missing: bool = True, universe_override: list[str] | None = None
) -> list[TickerAnalysis]:
    """Live-Analyse: berechnet je Ticker die Profitabilitäts-Wahrscheinlichkeit.

    Das Ranking zeigt, *wer* wahrscheinlich profitabel wird und *wohin*
    (relativ) das Kapital tendiert. ``universe_override`` ersetzt optional die zu
    bewertenden Ticker; Standard ist das gesamte Universum (Aktien+ETFs+Krypto).
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
    tickers = universe_override if universe_override is not None else universe(cfg)
    for ticker in tickers:
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
        horizon_probs = predictor.predict_horizons(X)

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
            expected_return=expected_return,
        )
        results.append(
            TickerAnalysis(
                ticker=ticker,
                last_price=last_price,
                profit_probability=proba,
                asset_class=asset_class(cfg, ticker),
                sentiment_mean=row.get("sent_mean", 0.0),
                news_count=int(row.get("news_count", 0)),
                rsi_14=row.get("rsi_14", 50.0),
                momentum_5d=row.get("ret_5d", 0.0),
                price_vs_high_20=row.get("price_vs_high_20", 1.0),
                volatility=float(row.get("vol_20d", 0.02) or 0.02),
                expected_return=expected_return,
                horizon_probs=horizon_probs,
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
