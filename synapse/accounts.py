"""Offizielle Nutzerprofile (Konten) – sicher & ohne Fremd-Dienste.

- **Passwörter** werden mit ``scrypt`` (Standardbibliothek) + Salt gehasht –
  niemals im Klartext gespeichert.
- **Sitzungen** über ein zufälliges Token; in der DB liegt nur dessen Hash
  (ein DB-Leak gibt keine gültigen Tokens preis), mit Ablaufdatum.
- **ORCID-Verifikation** über die öffentliche ORCID-API (ohne Login): existiert
  die ORCID, wird der dort registrierte Name übernommen → „verifizierter
  Forscher". Macht Beiträge nachvollziehbar und seriös.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from synapse.config import Config
from synapse.storage import SynapseStore

_SESSION_DAYS = 30
_ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


@dataclass
class Outcome:
    ok: bool
    message: str = ""
    data: dict | None = None


# -- Passwort-Hashing (scrypt) ---------------------------------------------- #
def hash_pw(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(pw.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_pw(pw: str, stored: str) -> bool:
    try:
        _, b_salt, b_dk = stored.split("$")
        salt, dk = base64.b64decode(b_salt), base64.b64decode(b_dk)
        test = hashlib.scrypt(pw.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(test, dk)
    except Exception:  # noqa: BLE001
        return False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# -- ORCID-Verifikation (öffentlich, kein Login nötig) ---------------------- #
def verify_orcid(orcid: str) -> tuple[bool, str]:
    """Prüft, ob die ORCID existiert; liefert (gültig, registrierter Name)."""
    orcid = orcid.strip()
    if not _ORCID_RE.match(orcid):
        return False, ""
    url = f"https://pub.orcid.org/v3.0/{orcid}/person"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json",
                                                   "User-Agent": "Synapse/0.1"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        name = data.get("name") or {}
        given = ((name.get("given-names") or {}) or {}).get("value", "")
        family = ((name.get("family-name") or {}) or {}).get("value", "")
        full = (f"{given} {family}").strip()
        return True, full
    except Exception:  # noqa: BLE001 (offline/ungültig)
        return False, ""


# -- Registrierung / Login / Sitzung ---------------------------------------- #
_USER_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,32}$")


_ACCOUNT_TYPES = {"student", "researcher", "other"}


def register(cfg: Config, username: str, password: str, name: str = "",
             email: str = "", orcid: str = "", affiliation: str = "",
             bio: str = "", account_type: str = "other") -> Outcome:
    username = (username or "").strip()
    if not _USER_RE.match(username):
        return Outcome(False, "Nutzername: 3–32 Zeichen (Buchstaben/Zahlen/._-).")
    if len(password or "") < 8:
        return Outcome(False, "Passwort: mindestens 8 Zeichen.")
    account_type = account_type if account_type in _ACCOUNT_TYPES else "other"
    orcid_verified = False
    if orcid.strip():
        ok, reg_name = verify_orcid(orcid)
        if not ok:
            return Outcome(False, "ORCID nicht verifizierbar (Format/Existenz prüfen) "
                           "oder offline. Du kannst sie später im Profil ergänzen.")
        orcid_verified = True
        name = name or reg_name
    with SynapseStore(cfg) as store:
        ex = store.con.execute("SELECT id FROM users WHERE lower(username)=?",
                               [username.lower()]).fetchone()
        if ex:
            return Outcome(False, "Nutzername bereits vergeben.")
        uid = "u-" + secrets.token_hex(8)
        store.con.execute(
            "INSERT INTO users (id,username,email,password_hash,name,affiliation,"
            "orcid,orcid_verified,bio,role,account_type,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [uid, username, email.strip()[:160], hash_pw(password),
             (name or username).strip()[:120], affiliation.strip()[:160],
             orcid.strip()[:40], orcid_verified, bio.strip()[:2000], "user",
             account_type, _now().isoformat()])
    return Outcome(True, "Konto erstellt.", {"user_id": uid})


def authenticate(cfg: Config, username: str, password: str) -> str | None:
    with SynapseStore(cfg) as store:
        row = store.con.execute(
            "SELECT id, password_hash FROM users WHERE lower(username)=?",
            [(username or "").strip().lower()]).fetchone()
    if not row or not verify_pw(password or "", row[1]):
        return None
    return row[0]


def create_session(cfg: Config, user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    with SynapseStore(cfg) as store:
        store.con.execute("INSERT INTO sessions VALUES (?,?,?,?)", [
            _hash_token(token), user_id,
            (_now() + timedelta(days=_SESSION_DAYS)).isoformat(), _now().isoformat()])
    return token


def destroy_session(cfg: Config, token: str) -> None:
    if not token:
        return
    with SynapseStore(cfg) as store:
        store.con.execute("DELETE FROM sessions WHERE token_hash=?", [_hash_token(token)])


def session_user(cfg: Config, token: str) -> dict | None:
    if not token:
        return None
    with SynapseStore(cfg) as store:
        row = store.con.execute(
            "SELECT user_id, expires_at FROM sessions WHERE token_hash=?",
            [_hash_token(token)]).fetchone()
        if not row:
            return None
        try:
            if datetime.fromisoformat(row[1]) < _now():
                store.con.execute("DELETE FROM sessions WHERE token_hash=?",
                                  [_hash_token(token)])
                return None
        except Exception:  # noqa: BLE001
            return None
        return _user_row(store, row[0])


def get_user(cfg: Config, user_id: str) -> dict | None:
    with SynapseStore(cfg) as store:
        return _user_row(store, user_id)


def _user_row(store, user_id: str) -> dict | None:
    r = store.con.execute(
        "SELECT id, username, name, affiliation, orcid, orcid_verified, bio, role, "
        "COALESCE(account_type,'other'), created_at FROM users WHERE id=?",
        [user_id]).fetchone()
    if not r:
        return None
    return {"id": r[0], "username": r[1], "name": r[2], "affiliation": r[3],
            "orcid": r[4], "orcid_verified": bool(r[5]), "bio": r[6],
            "role": r[7], "account_type": r[8], "created_at": r[9]}


def update_profile(cfg: Config, user_id: str, name: str = "", affiliation: str = "",
                   orcid: str = "", bio: str = "", account_type: str = "") -> Outcome:
    orcid = orcid.strip()
    orcid_verified = False
    if orcid:
        ok, reg_name = verify_orcid(orcid)
        if not ok:
            return Outcome(False, "ORCID nicht verifizierbar (Format/Existenz) oder offline.")
        orcid_verified = True
        name = name or reg_name
    at = account_type if account_type in _ACCOUNT_TYPES else None
    with SynapseStore(cfg) as store:
        if not _user_row(store, user_id):
            return Outcome(False, "Konto nicht gefunden.")
        store.con.execute(
            "UPDATE users SET name=?, affiliation=?, orcid=?, orcid_verified=?, bio=?, "
            "account_type=COALESCE(?, account_type) WHERE id=?",
            [name.strip()[:120], affiliation.strip()[:160], orcid[:40],
             orcid_verified, bio.strip()[:2000], at, user_id])
    return Outcome(True, "Profil aktualisiert."
                   + (" ORCID verifiziert." if orcid_verified else ""))
