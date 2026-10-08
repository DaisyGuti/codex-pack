"""The nightly export: copy the day's orders to the warehouse feed."""

import sqlite3
from collections.abc import Callable

MAX_ATTEMPTS = 3


def fetch_rows(conn: sqlite3.Connection, since: str) -> list[tuple]:
    cursor = conn.execute(
        "SELECT id, user_id, total_cents, status FROM orders WHERE created_at >= ? ORDER BY id",
        (since,),
    )
    return [tuple(row) for row in cursor]


def export_orders(
    conn: sqlite3.Connection,
    feed: list[tuple],
    upload: Callable[[list[tuple]], None],
    since: str,
) -> int:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            for row in fetch_rows(conn, since):
                feed.append(row)
            upload(feed)
            return len(feed)
        except TimeoutError:
            if attempt == MAX_ATTEMPTS:
                raise
    return 0
