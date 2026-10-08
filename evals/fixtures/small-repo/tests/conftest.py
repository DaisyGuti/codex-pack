import sqlite3

import pytest
from api.auth import hash_password
from db.connection import connect
from scripts.migrate import migrate


@pytest.fixture
def conn(tmp_path) -> sqlite3.Connection:
    path = str(tmp_path / "test.db")
    migrate(path)
    connection = connect(path)
    connection.execute(
        "INSERT INTO users (email, password_hash) VALUES (?, ?)",
        ("ada@example.com", hash_password("correct horse", b"saltsalt")),
    )
    connection.execute("INSERT INTO orders (user_id, total_cents, status) VALUES (1, 1250, 'open')")
    connection.commit()
    return connection
