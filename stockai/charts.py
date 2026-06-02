"""Charts fürs Handy: Kursverlauf mit Signalen als Bild (PNG).

Erzeugt einen sauberen Zwei-Panel-Chart (Kurs + gleitende Durchschnitte mit
SMA-Kreuzungs-Signalen oben, RSI unten) und beschriftet ihn mit dem aktuellen
KI-Urteil (Aktion + Conviction). Reines Bild – nutzt das nicht-interaktive
``Agg``-Backend, läuft also headless auf dem Server.
"""
from __future__ import annotations

import io

from stockai.config import Config


def price_chart(cfg: Config, ticker: str, days: int = 140) -> tuple[bytes, str] | None:
    """Erzeugt einen PNG-Chart + Bildunterschrift für ``ticker``.

    Returns ``(png_bytes, caption)`` oder ``None``, wenn keine Daten vorliegen.
    """
    import matplotlib
    matplotlib.use("Agg")                       # headless, kein Display nötig
    import matplotlib.pyplot as plt
    import numpy as np

    from stockai.data import provider
    from stockai import pipeline

    ticker = ticker.upper()
    try:
        prices = provider.get_prices(cfg, ticker)
    except Exception:
        return None
    if prices is None or prices.empty or len(prices) < 30:
        return None

    df = prices.tail(days).copy()
    close = df["Close"]
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()

    # SMA-Kreuzungen als illustrative Kauf-/Verkaufssignale
    cross = np.sign(sma20 - sma50)
    flips = cross.diff()
    buys = df.index[(flips > 0)]
    sells = df.index[(flips < 0)]

    # RSI(14)
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))

    # aktuelles KI-Urteil (Titel ohne Emoji – matplotlib-Schrift; Caption mit Emoji)
    title_verdict, verdict = "", ""
    try:
        res = pipeline.analyze(cfg, universe_override=[ticker], use_cache=True)
        if res:
            a = res[0]
            title_verdict = (f"{a.action}  ·  Conviction {a.conviction:.0f}  ·  "
                             f"Chance {a.profit_probability:.0%}")
            verdict = (f"{a.action} · 🎯 {a.conviction:.0f} · "
                       f"Chance {a.profit_probability:.0%}")
    except Exception:
        pass

    plt.style.use("dark_background")
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(8, 5.2), sharex=True,
        gridspec_kw={"height_ratios": [3, 1]})
    fig.subplots_adjust(hspace=0.08)

    ax1.plot(df.index, close, color="#4da3ff", lw=1.6, label="Kurs")
    ax1.plot(df.index, sma20, color="#ffcc55", lw=1.0, label="SMA20")
    ax1.plot(df.index, sma50, color="#ff6f91", lw=1.0, label="SMA50")
    ax1.scatter(buys, close.reindex(buys), marker="^", color="#3ddc84",
                s=90, zorder=5, label="Kaufsignal (SMA)")
    ax1.scatter(sells, close.reindex(sells), marker="v", color="#ff5252",
                s=90, zorder=5, label="Verkaufssignal (SMA)")
    ax1.set_title(f"{ticker}   {title_verdict}", fontsize=12, loc="left")
    ax1.legend(loc="upper left", fontsize=7, ncol=5, framealpha=0.2)
    ax1.grid(alpha=0.15)
    ax1.tick_params(labelsize=8)

    ax2.plot(df.index, rsi, color="#c792ea", lw=1.2)
    ax2.axhline(70, color="#ff5252", lw=0.7, ls="--", alpha=0.6)
    ax2.axhline(30, color="#3ddc84", lw=0.7, ls="--", alpha=0.6)
    ax2.set_ylim(0, 100)
    ax2.set_ylabel("RSI", fontsize=8)
    ax2.grid(alpha=0.15)
    ax2.tick_params(labelsize=8)

    fig.autofmt_xdate(rotation=0, ha="center")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)

    last = float(close.iloc[-1])
    caption = (f"📈 {ticker} – {last:.2f}\n"
               + (verdict + "\n" if verdict else "")
               + "▲ Kaufsignal / ▼ Verkaufssignal = SMA20×SMA50-Kreuzung.\n"
               "ℹ️ Keine Anlageberatung.")
    return buf.getvalue(), caption
