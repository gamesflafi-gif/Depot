"""Datenquellen-Abstraktion: schaltet zwischen Live- und Demo-Daten um.

Gesteuert über ``data_source`` in config.yaml:
    * ``live`` – echte Daten via yfinance + RSS-News (benötigt Netzwerkzugriff
      auf finance.yahoo.com / news.google.com; ggf. Allowlist anpassen)
    * ``demo`` – synthetische, offline erzeugte Daten

So bleibt die restliche Pipeline unabhängig von der konkreten Quelle.
"""
from __future__ import annotations

import pandas as pd

from stockai.config import Config
from stockai.data import demo, news as news_mod, prices as prices_mod
from stockai.data.news import NewsItem


def get_prices(cfg: Config, ticker: str) -> pd.DataFrame:
    if cfg.raw.get("data_source", "live") == "demo":
        return demo.demo_prices(ticker, cfg.history_period, cfg.history_interval)
    return prices_mod.fetch_prices(ticker, cfg.history_period, cfg.history_interval)


def get_prices_window(cfg: Config, ticker: str, period: str) -> pd.DataFrame:
    """Kurse über einen abweichenden Zeitraum (z.B. fürs Labeling)."""
    if cfg.raw.get("data_source", "live") == "demo":
        return demo.demo_prices(ticker, period, cfg.history_interval)
    return prices_mod.fetch_prices(ticker, period, cfg.history_interval)


def get_news(cfg: Config, ticker: str) -> list[NewsItem]:
    if cfg.raw.get("data_source", "live") == "demo":
        return demo.demo_news(ticker, cfg.news_max_per_ticker)
    return news_mod.fetch_news(ticker, limit=cfg.news_max_per_ticker)
