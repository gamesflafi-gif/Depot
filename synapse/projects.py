"""Kollaborative Forschung: Projekte (Forschungsbereiche) + Beiträge.

Nutzer legen einen Forschungsbereich an und laden Ergebnisse/Zwischenstände hoch;
andere bauen darauf auf. Jeder Beitrag bekommt eine **Vertrauens-Stufe**
(geprüft per DOI / Preprint-Link / community-unbestätigt), damit nichts
verwechselt wird. Ungeprüftes wird nie mit der geprüften Literatur vermischt.
Siehe SYNAPSE_COLLAB_DESIGN.md (alle Eventualitäten + Absicherung).
"""
from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from synapse.config import Config
from synapse.storage import SynapseStore

KINDS = {"finding", "dataset", "progress", "question"}
TRUST = {"verified", "preprint", "community"}
# anerkannte externe Repos -> Stufe „preprint/daten"
_REPO_HINTS = ("zenodo.org", "osf.io", "arxiv.org", "figshare.com",
               "github.com", "doi.org", "ncbi.nlm.nih.gov", "biorxiv.org",
               "medrxiv.org", "dryad")
# sensible Themen -> deutlicher Warnhinweis (keine Beratung!)
_SENSITIVE = ("krebs", "cancer", "tumor", "onko", "covid", "impf", "vaccine",
              "suizid", "suicide", "medikament", "drug dose", "therapie", "therapy",
              "diagnose", "diagnosis", "patient")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (title or "projekt").lower()).strip("-")
    return (s[:40] or "projekt") + "-" + secrets.token_hex(3)


@dataclass
class SubmitOutcome:
    ok: bool
    message: str = ""
    data: dict | None = None


# --------------------------------------------------------------------------- #
def create_project(cfg: Config, title: str, area: str = "", description: str = "",
                   owner_name: str = "", owner_orcid: str = "",
                   license: str = "CC-BY 4.0") -> SubmitOutcome:
    title = (title or "").strip()
    if len(title) < 4:
        return SubmitOutcome(False, "Bitte einen aussagekräftigen Titel (min. 4 Zeichen).")
    pid = _slug(title)
    token = secrets.token_urlsafe(12)            # geheim, nur einmal sichtbar
    with SynapseStore(cfg) as store:
        store.con.execute(
            "INSERT INTO projects VALUES (?,?,?,?,?,?,?,?,?,?)",
            [pid, title, area.strip()[:120], description.strip()[:4000],
             (owner_name or "anonym").strip()[:120], owner_orcid.strip()[:40],
             _hash(token), license.strip()[:60], "active", _now()])
    return SubmitOutcome(True, "Projekt angelegt. Bewahre den Owner-Token sicher auf "
                         "(zum Kuratieren – wird nur jetzt angezeigt).",
                         {"id": pid, "title": title, "owner_token": token})


def _trust_level(cfg: Config, evidence_doi: str, link: str) -> str:
    if evidence_doi.strip():
        # DOI live prüfen (offline/Sample: überspringen -> nicht „verified")
        if cfg.source_mode != "sample":
            try:
                from synapse.sources import openalex
                if openalex.fetch_by_doi(cfg, evidence_doi):
                    return "verified"
            except Exception:  # noqa: BLE001
                pass
    low = link.lower()
    if link.strip() and any(h in low for h in _REPO_HINTS):
        return "preprint"
    return "community"


def add_contribution(cfg: Config, project_id: str, kind: str, title: str,
                     body: str = "", link: str = "", evidence_doi: str = "",
                     contributor_name: str = "", contributor_orcid: str = "") -> SubmitOutcome:
    kind = kind if kind in KINDS else "finding"
    title = (title or "").strip()
    if len(title) < 4:
        return SubmitOutcome(False, "Bitte einen aussagekräftigen Titel (min. 4 Zeichen).")
    with SynapseStore(cfg) as store:
        proj = store.con.execute(
            "SELECT id, status FROM projects WHERE id=?", [project_id]).fetchone()
        if not proj:
            return SubmitOutcome(False, "Projekt nicht gefunden.")
        if proj[1] == "archived":
            return SubmitOutcome(False, "Projekt ist archiviert – keine neuen Beiträge.")
        trust = _trust_level(cfg, evidence_doi, link)
        cid = "c-" + secrets.token_hex(6)
        store.con.execute(
            "INSERT INTO contributions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [cid, project_id, kind, title, body.strip()[:8000], link.strip()[:500],
             evidence_doi.strip()[:120], (contributor_name or "anonym").strip()[:120],
             contributor_orcid.strip()[:40], trust, "visible", _now()])
    warn = ""
    if any(w in (title + " " + body).lower() for w in _SENSITIVE):
        warn = (" Hinweis: sensibles Thema – dies ist KEINE medizinische/rechtliche "
                "Beratung und (sofern nicht geprüft) unbestätigt.")
    return SubmitOutcome(True, f"Beitrag aufgenommen (Stufe: {trust}).{warn}",
                         {"id": cid, "trust_level": trust})


