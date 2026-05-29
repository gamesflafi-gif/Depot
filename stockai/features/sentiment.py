"""News-Sentiment mit VADER (lexikonbasiert, kein Modell-Download nötig).

VADER ist auf kurze, schlagzeilenartige Texte abgestimmt und liefert einen
Compound-Score in [-1, 1]. Wir aggregieren die Scores aller Headlines eines
Tickers zu kompakten Features.
"""
from __future__ import annotations

from dataclasses import dataclass

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from stockai.data.news import NewsItem

# Aggregierte Sentiment-Feature-Spalten.
SENTIMENT_FEATURES: list[str] = [
    "news_count",
    "sent_mean",
    "sent_pos_ratio",
    "sent_neg_ratio",
    "sent_max",
    "sent_min",
    "sent_trend",   # Veränderung der Stimmung (dreht das Sentiment?)
    "news_vol_z",   # ungewöhnlich viel Berichterstattung (z-Score)
    "kw_signal",    # Schlagwort-Signal aus Headlines (Earnings/Upgrade/Lawsuit …)
]

# Schlagworte, die typischerweise Kurssprünge bzw. -einbrüche begleiten.
_KW_POS = (
    "beat", "beats", "surge", "soar", "record", "upgrade", "rally", "growth",
    "partnership", "profit", "wins", "approval", "raises", "outperform", "buy",
)
_KW_NEG = (
    "miss", "slide", "lawsuit", "probe", "fraud", "cut", "cuts", "plunge",
    "downgrade", "recall", "warning", "loss", "investigation", "halt", "sell",
)

_analyzer = SentimentIntensityAnalyzer()


def keyword_signal(news: list[NewsItem]) -> float:
    """Schlagwort-Signal in [-1, 1]: (positive − negative Treffer) / Anzahl."""
    if not news:
        return 0.0
    pos = neg = 0
    for item in news:
        text = item.text.lower()
        pos += sum(1 for k in _KW_POS if k in text)
        neg += sum(1 for k in _KW_NEG if k in text)
    total = pos + neg
    if total == 0:
        return 0.0
    return (pos - neg) / total


@dataclass
class SentimentResult:
    features: dict[str, float]
    scored_items: list[tuple[NewsItem, float]]


def score_text(text: str) -> float:
    """Compound-Sentiment eines einzelnen Textes in [-1, 1]."""
    if not text or not text.strip():
        return 0.0
    return _analyzer.polarity_scores(text)["compound"]


def aggregate_sentiment(news: list[NewsItem]) -> SentimentResult:
    """Berechnet aggregierte Sentiment-Features über eine Liste von News."""
    scored = [(item, score_text(item.text)) for item in news]
    scores = [s for _, s in scored]

    if not scores:
        features = {name: 0.0 for name in SENTIMENT_FEATURES}
        return SentimentResult(features=features, scored_items=scored)

    n = len(scores)
    pos = sum(1 for s in scores if s > 0.05)
    neg = sum(1 for s in scores if s < -0.05)
    features = {
        "news_count": float(n),
        "sent_mean": sum(scores) / n,
        "sent_pos_ratio": pos / n,
        "sent_neg_ratio": neg / n,
        "sent_max": max(scores),
        "sent_min": min(scores),
        # Trend & Volumen-Spike brauchen Historie -> live neutral (0.0);
        # im Betrieb lernt die Snapshot-Schleife sie über die Zeit.
        "sent_trend": 0.0,
        "news_vol_z": 0.0,
        "kw_signal": keyword_signal(news),
    }
    return SentimentResult(features=features, scored_items=scored)
