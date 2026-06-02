"""Interaktiver Telegram-Bot: auf Befehle vom Handy antworten.

Per Long-Polling werden Nachrichten abgeholt und beantwortet – ganz ohne
Zusatz-Abhängigkeiten (nur urllib). Aus Sicherheitsgründen reagiert der Bot nur
auf die in ``STOCKAI_TELEGRAM_CHAT_ID`` hinterlegte Chat-ID (deine eigene).

Befehle:
    /menu          – persönlicher Überblick (Depot, Alerts, Sparplan)
    /analyse SYM   – Einzelanalyse eines Wertes (z.B. /analyse NVDA)
    /live SYM      – aktueller Live-Kurs
    /briefing      – aktuelles Briefing mit Moves
    /top [n]       – Top-n Chancen und Risiken
    /alerts        – starke Live-Bewegungen
    /sparplan [€]  – Sparplan-Vorschlag (Standard 100€)
    /track         – Live-Track-Record: traf die KI richtig?
    /weakspots     – Schwachstellen-Analyse: wo liegt die KI daneben?
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
    "🤖 Aktien-KI Bot · deine Befehle\n"
    "\n"
    "🏠 /menu   dein persönlicher Überblick (Depot, Alerts, Sparplan)\n"
    "\n"
    "📊 Analyse\n"
    "  /analyse SYM   Einzelanalyse (z.B. /analyse NVDA)\n"
    "  /live SYM      aktueller Live-Kurs\n"
    "  /briefing      aktuelles Briefing mit Bewegungen\n"
    "  /top [n]       Top-n Chancen & Risiken\n"
    "  /alerts        starke Live-Bewegungen\n"
    "  /whales        auffälliges Volumen (Smart-Money-Spur)\n"
    "  /watch         eigene Trigger (z.B. /watch add BTC-USD < 50000)\n"
    "\n"
    "💶 Geld\n"
    "  /sparplan [€]  Sparplan-Vorschlag (Standard 100€)\n"
    "  /depot         dein Depot: G/V + KI-Bewertung\n"
    "  /depot add NVDA 10 850   Position eintragen\n"
    "\n"
    "🔍 Selbstkontrolle der KI\n"
    "  /track         traf die KI live richtig?\n"
    "  /weakspots     wo liegt die KI daneben?\n"
    "  /health        wird die KI besser oder schlechter?\n"
    "\n"
    "  /help          diese Übersicht\n"
    "\n"
    "ℹ️ Keine Anlageberatung."
)


def _personal_overview(cfg: Config, user: str | None) -> str:
    """Persönlicher, schneller Überblick je Nutzer (ohne schwere Analyse)."""
    from stockai import holdings as hd, watch as wt, users
    prefs = users.load_prefs(cfg, user)
    name = prefs.get("name")
    nh = len(hd.load_holdings(cfg, user))
    nw = len(wt.load_watches(cfg, user))
    monthly = prefs.get("monthly")

    lines = [f"👋 Hallo {name}!" if name else "👋 Hallo!", "", "Dein Überblick:"]
    if nh:
        lines.append(f"💼 Depot: {nh} Position(en)  →  /depot")
    else:
        lines.append("💼 Depot: noch leer  →  /depot add NVDA 10 850")
    if nw:
        lines.append(f"🔔 Alerts: {nw} aktiv  →  /watch")
    else:
        lines.append("🔔 Alerts: keine  →  /watch add BTC-USD < 50000")
    if monthly:
        lines.append(f"💶 Sparplan: {float(monthly):g}€/Monat  →  /sparplan")
    else:
        lines.append("💶 Sparplan: noch keiner  →  /sparplan 200")
    lines.append("")
    lines.append("Tipp einen Button unten oder /help für alle Befehle.")
    return "\n".join(lines)


def _welcome(cfg: Config, user: str | None) -> str:
    """Freundliche Begrüßung beim /start – persönlich und mit Überblick."""
    return ("🤖 Willkommen bei deiner Aktien-KI!\n"
            "Ich analysiere Aktien, ETFs & Krypto, lerne laufend dazu und melde "
            "dir Chancen, Whale-Volumen und Depot-Warnungen.\n\n"
            + _personal_overview(cfg, user)
            + "\n\nℹ️ Keine Anlageberatung.")


def handle_command(cfg: Config, text: str, user: str | None = None,
                   cached: bool = False) -> str:
    """Wertet einen Befehlstext aus und liefert die Antwort (Text).

    ``user`` (Telegram-Chat-ID) trennt persönliche Daten – Depot, Sparplan und
    Alerts gehören jeweils nur dem anfragenden Nutzer. ``cached`` bedient teure
    Markt-Analysen kurzzeitig aus dem Speicher (schnellere Antworten, weniger
    Last bei mehreren Nutzern).
    """
    parts = text.strip().split()
    if not parts:
        return _HELP
    cmd = parts[0].lower().lstrip("/").split("@")[0]
    arg = parts[1] if len(parts) > 1 else None

    if cmd == "help":
        return _HELP
    if cmd == "start":
        return _welcome(cfg, user)
    if cmd in ("menu", "menü", "uebersicht", "übersicht"):
        return _personal_overview(cfg, user)

    if cmd == "briefing":
        from stockai import briefing as bf
        return bf.render_briefing(bf.build_briefing(cfg, use_cache=cached))

    if cmd == "alerts":
        from stockai import alerts as al
        res = al.check_alerts(cfg)
        return al.render_alerts(res) or "Aktuell keine starken Bewegungen."

    if cmd in ("whales", "whale", "volumen"):
        from stockai import whale as wh
        return wh.render_whales(wh.scan_whales(cfg))

    if cmd in ("track", "trackrecord", "bilanz"):
        from stockai import track as tk
        return tk.render_track_record(tk.build_track_record(cfg))

    if cmd in ("health", "check", "selbstcheck"):
        from stockai import health as hl
        return hl.render_health(hl.assess_health(cfg, record=False))

    if cmd in ("watch", "alert", "trigger"):
        from stockai import watch as wt
        sub = (parts[1].lower() if len(parts) > 1 else "")
        if sub == "add":
            w = wt.parse_spec(parts[2:])
            if not w:
                return ("Nutzung: /watch add TICKER [rsi|vol|pct] <|> WERT\n"
                        "z.B. /watch add BTC-USD < 50000\n"
                        "      /watch add NVDA rsi < 30\n"
                        "      /watch add BTC-USD vol > 2")
            wt.add_watch(cfg, w, user=user)
            return (f"✔ Alert gesetzt: {w.ticker} {wt._LABEL[w.metric]} {w.op} "
                    f"{w.value:g}\nAlle Alerts: /watch")
        if sub in ("remove", "del", "delete"):
            try:
                idx = int(parts[2])
            except (IndexError, ValueError):
                return "Nutzung: /watch remove NUMMER (siehe /watch)"
            return ("✔ entfernt." if wt.remove_watch(cfg, idx, user=user)
                    else "Nummer nicht gefunden.")
        if sub == "clear":
            wt.save_watches(cfg, [], user=user)
            return "✔ Alle Alerts gelöscht."
        return wt.render_watches(cfg, user=user)

    if cmd in ("depot", "portfolio", "wallet"):
        from stockai import holdings as hd
        sub = (parts[1].lower() if len(parts) > 1 else "")
        if sub == "add":
            try:
                tkr, qty, price = parts[2], float(parts[3]), float(parts[4])
            except (IndexError, ValueError):
                return "Nutzung: /depot add TICKER STÜCK KAUFKURS\nz.B. /depot add NVDA 10 850"
            hd.add_holding(cfg, tkr, qty, price, user=user)
            return f"✔ {tkr.upper()} hinzugefügt ({qty:g} @ {price:.2f}).\nSchau mit /depot"
        if sub in ("remove", "del", "delete"):
            if len(parts) < 3:
                return "Nutzung: /depot remove TICKER"
            ok = hd.remove_holding(cfg, parts[2], user=user)
            return (f"✔ {parts[2].upper()} entfernt." if ok else "Position nicht gefunden.")
        if sub == "clear":
            hd.save_holdings(cfg, [], user=user)
            return "✔ Depot geleert."
        return hd.render_depot(hd.build_depot_report(cfg, user=user, use_cache=cached))

    if cmd in ("weakspots", "schwachstellen", "schwaechen"):
        from stockai import weakspots as ws
        return ws.render_weakspots(ws.analyze_weakspots(cfg))

    if cmd == "top":
        from stockai import briefing as bf
        n = int(arg) if arg and arg.isdigit() else 5
        top, bottom = bf.build_top(cfg, n=n, use_cache=cached)
        return bf.render_top(top, bottom, n)

    if cmd == "sparplan":
        from stockai.savings_plan import build_savings_plan
        from stockai import notify, users
        if arg:                                   # neuer Betrag -> pro Nutzer merken
            try:
                amount = float(arg.replace(",", "."))
                users.set_pref(cfg, user, "monthly", amount)
            except ValueError:
                amount = float(users.load_prefs(cfg, user).get("monthly", 100.0))
        else:
            amount = float(users.load_prefs(cfg, user).get("monthly", 100.0))
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
        res = pipeline.analyze(cfg, universe_override=[sym], use_cache=cached)
        if not res:
            return f"Keine Daten für {sym} gefunden."
        a = res[0]
        er = f"{a.expected_return:+.1%}" if a.expected_return is not None else "–"
        hz = " · ".join(f"{h}T {p:.0%}" for h, p in sorted(a.horizon_probs.items()))
        q = get_quote(sym)
        price_line = (f"🔴 Live: {q.price:.2f}  ({q.change_pct:+.2f}% heute · {q.source})\n"
                      if q else f"Kurs: {a.last_price:.2f}\n")
        return (f"📊 {a.ticker} ({a.asset_class}) · {a.action}\n"
                + price_line
                + f"Gewinn-Chance: {a.profit_probability:.0%}  ·  erwartet: {er}\n"
                + (f"Horizonte: {hz}\n" if hz else "")
                + f"RSI: {a.rsi_14:.0f}  ·  News-Stimmung: {a.sentiment_mean:+.2f}\n"
                f"Timing: {a.timing}\n\nℹ️ Keine Anlageberatung.")

    return "Unbekannter Befehl. /help zeigt die Übersicht."


# --------------------------------------------------------------------------- #
_LOCK_HANDLE = None   # offen halten, solange der Prozess lebt


def _acquire_lock(cfg: Config) -> bool:
    """Exklusive Datei-Sperre, damit nur EIN Bot gleichzeitig pollt.

    Liefert True, wenn die Sperre erlangt wurde. Auf Systemen ohne ``fcntl``
    (z.B. Windows) wird keine Sperre genutzt (immer True).
    """
    global _LOCK_HANDLE
    try:
        import fcntl
        from pathlib import Path
        path = Path(cfg.store_dir) / "bot.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(path, "w")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        _LOCK_HANDLE = fh                     # Referenz halten -> Sperre bleibt aktiv
        return True
    except OSError:
        return False                          # bereits gesperrt
    except Exception:
        return True                           # kein fcntl -> ohne Sperre weiter


def _api(token: str, method: str, params: dict, timeout: int = 35):
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _send(token: str, chat_id: str, text: str, keyboard: str | None = None) -> None:
    try:
        params = {"chat_id": chat_id, "text": text[:_TG_LIMIT],
                  "disable_web_page_preview": "true"}
        if keyboard:
            params["reply_markup"] = keyboard
        _api(token, "sendMessage", params, timeout=15)
    except Exception as exc:
        log.warning("Senden fehlgeschlagen: %s", exc)


def _remember_name(cfg: Config, chat_id: str, frm: dict) -> None:
    """Merkt sich den Telegram-Vornamen pro Nutzer (für persönliche Begrüßung)."""
    name = (frm or {}).get("first_name")
    if not name:
        return
    try:
        from stockai import users
        if users.load_prefs(cfg, chat_id).get("name") != name:
            users.set_pref(cfg, chat_id, "name", name)
    except Exception:
        pass


def _typing(token: str, chat_id: str) -> None:
    """Zeigt im Chat „tippt …", damit der Bot bei längeren Befehlen nicht
    eingefroren wirkt."""
    try:
        _api(token, "sendChatAction", {"chat_id": chat_id, "action": "typing"}, timeout=8)
    except Exception:
        pass


def _reply(cfg: Config, token: str, chat_id: str, text: str) -> None:
    """Befehl auswerten und Antwort mit antippbarem Menü senden."""
    from stockai.notify import main_menu_markup
    _typing(token, chat_id)                            # sofortiges Lebenszeichen
    try:
        # Chat-ID = persönlicher Kontext; cached=True für schnelle Wiederholungen
        answer = handle_command(cfg, text, user=chat_id, cached=True)
    except Exception as exc:
        answer = f"Fehler bei der Verarbeitung: {exc}"
    _send(token, chat_id, answer, keyboard=main_menu_markup())


def run_bot(cfg: Config, poll_timeout: int = 30) -> None:
    """Startet die Long-Polling-Schleife (läuft dauerhaft).

    ``STOCKAI_TELEGRAM_CHAT_ID`` darf mehrere erlaubte IDs enthalten (Allowlist,
    komma-/leerzeichengetrennt). Nur diese dürfen den Bot nutzen; ist keine ID
    gesetzt, antwortet der Bot allen (nicht empfohlen).
    """
    from stockai.notify import main_menu_markup, parse_chat_ids
    token = os.environ.get(_TOKEN_ENV)
    allowed = parse_chat_ids(os.environ.get(_CHAT_ENV))
    if not token:
        raise RuntimeError(f"{_TOKEN_ENV} nicht gesetzt (siehe .env / doctor).")

    # Single-Instance-Sperre: verhindert, dass zwei Bot-Prozesse gleichzeitig
    # pollen und jede Nachricht doppelt beantworten.
    if not _acquire_lock(cfg):
        log.warning("Es läuft bereits eine Bot-Instanz – diese beende ich.")
        print("Es läuft bereits ein Bot (Lock aktiv) – doppelte Instanz beendet.")
        return

    log.info("Telegram-Bot gestartet (Polling). Erlaubte Chats: %d", len(allowed))

    def _authorized(cid: str) -> bool:
        return (not allowed) or (cid in allowed)

    # Beim Start eventuell aufgelaufene Alt-Updates verwerfen (kein Nachzügler-Spam)
    try:
        _api(token, "getUpdates", {"offset": -1, "timeout": 0}, timeout=15)
    except Exception:
        pass

    for cid in allowed:                      # persönliche Startmeldung an alle Erlaubten
        from stockai import users
        nm = users.load_prefs(cfg, cid).get("name")
        hi = f"🤖 Bot wieder online{', ' + nm if nm else ''}! Tippe 🏠 Mein Menü."
        _send(token, cid, hi, keyboard=main_menu_markup())

    offset = None
    while True:
        try:
            params = {"timeout": poll_timeout}
            if offset is not None:
                params["offset"] = offset
            data = _api(token, "getUpdates", params, timeout=poll_timeout + 10)
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1

                # 1) Button-Klick (Inline-Tastatur)
                cb = upd.get("callback_query")
                if cb:
                    cb_chat = str(cb.get("message", {}).get("chat", {}).get("id", ""))
                    try:    # Lade-Spinner am Button stoppen
                        _api(token, "answerCallbackQuery",
                             {"callback_query_id": cb.get("id", "")}, timeout=10)
                    except Exception:
                        pass
                    if not _authorized(cb_chat):
                        continue
                    _reply(cfg, token, cb_chat, cb.get("data", "/help"))
                    continue

                # 2) normale Textnachricht
                msg = upd.get("message") or upd.get("edited_message") or {}
                text = msg.get("text")
                chat_id = str(msg.get("chat", {}).get("id", ""))
                if not text:
                    continue
                if not _authorized(chat_id):
                    _send(token, chat_id,
                          "Nicht autorisiert. Deine Chat-ID: " + chat_id +
                          "\nGib sie dem Betreiber, damit er dich freischaltet.")
                    continue
                _remember_name(cfg, chat_id, msg.get("from", {}))
                _reply(cfg, token, chat_id, text)
        except Exception as exc:
            log.warning("Bot-Schleife: %s", exc)
            time.sleep(5)
