"""Benachrichtigung: Sparplan-/Analyse-Report als Markdown + optionaler Webhook.

Echte „Live-Benachrichtigung aufs Handy" erfordert einen dauerhaft laufenden
Dienst (Server/Cron) und einen Kanal. Dieses Modul liefert beides als Baustein:
ein lesbarer Report und ein optionaler Webhook-Versand (Telegram/Discord/Slack
o.ä.) an die URL aus der Umgebungsvariable ``STOCKAI_WEBHOOK_URL``.
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone

_WEBHOOK_ENV = "STOCKAI_WEBHOOK_URL"


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
