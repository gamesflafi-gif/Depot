"""Benachrichtigung: Report als Markdown + Versand per Telegram oder Webhook.

Echte „Live-Benachrichtigung aufs Handy" erfordert einen dauerhaft laufenden
Dienst (Server/Cron) und einen Kanal. Dieses Modul liefert die Bausteine:

    * einen lesbaren Report,
    * **Telegram** (empfohlen fürs Handy) über ``STOCKAI_TELEGRAM_TOKEN`` und
      ``STOCKAI_TELEGRAM_CHAT_ID``,
    * alternativ einen generischen **Webhook** (Discord/Slack/Mattermost) über
      ``STOCKAI_WEBHOOK_URL``.

``notify(text)`` wählt automatisch den konfigurierten Kanal.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone

_WEBHOOK_ENV = "STOCKAI_WEBHOOK_URL"
_TG_TOKEN_ENV = "STOCKAI_TELEGRAM_TOKEN"
_TG_CHAT_ENV = "STOCKAI_TELEGRAM_CHAT_ID"
_TG_LIMIT = 4000  # Telegram-Nachrichtenlimit (~4096), mit Puffer


def parse_chat_ids(raw: str | None) -> list[str]:
    """Zerlegt eine Chat-ID-Liste (komma-/leerzeichengetrennt) in einzelne IDs.

    So kann ``STOCKAI_TELEGRAM_CHAT_ID`` mehrere erlaubte Empfänger enthalten
    (du + Freunde) – z.B. ``"123456,789012"``.
    """
    return [c for c in re.split(r"[,\s]+", (raw or "").strip()) if c]


def main_menu_markup() -> str:
    """Antippbares Hauptmenü (Telegram-Inline-Tastatur) – kein Tippen nötig."""
    kb = {"inline_keyboard": [
        [{"text": "📊 Briefing", "callback_data": "/briefing"},
         {"text": "🚀 Top 5", "callback_data": "/top 5"}],
        [{"text": "💼 Depot", "callback_data": "/depot"},
         {"text": "💶 Sparplan", "callback_data": "/sparplan"}],
        [{"text": "🔔 Alerts", "callback_data": "/alerts"},
         {"text": "📒 Track", "callback_data": "/track"}],
        [{"text": "🔍 Schwächen", "callback_data": "/weakspots"},
         {"text": "🩺 Selbstcheck", "callback_data": "/health"}],
        [{"text": "❓ Hilfe", "callback_data": "/help"}],
    ]}
    return json.dumps(kb)


def render_savings_plan(plan) -> str:
    """Erzeugt einen kompakten, sauber lesbaren Sparplan-Report (Telegram-tauglich)."""
    lines = [
        "📈 Sparplan-Update",
        f"Monatlich: {plan.monthly_amount:.2f}€  ·  Core/ETF-Anteil {plan.core_share:.0%}",
        "",
        "🧱 CORE (ETFs)",
    ]
    for p in plan.core_positions:
        lines.append(f"  • {p.instrument}: {p.monthly:.2f}€/Monat ({p.weight:.0%})")
    if not plan.core_positions:
        lines.append("  • (keine)")
    lines += ["", "🛰️ SATELLITEN (Aktien)"]
    for p in plan.satellite_positions:
        lines.append(
            f"  • {p.instrument}: {p.monthly:.2f}€/Monat ({p.weight:.0%}) "
            f"– {p.action}, Chance {p.probability:.0%}"
        )
    if not plan.satellite_positions:
        lines.append("  • (aktuell keine – defensiv im Core)")
    if plan.crypto_positions:
        lines += ["", "🪙 KRYPTO (Beimischung, höheres Risiko)"]
        for p in plan.crypto_positions:
            lines.append(
                f"  • {p.instrument}: {p.monthly:.2f}€/Monat ({p.weight:.0%}) "
                f"– Chance {p.probability:.0%}"
            )
    if plan.notes:
        lines += ["", "ℹ️ Hinweise"]
        lines += [f"  • {n}" for n in plan.notes]
    lines += ["", "ℹ️ Keine Anlageberatung."]
    return "\n".join(lines)


def send_telegram(text: str, token: str | None = None, chat_id: str | None = None,
                  reply_markup: str | None = None) -> bool:
    """Sendet eine Nachricht an einen oder mehrere Telegram-Chats. Liefert Erfolg.

    Einrichtung: bei @BotFather einen Bot anlegen -> Token; die eigene Chat-ID
    z.B. über @userinfobot ermitteln. ``STOCKAI_TELEGRAM_CHAT_ID`` darf mehrere
    IDs (komma-/leerzeichengetrennt) enthalten – dann geht die Nachricht an alle.
    Ohne Token/Chat-ID (oder Netz) passiert nichts (kein Fehler). ``reply_markup``
    hängt eine Inline-Tastatur an.
    """
    token = token or os.environ.get(_TG_TOKEN_ENV)
    ids = parse_chat_ids(chat_id or os.environ.get(_TG_CHAT_ENV))
    if not token or not ids:
        return False
    ok_any = False
    for cid in ids:
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            params = {"chat_id": cid, "text": text[:_TG_LIMIT],
                      "disable_web_page_preview": "true"}
            if reply_markup:
                params["reply_markup"] = reply_markup
            data = urllib.parse.urlencode(params).encode("utf-8")
            req = urllib.request.Request(url, data=data)
            with urllib.request.urlopen(req, timeout=10) as resp:
                ok_any = ok_any or (200 <= resp.status < 300)
        except Exception:
            continue
    return ok_any


def notify(text: str) -> tuple[bool, str]:
    """Sendet über den konfigurierten Kanal. Returns (Erfolg, Kanalname).

    Bei Telegram werden die antippbaren Menü-Buttons automatisch angehängt.
    """
    if telegram_configured():
        return send_telegram(text, reply_markup=main_menu_markup()), "Telegram"
    if webhook_configured():
        return send_webhook(text), "Webhook"
    return False, "kein Kanal konfiguriert"


def send_webhook(text: str, url: str | None = None) -> bool:
    """Sendet den Text an einen Webhook (JSON ``{"text": …}``). Liefert Erfolg.

    Funktioniert mit Slack/Discord/Mattermost und vielen Bots, die ein
    ``text``-Feld erwarten. Ohne URL/Netzwerk passiert nichts (kein Fehler).
    """
    url = url or os.environ.get(_WEBHOOK_ENV)
    if not url:
        return False
    try:
        data = json.dumps({"text": text}).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def webhook_configured() -> bool:
    return bool(os.environ.get(_WEBHOOK_ENV))


def telegram_configured() -> bool:
    return bool(os.environ.get(_TG_TOKEN_ENV) and parse_chat_ids(os.environ.get(_TG_CHAT_ENV)))
