"""Walk-Forward-Strategie-Backtest mit P&L, Equity-Kurve und Risikokennzahlen.

Simuliert, als hätte man der KI über die Zeit tatsächlich gefolgt:

    1. Zu jedem Rebalancing-Termin wird das Modell ausschließlich auf der bis
       dahin bekannten Historie trainiert (keine Zukunftsinformation).
    2. Es wählt die aussichtsreichsten Aktien (P(Profit) über Schwelle, max.
       ``top_k``) und gewichtet sie gleich.
    3. Die real eingetretene Folge-Rendite über den Horizont wird verbucht.

Verglichen wird gegen eine Buy-&-Hold-Benchmark (Gleichgewichtung aller Ticker).
Ausgegeben werden Gesamtrendite, Sharpe-Ratio und maximaler Drawdown – plus eine
Equity-Kurve als Chart.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from stockai.config import Config
from stockai.data import provider
from stockai.features.sentiment import SENTIMENT_FEATURES
from stockai.features.technical import add_technical_features
from stockai.model.predictor import Predictor

log = logging.getLogger(__name__)


@dataclass
class StrategyResult:
    dates: list[str]
    strategy_equity: list[float]
    benchmark_equity: list[float]
    metrics: dict[str, float]
    benchmark_metrics: dict[str, float]
    n_rebalances: int
    trades: list[dict] = field(default_factory=list)
    initial_capital: float = 1.0
    years: float = 0.0

    @property
    def final_value(self) -> float:
        return self.initial_capital * (self.strategy_equity[-1] if self.strategy_equity else 1.0)

    @property
    def benchmark_value(self) -> float:
        return self.initial_capital * (self.benchmark_equity[-1] if self.benchmark_equity else 1.0)

    @property
    def cagr(self) -> float:
        """Durchschnittliche jährliche Wachstumsrate der Strategie."""
        if self.years <= 0 or not self.strategy_equity:
            return 0.0
        return self.strategy_equity[-1] ** (1.0 / self.years) - 1.0


# --------------------------------------------------------------------------- #
def _build_panel(cfg: Config, period: str | None = None) -> pd.DataFrame:
    """Long-Panel: je (Datum, Ticker) Features (inkl. News) + reale Folge-Rendite.

    ``period`` überschreibt optional den Kurszeitraum (z.B. "10y" für eine
    lange Simulation), ohne die Trainingskonfiguration zu ändern.
    """
    from stockai.pipeline import (
        FEATURE_COLUMNS, add_market_features, analog_memory, pattern_memory,
        ticker_bias, universe,
    )

    horizon = cfg.horizon_days
    rows: list[pd.DataFrame] = []
    for ticker in universe(cfg):
        prices = (
            provider.get_prices_window(cfg, ticker, period)
            if period else provider.get_prices(cfg, ticker)
        )
        if prices.empty or len(prices) < 80:
            continue
        feat = add_technical_features(prices)
        feat["fwd_ret"] = prices["Close"].shift(-horizon) / prices["Close"] - 1.0
        feat["target"] = (feat["fwd_ret"] > cfg.profit_threshold).astype("float")
        feat["pattern_mem"] = pattern_memory(prices, horizon).values
        feat["analog_mem"] = analog_memory(prices, horizon).values
        feat["ticker_bias"] = ticker_bias(prices, horizon, cfg.profit_threshold).values
        # News-Sentiment je Tag (sofern verfügbar) -> News im Backtest nutzen
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
        feat["date"] = feat.index
        rows.append(feat)
    if not rows:
        return pd.DataFrame()
    panel = pd.concat(rows, ignore_index=True)
    panel = add_market_features(panel)
    panel[FEATURE_COLUMNS] = panel[FEATURE_COLUMNS].replace([np.inf, -np.inf], np.nan)
    return panel.dropna(subset=FEATURE_COLUMNS + ["fwd_ret"])


def _annualized(period_returns: np.ndarray, periods_per_year: float) -> dict[str, float]:
    if len(period_returns) == 0:
        return {"total_return": 0.0, "sharpe": 0.0, "win_rate": 0.0}
    equity = np.cumprod(1 + period_returns)
    total = float(equity[-1] - 1.0)
    mean, std = float(np.mean(period_returns)), float(np.std(period_returns))
    sharpe = (mean / std * np.sqrt(periods_per_year)) if std > 1e-9 else 0.0
    return {
        "total_return": total,
        "sharpe": float(sharpe),
        "win_rate": float(np.mean(period_returns > 0)),
    }


def _max_drawdown(equity: list[float]) -> float:
    peak, mdd = -np.inf, 0.0
    for v in equity:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1.0)
    return float(mdd)


# --------------------------------------------------------------------------- #
def run_strategy_backtest(
    cfg: Config,
    prob_threshold: float = 0.55,
    top_k: int = 3,
    train_frac: float = 0.4,
    period: str | None = None,
    initial_capital: float = 1.0,
    retrain_every: int = 1,
    cost_bps: float = 10.0,
    regime_filter: bool = False,
) -> StrategyResult:
    """Führt den Walk-Forward-Strategie-Backtest aus.

    ``retrain_every`` steuert, wie oft das Modell neu trainiert wird (1 = bei
    jedem Rebalancing). Größere Werte beschleunigen lange Simulationen deutlich
    und entsprechen dem realistischen Vorgehen, nicht ständig neu zu trainieren.

    ``cost_bps`` sind die Transaktionskosten je Einheit Umschichtung in
    Basispunkten (10 = 0,1 %). So ist die Strategie-Rendite **netto** nach
    Gebühren/Spread – ehrlicher, gerade bei häufigem Rebalancing.
    """
    panel = _build_panel(cfg, period=period)
    if panel.empty:
        raise RuntimeError("Keine Daten für den Strategie-Backtest verfügbar.")

    horizon = cfg.horizon_days
    from stockai.pipeline import FEATURE_COLUMNS, resolve_model_type

    # Modelltyp einmal auflösen (auto -> konkret). Für lange Reihen genügt zur
    # Auswahl ein jüngerer Ausschnitt -> schnell.
    sel_panel = panel.tail(4000) if len(panel) > 4000 else panel
    model_type, _ = resolve_model_type(cfg, sel_panel, feature_names=FEATURE_COLUMNS)

    all_dates = np.sort(panel["date"].unique())
    start_idx = int(len(all_dates) * train_frac)
    # Nicht überlappende Rebalancing-Termine im Abstand des Horizonts
    rebal_dates = all_dates[start_idx::horizon]

    strat_returns: list[float] = []
    bench_returns: list[float] = []
    used_dates: list[str] = []
    trades: list[dict] = []
    predictor = None
    steps_since_fit = 0
    prev_weights: dict[str, float] = {}
    cost_rate = cost_bps / 10000.0
    total_cost = 0.0

    for t in rebal_dates:
        train = panel[panel["date"] <= (t - np.timedelta64(horizon, "D"))]
        today = panel[panel["date"] == t]
        if len(train) < 50 or today.empty:
            continue
        if train["target"].nunique() < 2:
            continue

        # Nur periodisch neu trainieren (oder beim ersten Mal)
        if predictor is None or steps_since_fit >= retrain_every:
            predictor = Predictor(
                feature_names=FEATURE_COLUMNS,
                model_type=model_type,
                random_state=int(cfg.model.get("random_state", 42)),
            )
            predictor.estimator.fit(
                train[FEATURE_COLUMNS].values, train["target"].astype(int).values
            )
            predictor.is_fitted = True
            steps_since_fit = 0
        steps_since_fit += 1

        proba = predictor.predict_proba(today)
        today = today.assign(proba=proba)
        picks = today[today["proba"] >= prob_threshold].nlargest(top_k, "proba")

        strat_ret = float(picks["fwd_ret"].mean()) if not picks.empty else 0.0
        bench_ret = float(today["fwd_ret"].mean())

        # Transaktionskosten über die Umschichtung (Turnover) gegenüber der
        # vorigen Positionierung -> Netto-Rendite.
        names = picks["ticker"].tolist()
        w = 1.0 / len(names) if names else 0.0
        new_weights = {t: w for t in names}
        turnover = 0.5 * sum(
            abs(new_weights.get(s, 0.0) - prev_weights.get(s, 0.0))
            for s in set(new_weights) | set(prev_weights)
        )
        cost = cost_rate * turnover
        total_cost += cost
        prev_weights = new_weights
        strat_ret -= cost

        # Regime-Bremse: in Abschwungphasen (breiter Markt unter SMA50) wird die
        # Position verkleinert (Rest = Cash) -> geringerer Drawdown.
        if regime_filter and "mkt_trend" in today.columns:
            regime = float(today["mkt_trend"].mean())
            exposure = min(1.0, max(0.3, 1.0 + 14.0 * regime))
            strat_ret *= exposure

        strat_returns.append(strat_ret)
        bench_returns.append(bench_ret)
        used_dates.append(pd.Timestamp(t).strftime("%Y-%m-%d"))
        trades.append(
            {
                "date": pd.Timestamp(t).strftime("%Y-%m-%d"),
                "picks": picks["ticker"].tolist(),
                "strategy_return": round(strat_ret, 4),
                "benchmark_return": round(bench_ret, 4),
            }
        )

    if not strat_returns:
        raise RuntimeError("Zu wenige Rebalancing-Termine für eine Auswertung.")

    strat_arr = np.array(strat_returns)
    bench_arr = np.array(bench_returns)
    strat_equity = np.cumprod(1 + strat_arr).tolist()
    bench_equity = np.cumprod(1 + bench_arr).tolist()
    ppy = 252.0 / horizon

    metrics = _annualized(strat_arr, ppy)
    metrics["max_drawdown"] = _max_drawdown(strat_equity)
    bench_metrics = _annualized(bench_arr, ppy)
    bench_metrics["max_drawdown"] = _max_drawdown(bench_equity)

    # Zeitspanne der Simulation in Jahren
    d0 = pd.Timestamp(used_dates[0])
    d1 = pd.Timestamp(used_dates[-1])
    years = max((d1 - d0).days / 365.25, len(strat_returns) * horizon / 365.25)

    return StrategyResult(
        dates=used_dates,
        strategy_equity=strat_equity,
        benchmark_equity=bench_equity,
        metrics=metrics,
        benchmark_metrics=bench_metrics,
        n_rebalances=len(strat_returns),
        trades=trades,
        initial_capital=initial_capital,
        years=years,
    )


# --------------------------------------------------------------------------- #
def plot_equity_curve(result: StrategyResult, out_path: str) -> str:
    """Speichert die Equity-Kurve (Strategie vs. Benchmark) als PNG."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    x = pd.to_datetime(result.dates)
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(x, result.strategy_equity, label="KI-Strategie", linewidth=2)
    ax.plot(x, result.benchmark_equity, label="Buy & Hold (Benchmark)",
            linewidth=2, linestyle="--")
    ax.axhline(1.0, color="gray", linewidth=0.8, alpha=0.6)
    ax.set_title("Strategie-Backtest: Kapitalentwicklung (Startwert = 1.0)")
    ax.set_xlabel("Datum")
    ax.set_ylabel("Kapital (Vielfaches des Einsatzes)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path
