"""GET /orders."""

import sqlite3


def list_orders(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, user_id, total_cents, status, created_at FROM orders ORDER BY id"
    ).fetchall()
    return [dict(row) for row in rows]
