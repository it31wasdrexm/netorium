import sqlite3
from pathlib import Path

from netorium.core.database import initialize_database


def test_initialize_database_creates_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "state" / "netorium.db"

    created_path = initialize_database(database_path)

    assert created_path == database_path
    assert database_path.exists()

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert "schema_migrations" in tables
    assert "zones" in tables
    assert "devices" in tables
    assert "audit_logs" in tables
