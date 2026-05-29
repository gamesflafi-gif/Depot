"""Streamlit-Dashboard für die Aktien-KI.

Start:
    streamlit run dashboard/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

# Projekt-Root in den Pfad legen, damit 'stockai' importierbar ist
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stockai.config import load_config  # noqa: E402
from stockai import pipeline  # noqa: E402
from stockai.model.store import ModelStore  # noqa: E402

st.set_page_config(page_title="Aktien-KI", page_icon="📈", layout="wide")

cfg = load_config()

st.title("📈 Lernende Aktien-KI")
st.caption(
    "Analysiert Kurse + News, lernt kontinuierlich dazu und gibt eigenständige "
    "Empfehlungen: Welche Aktien könnten boomen – und wann verkaufen?"
)

# --- Sidebar: Steuerung --------------------------------------------------- #
with st.sidebar:
    st.header("Steuerung")
    st.write(f"**Beobachtete Ticker:** {', '.join(cfg.tickers)}")
    st.write(f"**Horizont:** {cfg.horizon_days} Handelstage")

    if st.button("🔁 Modell neu trainieren"):
        with st.spinner("Trainiere …"):
            res = pipeline.train(cfg)
        st.success(f"Trainiert. Accuracy={res.metrics.get('accuracy', 0):.3f}, "
                   f"AUC={res.metrics.get('roc_auc', float('nan')):.3f}")

    if st.button("🧠 Lernzyklus (snapshot+label+train)"):
        with st.spinner("Lerne dazu …"):
            labeled = pipeline.label_pending(cfg)
            snap = pipeline.snapshot_live(cfg)
            res = pipeline.train(cfg)
        st.success(f"{labeled} gelabelt, {snap} neue Snapshots, neu trainiert.")

_ACTION_COLORS = {
    "BOOM": "#0a8f3c",
    "KAUFEN": "#3cb371",
    "HALTEN": "#b8b8b8",
    "VERKAUFEN": "#d97706",
    "MEIDEN": "#c0392b",
}


@st.cache_data(ttl=600, show_spinner=False)
def _run_analysis():
    results = pipeline.analyze(cfg)
    return [r.__dict__ for r in results]


# --- Hauptbereich --------------------------------------------------------- #
tab_overview, tab_detail, tab_portfolio, tab_strategy, tab_learning = st.tabs(
    ["🎯 Empfehlungen", "🔍 Detail & News", "💼 Portfolio",
     "📉 Strategie-Backtest", "🧠 Lernfortschritt"]
)

with tab_overview:
    if st.button("Analyse starten / aktualisieren", type="primary"):
        _run_analysis.clear()
    try:
        results = _run_analysis()
    except Exception as exc:
        st.error(f"Analyse fehlgeschlagen: {exc}")
        results = []

    if results:
        df = pd.DataFrame(results)
        show = df[[
            "ticker", "last_price", "profit_probability", "action",
            "rsi_14", "sentiment_mean", "news_count",
        ]].copy()
        show.columns = [
            "Ticker", "Kurs", "P(Profit)", "Aktion", "RSI", "Sentiment", "News"
        ]
        st.dataframe(
            show.style.format({
                "Kurs": "{:.2f}", "P(Profit)": "{:.1%}",
                "RSI": "{:.0f}", "Sentiment": "{:+.2f}",
            }),
            use_container_width=True, hide_index=True,
        )

        fig = px.bar(
            df, x="ticker", y="profit_probability", color="action",
            color_discrete_map=_ACTION_COLORS,
            title="Profitabilitäts-Wahrscheinlichkeit je Aktie (wohin tendiert das Geld?)",
            labels={"profit_probability": "P(Profit)", "ticker": "Aktie"},
        )
        fig.add_hline(y=0.5, line_dash="dash", line_color="gray")
        st.plotly_chart(fig, use_container_width=True)

with tab_detail:
    try:
        results = _run_analysis()
    except Exception:
        results = []
    for r in results:
        with st.expander(
            f"{r['ticker']} — {r['action']} (P={r['profit_probability']:.0%}, "
            f"Konfidenz {r['confidence']:.0%})"
        ):
            c1, c2, c3 = st.columns(3)
            c1.metric("Kurs", f"{r['last_price']:.2f}")
            c2.metric("RSI", f"{r['rsi_14']:.0f}")
            c3.metric("Sentiment", f"{r['sentiment_mean']:+.2f}")
            st.write(f"**Timing:** {r['timing']}")
            st.write("**Begründung:**")
            for reason in r["reasons"]:
                st.write(f"- {reason}")
            if r["top_headlines"]:
                st.write("**Schlagzeilen:**")
                for h in r["top_headlines"]:
                    st.markdown(
                        f"- [{h['sentiment']:+.2f}] [{h['title']}]({h['link']}) "
                        f"_( {h['source']} )_"
                    )

with tab_portfolio:
    from types import SimpleNamespace
    from stockai.portfolio import build_portfolio

    st.write("**Allokationsvorschlag** – wohin wie viel Kapital fließen sollte.")
    capital = st.number_input("Verfügbares Kapital", min_value=100.0,
                              value=10_000.0, step=500.0)
    max_pos = st.slider("Max. Anteil je Position", 0.1, 1.0, 0.25, 0.05)
    try:
        results = _run_analysis()
    except Exception:
        results = []
    if results:
        pf = build_portfolio(
            [SimpleNamespace(**r) for r in results],
            capital=capital, max_position_pct=max_pos,
        )
        if pf.allocations:
            alloc_df = pd.DataFrame([{
                "Ticker": a.ticker, "Aktion": a.action, "Anteil": a.weight,
                "Betrag": a.amount, "Stück": a.shares, "Kurs": a.last_price,
            } for a in pf.allocations])
            st.dataframe(
                alloc_df.style.format({
                    "Anteil": "{:.1%}", "Betrag": "{:,.2f}",
                    "Stück": "{:.3f}", "Kurs": "{:.2f}",
                }),
                use_container_width=True, hide_index=True,
            )
            c1, c2 = st.columns(2)
            c1.metric("Investiert", f"{pf.invested:,.2f}",
                      f"{pf.invested / pf.capital:.0%}")
            c2.metric("Cash", f"{pf.cash:,.2f}", f"{pf.cash / pf.capital:.0%}")
            pie = px.pie(alloc_df, names="Ticker", values="Betrag",
                         title="Kapitalverteilung")
            st.plotly_chart(pie, use_container_width=True)
        else:
            st.info("Aktuell keine Kaufkandidaten – Empfehlung: abwarten.")
        if pf.sells:
            st.warning(f"Verkaufen/Meiden: {', '.join(pf.sells)}")

with tab_strategy:
    st.write("**Walk-Forward-Backtest** – wäre man der KI gefolgt, vs. Buy & Hold.")
    c1, c2 = st.columns(2)
    thr = c1.slider("Kauf-Schwelle P(Profit)", 0.5, 0.8, 0.55, 0.01)
    topk = c2.slider("Max. Positionen je Rebalancing", 1, len(cfg.tickers), 3)
    if st.button("Backtest starten", type="primary"):
        from stockai import strategy as _strat
        with st.spinner("Simuliere (Training an jedem Rebalancing-Termin) …"):
            try:
                res = _strat.run_strategy_backtest(cfg, prob_threshold=thr, top_k=topk)
            except Exception as exc:
                st.error(f"Backtest fehlgeschlagen: {exc}")
                res = None
        if res is not None:
            eq = pd.DataFrame({
                "Datum": pd.to_datetime(res.dates),
                "KI-Strategie": res.strategy_equity,
                "Buy & Hold": res.benchmark_equity,
            }).melt("Datum", var_name="Serie", value_name="Kapital")
            fig = px.line(eq, x="Datum", y="Kapital", color="Serie",
                          title="Kapitalentwicklung (Start = 1.0)")
            st.plotly_chart(fig, use_container_width=True)
            m, b = res.metrics, res.benchmark_metrics
            kpi = pd.DataFrame({
                "Kennzahl": ["Gesamtrendite", "Sharpe-Ratio", "Max. Drawdown", "Trefferquote"],
                "KI-Strategie": [f"{m['total_return']:.1%}", f"{m['sharpe']:.2f}",
                                 f"{m['max_drawdown']:.1%}", f"{m['win_rate']:.1%}"],
                "Buy & Hold": [f"{b['total_return']:.1%}", f"{b['sharpe']:.2f}",
                               f"{b['max_drawdown']:.1%}", f"{b['win_rate']:.1%}"],
            })
            st.dataframe(kpi, use_container_width=True, hide_index=True)
            st.caption(f"{res.n_rebalances} Rebalancings. Demo-Daten dienen nur "
                       "der Veranschaulichung – keine reale Performance.")

with tab_learning:
    history = ModelStore(cfg.model_dir).load_history()
    if not history:
        st.info("Noch keine Lernhistorie. Bitte zuerst trainieren.")
    else:
        rows = []
        for i, h in enumerate(history, 1):
            m = h.get("metrics", {})
            rows.append({
                "Lauf": i,
                "Zeitpunkt": h.get("timestamp", "")[:19],
                "Samples": h.get("n_samples", 0),
                "Accuracy": m.get("accuracy"),
                "ROC-AUC": m.get("roc_auc"),
                "F1": m.get("f1"),
            })
        hist_df = pd.DataFrame(rows)
        st.dataframe(hist_df, use_container_width=True, hide_index=True)
        melt = hist_df.melt(
            id_vars=["Lauf"], value_vars=["Accuracy", "ROC-AUC", "F1"],
            var_name="Metrik", value_name="Wert",
        ).dropna()
        if not melt.empty:
            fig = px.line(
                melt, x="Lauf", y="Wert", color="Metrik", markers=True,
                title="Lernfortschritt: Güte über die Trainingsläufe",
            )
            st.plotly_chart(fig, use_container_width=True)
        st.caption(
            "Mit jedem Lernzyklus wachsen die Daten und das Modell wird neu "
            "bewertet – so wird sichtbar, wie die KI präziser wird."
        )
