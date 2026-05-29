"""Datenquellen-Abstraktion: schaltet zwischen Live- und Demo-Daten um.

Gesteuert über ``data_source`` in config.yaml:
    * ``live`` – echte Daten (Kurse direkt herunterladen, News via RSS)
    * ``demo`` – synthetische, offline erzeugte Daten

Im Live-Modus sind die Kurse **anbieter-unabhängig**: gesteuert über
``price_source`` (yfinance | stooq | auto). ``auto`` (Standard) lädt zuerst
über yfinance und fällt bei Bedarf automatisch auf den direkten Stooq-CSV-
Download zurück – so hängt nichts an einer einzelnen Quelle.

So bleibt die restliche Pipeline unabhängig von der konkreten Quelle.
"""
from __future__ import annotations

import pandas as pd

from stockai.config import Config
from stockai.data import demo, news as news_mod, prices as prices_mod, stooq
from stockai.data.news import NewsItem


def _fetch_live_prices(cfg: Config, ticker: str, period: str) -> pd.DataFrame:
    """Lädt echte Kurse gemäß ``price_source`` mit automatischem Fallback."""
    source = str(cfg.raw.get("price_source", "auto")).lower()
    interval = cfg.history_interval

    def yf():
        return prices_mod.fetch_prices(ticker, period, interval)

    def sq():
        return stooq.fetch_prices_stooq(ticker, period, interval)

    if source == "stooq":
        df = sq()
        return df if not df.empty else yf()
    if source == "yfinance":
        df = yf()
        return df if not df.empty else sq()
    # auto: erst yfinance, dann direkter Stooq-Download
    df = yf()
    return df if not df.empty else sq()


def get_prices(cfg: Config, ticker: str) -> pd.DataFrame:
    if cfg.raw.get("data_source", "live") == "demo":
        return demo.demo_prices(ticker, cfg.history_period, cfg.history_interval)
    return _fetch_live_prices(cfg, ticker, cfg.history_period)


def get_prices_window(cfg: Config, ticker: str, period: str) -> pd.DataFrame:
    """Kurse über einen abweichenden Zeitraum (z.B. fürs Labeling)."""
    if cfg.raw.get("data_source", "live") == "demo":
        return demo.demo_prices(ticker, period, cfg.history_interval)
    return _fetch_live_prices(cfg, ticker, period)


def get_news(cfg: Config, ticker: str) -> list[NewsItem]:
    if cfg.raw.get("data_source", "live") == "demo":
        return demo.demo_news(ticker, cfg.news_max_per_ticker)
    return news_mod.fetch_news(ticker, limit=cfg.news_max_per_ticker)


def get_sentiment_history(cfg: Config, ticker: str) -> pd.DataFrame | None:
    """Tagesgenaue historische Sentiment-Features (für das Training).

    Demo: an das Trend-Regime gekoppelte Reihe. Live: nicht verfügbar (None) –
    kostenlose, tagesgenaue Alt-News über Jahre gibt es nicht; das News-Signal
    wird dann im Betrieb über die Snapshot-Schleife dazugelernt.
    """
    if cfg.raw.get("data_source", "live") == "demo":
        return demo.demo_sentiment_history(ticker)
    return None


def get_sentiment_features(cfg: Config, ticker: str, news: list[NewsItem] | None = None) -> dict:
    """Aktuelle Sentiment-Features – konsistent zur Trainingsquelle."""
    if cfg.raw.get("data_source", "live") == "demo":
        return demo.demo_sentiment_today(ticker)
    from stockai.features.sentiment import aggregate_sentiment

    news = news if news is not None else get_news(cfg, ticker)
    return aggregate_sentiment(news).features
