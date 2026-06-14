from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from netorium.core.database import connect_database, initialize_database


class AuditError(RuntimeError):
    pass


@dataclass(frozen=True)
class AuditEntry:
    id: int
    action: str
    entity_type: str
    entity_id: str
    details: dict[str, Any]
    created_at: str


def write_audit_entry(
    connection: sqlite3.Connection,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    details: Mapping[str, object] | None = None,
    created_at: str | None = None,
) -> AuditEntry:
    _validate_text(action, "Audit action")
    _validate_text(entity_type, "Audit entity type")
    _validate_text(entity_id, "Audit entity id")

    active_details = dict(details or {})
    timestamp = created_at or _utc_timestamp()
    try:
        details_text = json.dumps(active_details, ensure_ascii=False, sort_keys=True)
        cursor = connection.execute(
            """
            INSERT INTO audit_logs(action, entity_type, entity_id, details, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (action, entity_type, entity_id, details_text, timestamp),
        )
    except (TypeError, sqlite3.Error) as exc:
        raise AuditError(f"Could not write audit entry for {entity_type}:{entity_id}: {exc}") from exc

    entry_id = cursor.lastrowid
    if entry_id is None:
        raise AuditError(f"Could not read audit id for {entity_type}:{entity_id}.")

    return AuditEntry(
        id=entry_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=active_details,
        created_at=timestamp,
    )


def list_audit_entries(path: str, limit: int = 50) -> list[AuditEntry]:
    if limit < 1:
        raise AuditError("Audit limit must be greater than 0.")

    database_path = initialize_database(path)
    try:
        connection = connect_database(database_path)
        try:
            rows = connection.execute(
                """
                SELECT id, action, entity_type, entity_id, details, created_at
                FROM audit_logs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise AuditError(f"Could not read audit entries: {exc}") from exc

    return [_audit_entry_from_row(row) for row in rows]


def _audit_entry_from_row(row: sqlite3.Row) -> AuditEntry:
    raw_details = str(row["details"])
    try:
        details = json.loads(raw_details)
    except json.JSONDecodeError:
        details = {"raw": raw_details}

    if not isinstance(details, dict):
        details = {"raw": raw_details}

    return AuditEntry(
        id=int(row["id"]),
        action=str(row["action"]),
        entity_type=str(row["entity_type"]),
        entity_id=str(row["entity_id"]),
        details=details,
        created_at=str(row["created_at"]),
    )


def _validate_text(value: str, label: str) -> None:
    if not value.strip():
        raise AuditError(f"{label} cannot be empty.")


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
