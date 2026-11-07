"""Minimal anonymous server-side sessions: opaque random cookie -> owner_id.

This is NOT enterprise IAM. It only guarantees that two browser sessions get
distinct unpredictable identities and that owner_id is never taken from the client.
"""
from __future__ import annotations

import hashlib
import secrets

from .db import Database, new_id, now

COOKIE_NAME = "dd_session"
COOKIE_MAX_AGE = 30 * 24 * 3600


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def resolve(db: Database, token: str | None) -> str | None:
    if not token or len(token) > 200:
        return None
    row = db.one("SELECT owner_id FROM sessions WHERE token_hash = ?", (_hash(token),))
    return row["owner_id"] if row else None


def create(db: Database) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    owner_id = new_id("own")
    ts = now()
    with db.tx() as con:
        con.execute("INSERT INTO sessions(token_hash, owner_id, created_at, last_seen_at) VALUES (?,?,?,?)",
                    (_hash(token), owner_id, ts, ts))
    return token, owner_id
