"""Server-side sessions: opaque random cookie -> anonymous or account owner_id.

Anonymous sessions get separate random owners; authenticated sessions use the
account's stable owner. The owner_id is never taken from the client.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone

from .db import Database, new_id, now

COOKIE_NAME = "dd_session"
COOKIE_MAX_AGE = 30 * 24 * 3600


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def resolve(db: Database, token: str | None) -> str | None:
    if not token or len(token) > 200:
        return None
    row = db.one("SELECT owner_id, created_at FROM sessions WHERE token_hash = ?", (_hash(token),))
    if row:
        created = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
        if (datetime.now(timezone.utc) - created).total_seconds() < COOKIE_MAX_AGE:
            return row["owner_id"]
    return None


def create(db: Database, owner_id: str | None = None, revoke_token: str | None = None) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    owner_id = owner_id or new_id("own")
    ts = now()
    with db.tx() as con:
        if revoke_token:
            con.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash(revoke_token),))
        con.execute("INSERT INTO sessions(token_hash, owner_id, created_at, last_seen_at) VALUES (?,?,?,?)",
                    (_hash(token), owner_id, ts, ts))
    return token, owner_id
