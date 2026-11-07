"""One bootstrap account, with a persistent owner and hashed password in SQLite."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

from .db import Database, new_id
from .errors import ApiError
from .settings import LOOPBACK_NAMES, SettingsError

ITERATIONS = 600_000


def password_hash(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), ITERATIONS).hex()
    return f"pbkdf2_sha256${ITERATIONS}${salt}${digest}"


def verify(password: str, encoded: str) -> bool:
    _, iterations, salt, expected = encoded.split("$")
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations)).hex()
    return hmac.compare_digest(actual, expected)


def configure(db: Database, allowed_hosts: frozenset) -> None:
    username = os.environ.get("DD_AUTH_USERNAME", "admin").strip()
    password = os.environ.get("DD_AUTH_PASSWORD", "admin12345")
    display_name = os.environ.get("DD_AUTH_DISPLAY_NAME", "Аналитик").strip()
    if not username or len(username) > 120 or not display_name or len(display_name) > 120:
        raise SettingsError("DD_AUTH_USERNAME and DD_AUTH_DISPLAY_NAME must contain 1..120 characters")
    if not 8 <= len(password) <= 256:
        raise SettingsError("DD_AUTH_PASSWORD must contain 8..256 characters")
    try:
        for value in (username, password, display_name):
            value.encode("utf-8")
    except UnicodeEncodeError:
        raise SettingsError("DD_AUTH_* values must contain valid Unicode characters") from None
    if not allowed_hosts <= LOOPBACK_NAMES and password == "admin12345":
        raise SettingsError("Set a private DD_AUTH_PASSWORD before allowing non-loopback hosts")
    with db.tx() as con:
        row = con.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if row is None:
            # Renaming the single bootstrap account retains its saved work/owner.
            # Legacy databases may contain extra accounts created by the old rename behavior.
            row = con.execute("SELECT * FROM users ORDER BY rowid LIMIT 1").fetchone()
        if row is None:
            con.execute("INSERT INTO users VALUES (?,?,?,?)",
                        (new_id("own"), username, display_name, password_hash(password)))
        else:
            # Environment changes update credentials without changing ownership of saved work.
            password_changed = not verify(password, row["password_hash"])
            con.execute("UPDATE users SET username = ?, display_name = ?, password_hash = ? WHERE owner_id = ?",
                        (username, display_name, password_hash(password) if password_changed else row["password_hash"], row["owner_id"]))
            if password_changed or row["username"] != username:
                con.execute("DELETE FROM sessions WHERE owner_id = ?", (row["owner_id"],))
        # Old legacy credentials cannot stay active, and their cookies must stop working too.
        con.execute("DELETE FROM sessions WHERE owner_id IN (SELECT owner_id FROM users WHERE username != ?)", (username,))


def user(db: Database, owner_id: str) -> dict | None:
    return db.one("SELECT username, display_name FROM users WHERE owner_id = ?", (owner_id,))


def authenticate(db: Database, username: str, password: str) -> str:
    # Shared persisted limit for the bootstrap account (also covers unknown usernames).
    # The transaction serializes concurrent attempts across processes.
    with db.tx() as con:
        ts = time.time()
        limit = con.execute("SELECT * FROM login_limits WHERE bucket = 'basic'").fetchone()
        failures = limit["failures"] if limit and ts - limit["started_at"] < 60 else 0
        started = limit["started_at"] if failures else ts
        if failures >= 10:
            raise ApiError(429, "LOGIN_RATE_LIMITED", "Слишком много попыток. Повторите вход через минуту.")
        configured_username = os.environ.get("DD_AUTH_USERNAME", "admin").strip()
        row = con.execute("SELECT * FROM users WHERE username = ? AND username = ?",
                          (username.strip(), configured_username)).fetchone()
        # Use the same work factor for unknown usernames.
        encoded = row["password_hash"] if row else f"pbkdf2_sha256${ITERATIONS}$unknown${'0' * 64}"
        valid = verify(password, encoded) and row is not None
        con.execute("INSERT OR REPLACE INTO login_limits VALUES ('basic',?,?)",
                    (0 if valid else failures + 1, started))
        owner_id = row["owner_id"] if valid else None
    if owner_id is None:
        raise ApiError(401, "INVALID_CREDENTIALS", "Неверный логин или пароль.")
    return owner_id
