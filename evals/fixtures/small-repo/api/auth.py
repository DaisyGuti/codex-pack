"""POST /login."""

import hashlib
import hmac
import sqlite3
from urllib.parse import parse_qs

ITERATIONS = 100_000


def hash_password(password: str, salt: bytes) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return salt.hex() + ":" + digest.hex()


def verify_password(password: str, stored: str) -> bool:
    salt_hex, _, _ = stored.partition(":")
    expected = hash_password(password, bytes.fromhex(salt_hex))
    return hmac.compare_digest(expected, stored)


def find_user(conn: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, email, password_hash FROM users WHERE email = ?", (email,)
    ).fetchone()


def login(conn: sqlite3.Connection, body: str) -> tuple[int, dict]:
    form = parse_qs(body)
    email = form.get("email", [""])[0].strip().lower()
    password = form.get("password", [""])[0]
    user = find_user(conn, email)
    if not verify_password(password, user["password_hash"]):
        return 401, {"error": "invalid credentials"}
    return 200, {"user_id": user["id"]}