def list_projects(cfg: Config, q: str = "", limit: int = 50) -> list[dict]:
    with SynapseStore(cfg) as store:
        if q.strip():
            like = f"%{q.strip().lower()}%"
            rows = store.con.execute(
                "SELECT id,title,area,owner_name,status,created_at FROM projects "
                "WHERE lower(title) LIKE ? OR lower(area) LIKE ? "
                "ORDER BY created_at DESC LIMIT ?", [like, like, limit]).fetchall()
        else:
            rows = store.con.execute(
                "SELECT id,title,area,owner_name,status,created_at FROM projects "
                "ORDER BY created_at DESC LIMIT ?", [limit]).fetchall()
        out = []
        for r in rows:
            n = store.con.execute(
                "SELECT COUNT(*) FROM contributions WHERE project_id=? AND status='visible'",
                [r[0]]).fetchone()[0]
            out.append({"id": r[0], "title": r[1], "area": r[2], "owner_name": r[3],
                        "status": r[4], "created_at": r[5], "contributions": int(n)})
    return out


def get_project(cfg: Config, project_id: str) -> dict | None:
    with SynapseStore(cfg) as store:
        p = store.con.execute(
            "SELECT id,title,area,description,owner_name,owner_orcid,license,status,"
            "created_at FROM projects WHERE id=?", [project_id]).fetchone()
        if not p:
            return None
        rows = store.con.execute(
            "SELECT id,kind,title,body,link,evidence_doi,contributor_name,"
            "contributor_orcid,trust_level,status,created_at FROM contributions "
            "WHERE project_id=? AND status<>'removed' ORDER BY created_at DESC",
            [project_id]).fetchall()
    contribs = [{"id": r[0], "kind": r[1], "title": r[2], "body": r[3], "link": r[4],
                 "evidence_doi": r[5], "contributor_name": r[6], "contributor_orcid": r[7],
                 "trust_level": r[8], "status": r[9], "created_at": r[10]} for r in rows]
    return {"id": p[0], "title": p[1], "area": p[2], "description": p[3],
            "owner_name": p[4], "owner_orcid": p[5], "license": p[6], "status": p[7],
            "created_at": p[8], "contributions": contribs}


def report(cfg: Config, contribution_id: str, reason: str = "") -> SubmitOutcome:
    with SynapseStore(cfg) as store:
        ex = store.con.execute(
            "SELECT id FROM contributions WHERE id=?", [contribution_id]).fetchone()
        if not ex:
            return SubmitOutcome(False, "Beitrag nicht gefunden.")
        store.con.execute("INSERT INTO reports VALUES (?,?,?,?)",
                          ["r-" + secrets.token_hex(5), contribution_id,
                           reason.strip()[:500], _now()])
        store.con.execute("UPDATE contributions SET status='flagged' "
                          "WHERE id=? AND status='visible'", [contribution_id])
    return SubmitOutcome(True, "Danke – der Beitrag wurde zur Prüfung markiert.")


def _verify_owner(store, project_id: str, owner_token: str) -> bool:
    row = store.con.execute(
        "SELECT owner_token FROM projects WHERE id=?", [project_id]).fetchone()
    return bool(row) and row[0] == _hash(owner_token or "")


def moderate(cfg: Config, project_id: str, owner_token: str, contribution_id: str,
             action: str) -> SubmitOutcome:
    """Owner kuratiert sein Projekt: Beitrag entfernen/wiederherstellen."""
    new_status = {"remove": "removed", "restore": "visible"}.get(action)
    if not new_status:
        return SubmitOutcome(False, "Aktion unbekannt (remove|restore).")
    with SynapseStore(cfg) as store:
        if not _verify_owner(store, project_id, owner_token):
            return SubmitOutcome(False, "Owner-Token ungültig – keine Berechtigung.")
        store.con.execute(
            "UPDATE contributions SET status=? WHERE id=? AND project_id=?",
            [new_status, contribution_id, project_id])
    return SubmitOutcome(True, f"Beitrag auf '{new_status}' gesetzt.")


def archive(cfg: Config, project_id: str, owner_token: str, archived: bool = True) -> SubmitOutcome:
    with SynapseStore(cfg) as store:
        if not _verify_owner(store, project_id, owner_token):
            return SubmitOutcome(False, "Owner-Token ungültig.")
        store.con.execute("UPDATE projects SET status=? WHERE id=?",
                          ["archived" if archived else "active", project_id])
    return SubmitOutcome(True, "Projekt " + ("archiviert." if archived else "reaktiviert."))
