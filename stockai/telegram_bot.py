"""Interaktiver Telegram-Bot: auf Befehle vom Handy antworten.

Per Long-Polling werden Nachrichten abgeholt und beantwortet – ganz ohne
Zusatz-Abhängigkeiten (nur urllib). Aus Sicherheitsgründen reagiert der Bot nur
auf die in ``STOCKAI_TELEGRAM_CHAT_ID`` hinterlegte Chat-ID (deine eigene).

Befehle:
    /analyse SYM   – Einzelanalyse eines Wertes (z.B. /analyse NVDA)
    /briefing      – aktuelles Briefing mit Moves
    /top [n]       – Top-n Chancen und Risiken
    /sparplan [€]  – Sparplan-Vorschlag (Standard 100€)
    /help          – diese Übersicht
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request

from stockai.config import Config

log = logging.getLogger(__name__)

_TOKEN_ENV = "STOCKAI_TELEGRAM_TOKEN"
_CHAT_ENV = "STOCKAI_TELEGRAM_CHAT_ID"
_TG_LIMIT = 3900

_HELP = (
    "🤖 Aktien-KI Bot – Befehle:\n"
    "/analyse SYM – Einzelanalyse (z.B. /analyse NVDA)\n"
    "/live SYM – aktueller Live-Kurs (Krypto frei, Aktien via Finnhub-Key)\n"
    "/briefing – aktuelles Briefing mit Moves\n"
    "/top [n] – Top-n Chancen & Risiken\n"
    "/sparplan [€] – Sparplan-Vorschlag\n"
    "/help – diese Übersicht\n\n"
    "_Keine Anlageberatung._"
)


def handle_command(cfg: Config, text: str) -> str:
    """Wertet einen Befehlstext aus und liefert die Antwort (Text)."""
    parts = text.strip().split()
    if not parts:
        return _HELP
    cmd = parts[0].lower().lstrip("/").split("@")[0]
    arg = parts[1] if len(parts) > 1 else None

    if cmd in ("start", "help"):
        return _HELP

    if cmd == "briefing":
        from stockai import briefing as bf
        return bf.render_briefing(bf.build_briefing(cfg))

    if cmd == "top":
        from stockai import briefing as bf
        n = int(arg) if arg and arg.isdigit() else 5
        top, bottom = bf.build_top(cfg, n=n)
        return bf.render_top(top, bottom, n)

    if cmd == "sparplan":
        from stockai.savings_plan import build_savings_plan
        from stockai import notify
        try:
            amount = float(arg) if arg else 100.0
        except ValueError:
            amount = 100.0
        return notify.render_savings_plan(build_savings_plan(cfg, monthly_amount=amount))

    if cmd == "live":
        from stockai.data.live import get_quote
        if not arg:
            return "Bitte ein Symbol angeben, z.B. /live BTC-USD"
        q = get_quote(arg.upper())
        if not q:
            return (f"Kein Live-Kurs für {arg.upper()} (Krypto ist frei; für "
                    f"Aktien einen Finnhub-Key in STOCKAI_FINNHUB_KEY setzen).")
        return f"🔴 LIVE {q.ticker}: {q.price:.2f} ({q.change_pct:+.2f}% heute) – {q.source}"

    if cmd in ("analyse", "analyze", "aktie"):
        if not arg:
            return "Bitte ein Symbol angeben, z.B. /analyse NVDA"
        from stockai import pipeline
        from stockai.data.live import get_quote
        sym = arg.upper()
        res = pipeline.analyze(cfg, universe_override=[sym])
        if not res:
            return f"Keine Daten für {sym} gefunden."
        a = res[0]
        er = f"{a.expected_return:+.1%}" if a.expected_return is not None else "–"
        hz = " · ".join(f"{h}T {p:.0%}" for h, p in sorted(a.horizon_probs.items()))
        q = get_quote(sym)
        price_line = (f"🔴 LIVE: {q.price:.2f} ({q.change_pct:+.2f}% heute, {q.source})\n"
                      if q else f"Kurs: {a.last_price:.2f}\n")
        return (f"📊 {a.ticker} [{a.asset_class}] – {a.action}\n"
                + price_line
                + f"P(Profit): {a.profit_probability:.0%} | E[Rendite]: {er}\n"
                + (f"Horizonte: {hz}\n" if hz else "")
                + f"RSI: {a.rsi_14:.0f} | Sentiment: {a.sentiment_mean:+.2f}\n"
                f"Timing: {a.timing}\n\n_Keine Anlageberatung._")

    return "Unbekannter Befehl. /help zeigt die Übersicht."


# --------------------------------------------------------------------------- #
def _api(token: str, method: str, params: dict, timeout: int = 35):
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _send(token: str, chat_id: str, text: str) -> None:
    try:
        _api(token, "sendMessage",
             {"chat_id": chat_id, "text": text[:_TG_LIMIT],
              "disable_web_page_preview": "true"}, timeout=15)
    except Exception as exc:
        log.warning("Senden fehlgeschlagen: %s", exc)


def run_bot(cfg: Config, poll_timeout: int = 30) -> None:
    """Startet die Long-Polling-Schleife (läuft dauerhaft)."""
    token = os.environ.get(_TOKEN_ENV)
    owner = os.environ.get(_CHAT_ENV)
    if not token:
        raise RuntimeError(f"{_TOKEN_ENV} nicht gesetzt (siehe .env / doctor).")
    log.info("Telegram-Bot gestartet (Polling).")
    if owner:
        _send(token, owner, "🤖 Aktien-KI Bot ist online. /help für Befehle.")

    offset = None
    while True:
        try:
            params = {"timeout": poll_timeout}
            if offset is not None:
                params["offset"] = offset
            data = _api(token, "getUpdates", params, timeout=poll_timeout + 10)
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or upd.get("edited_message") or {}
                text = msg.get("text")
                chat_id = str(msg.get("chat", {}).get("id", ""))
                if not text:
                    continue
                if owner and chat_id != str(owner):
                    _send(token, chat_id, "Nicht autorisiert.")
                    continue
                try:
                    reply = handle_command(cfg, text)
                except Exception as exc:
                    reply = f"Fehler bei der Verarbeitung: {exc}"
                _send(token, chat_id, reply)
        except Exception as exc:
            log.warning("Bot-Schleife: %s", exc)
            time.sleep(5)
