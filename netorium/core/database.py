from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Final

SCHEMA_VERSION: Final[int] = 7

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

CREATE TABLE IF NOT EXISTS controller_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    host TEXT NOT NULL,
    port INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS enrollment_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id TEXT NOT NULL UNIQUE,
    token_hash TEXT NOT NULL UNIQUE,
    purpose TEXT NOT NULL,
    zone TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    used_at TEXT,
    revoked_at TEXT
);

CREATE TABLE IF NOT EXISTS agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL UNIQUE,
    hostname TEXT NOT NULL,
    zone TEXT NOT NULL,
    device_token_hash TEXT NOT NULL UNIQUE,
    enrolled_at TEXT NOT NULL,
    last_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS agent_commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    command_id TEXT NOT NULL UNIQUE,
    agent_id TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    command_type TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    signature TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    result_message TEXT,
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_devices_zone_id ON devices(zone_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_logs_entity ON audit_logs(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_enrollment_tokens_active
ON enrollment_tokens(expires_at, used_at, revoked_at);
CREATE INDEX IF NOT EXISTS idx_agents_zone ON agents(zone);
CREATE INDEX IF NOT EXISTS idx_agent_commands_agent_status
ON agent_commands(agent_id, status, created_at);

CREATE TABLE IF NOT EXISTS agent_traffic_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    bytes_sent INTEGER NOT NULL,
    bytes_received INTEGER NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_traffic_samples_agent_time
ON agent_traffic_samples(agent_id, recorded_at);
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
                _ensure_column(
                    connection,
                    table_name="agent_commands",
                    column_name="signature",
                    definition="TEXT NOT NULL DEFAULT ''",
                )
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


def _ensure_column(
    connection: sqlite3.Connection,
    *,
    table_name: str,
    column_name: str,
    definition: str,
) -> None:
    columns = {
        str(row["name"])
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in columns:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")
