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
import urllib.parse
import urllib.request
from datetime import datetime, timezone

_WEBHOOK_ENV = "STOCKAI_WEBHOOK_URL"
_TG_TOKEN_ENV = "STOCKAI_TELEGRAM_TOKEN"
_TG_CHAT_ENV = "STOCKAI_TELEGRAM_CHAT_ID"
_TG_LIMIT = 4000  # Telegram-Nachrichtenlimit (~4096), mit Puffer


def render_savings_plan(plan) -> str:
    """Erzeugt einen kompakten Markdown-Report eines Sparplans."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# 📈 Sparplan-Update ({ts})",
        f"Monatlicher Sparbetrag: **{plan.monthly_amount:.2f}€** "
        f"(Core/ETF-Anteil {plan.core_share:.0%})",
        "",
        "## Core (ETFs)",
    ]
    for p in plan.core_positions:
        lines.append(f"- **{p.instrument}**: {p.monthly:.2f}€/Monat ({p.weight:.0%})")
    if not plan.core_positions:
        lines.append("- (keine)")
    lines += ["", "## Satelliten (Aktien)"]
    for p in plan.satellite_positions:
        lines.append(
            f"- **{p.instrument}**: {p.monthly:.2f}€/Monat ({p.weight:.0%}) "
            f"– {p.action}, P(Profit) {p.probability:.0%}"
        )
    if not plan.satellite_positions:
        lines.append("- (aktuell keine – defensiv im Core)")
    if plan.notes:
        lines += ["", "## Hinweise"]
        lines += [f"- {n}" for n in plan.notes]
    lines += ["", "_Demo/Analyse – keine Anlageberatung._"]
    return "\n".join(lines)


def send_telegram(text: str, token: str | None = None, chat_id: str | None = None) -> bool:
    """Sendet eine Nachricht an einen Telegram-Chat. Liefert Erfolg.

    Einrichtung: bei @BotFather einen Bot anlegen -> Token; die eigene Chat-ID
    z.B. über @userinfobot ermitteln. Ohne Token/Chat-ID (oder Netz) passiert
    nichts (kein Fehler).
    """
    token = token or os.environ.get(_TG_TOKEN_ENV)
    chat_id = chat_id or os.environ.get(_TG_CHAT_ENV)
    if not token or not chat_id:
        return False
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode(
            {"chat_id": chat_id, "text": text[:_TG_LIMIT], "disable_web_page_preview": "true"}
        ).encode("utf-8")
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def notify(text: str) -> tuple[bool, str]:
    """Sendet über den konfigurierten Kanal. Returns (Erfolg, Kanalname)."""
    if telegram_configured():
        return send_telegram(text), "Telegram"
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
    return bool(os.environ.get(_TG_TOKEN_ENV) and os.environ.get(_TG_CHAT_ENV))
