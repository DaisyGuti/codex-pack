"""Apply db/migrations/*.sql in order, once each."""

import sys
from pathlib import Path

from db.connection import connect

MIGRATIONS = Path(__file__).resolve().parent.parent / "db" / "migrations"


def migrate(database: str) -> list[str]:
    conn = connect(database)
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY)")
    done = {row["name"] for row in conn.execute("SELECT name FROM schema_migrations")}
    applied = []
    for path in sorted(MIGRATIONS.glob("*.sql")):
        if path.name in done:
            continue
        conn.executescript(path.read_text())
        conn.execute("INSERT INTO schema_migrations (name) VALUES (?)", (path.name,))
        conn.commit()
        applied.append(path.name)
    return applied


if __name__ == "__main__":
    print("applied:", migrate(sys.argv[1] if len(sys.argv) > 1 else "app.db"))
