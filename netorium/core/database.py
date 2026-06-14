from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Final

SCHEMA_VERSION: Final[int] = 2

SCHEMA_SQL: Final[str] = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS zones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    floor INTEGER,
    department TEXT,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip_address TEXT NOT NULL UNIQUE,
    zone_id INTEGER NOT NULL REFERENCES zones(id) ON DELETE RESTRICT,
    hostname TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_devices_zone_id ON devices(zone_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_logs_entity ON audit_logs(entity_type, entity_id);
"""


class DatabaseError(RuntimeError):
    pass


def normalize_database_path(path: str | Path) -> Path:
    return Path(path).expanduser()


def connect_database(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(normalize_database_path(path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(path: str | Path) -> Path:
    database_path = normalize_database_path(path)

    try:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = connect_database(database_path)
        try:
            with connection:
                connection.executescript(SCHEMA_SQL)
                connection.execute(
                    """
                    INSERT OR IGNORE INTO schema_migrations(version, applied_at)
                    VALUES (?, datetime('now'))
                    """,
                    (SCHEMA_VERSION,),
                )
        finally:
            connection.close()
    except OSError as exc:
        raise DatabaseError(f"Could not prepare database path {database_path}: {exc}") from exc
    except sqlite3.Error as exc:
        raise DatabaseError(f"Could not initialize database {database_path}: {exc}") from exc

    return database_path
