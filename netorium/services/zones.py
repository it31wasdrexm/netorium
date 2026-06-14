from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from netorium.core.audit import write_audit_entry
from netorium.core.database import connect_database, initialize_database


class ZoneError(RuntimeError):
    pass


class ZoneNotFoundError(ZoneError):
    pass


@dataclass(frozen=True)
class Zone:
    id: int
    name: str
    floor: int | None
    department: str | None
    description: str
    created_at: str
    updated_at: str


def add_zone(
    database_path: str | Path,
    *,
    name: str,
    floor: int | None = None,
    department: str | None = None,
    description: str = "",
) -> Zone:
    zone_name = _normalize_zone_name(name)
    clean_department = _clean_optional_text(department)
    clean_description = description.strip()
    timestamp = _utc_timestamp()
    path = initialize_database(database_path)

    try:
        connection = connect_database(path)
        try:
            with connection:
                connection.execute(
                    """
                    INSERT INTO zones(name, floor, department, description, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        zone_name,
                        floor,
                        clean_department,
                        clean_description,
                        timestamp,
                        timestamp,
                    ),
                )
                write_audit_entry(
                    connection,
                    action="zone.add",
                    entity_type="zone",
                    entity_id=zone_name,
                    details={
                        "name": zone_name,
                        "floor": floor,
                        "department": clean_department,
                        "description": clean_description,
                    },
                    created_at=timestamp,
                )
        finally:
            connection.close()
    except sqlite3.IntegrityError as exc:
        raise ZoneError(f"Zone already exists: {zone_name}") from exc
    except sqlite3.Error as exc:
        raise ZoneError(f"Could not add zone {zone_name}: {exc}") from exc

    return get_zone(path, zone_name)


def list_zones(database_path: str | Path) -> list[Zone]:
    path = initialize_database(database_path)
    try:
        connection = connect_database(path)
        try:
            rows = connection.execute(
                """
                SELECT id, name, floor, department, description, created_at, updated_at
                FROM zones
                ORDER BY name
                """
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ZoneError(f"Could not list zones: {exc}") from exc

    return [_zone_from_row(row) for row in rows]


def get_zone(database_path: str | Path, name: str) -> Zone:
    zone_name = _normalize_zone_name(name)
    path = initialize_database(database_path)
    try:
        connection = connect_database(path)
        try:
            row = connection.execute(
                """
                SELECT id, name, floor, department, description, created_at, updated_at
                FROM zones
                WHERE name = ?
                """,
                (zone_name,),
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ZoneError(f"Could not read zone {zone_name}: {exc}") from exc

    if row is None:
        raise ZoneNotFoundError(f"Zone not found: {zone_name}")
    return _zone_from_row(row)


def delete_zone(database_path: str | Path, name: str) -> Zone:
    zone = get_zone(database_path, name)
    timestamp = _utc_timestamp()
    path = initialize_database(database_path)

    try:
        connection = connect_database(path)
        try:
            with connection:
                connection.execute("DELETE FROM zones WHERE name = ?", (zone.name,))
                write_audit_entry(
                    connection,
                    action="zone.delete",
                    entity_type="zone",
                    entity_id=zone.name,
                    details={
                        "name": zone.name,
                        "floor": zone.floor,
                        "department": zone.department,
                        "description": zone.description,
                    },
                    created_at=timestamp,
                )
        finally:
            connection.close()
    except sqlite3.IntegrityError as exc:
        raise ZoneError(f"Zone has devices and cannot be deleted: {zone.name}") from exc
    except sqlite3.Error as exc:
        raise ZoneError(f"Could not delete zone {zone.name}: {exc}") from exc

    return zone


def _zone_from_row(row: sqlite3.Row) -> Zone:
    raw_floor = row["floor"]
    return Zone(
        id=int(row["id"]),
        name=str(row["name"]),
        floor=int(raw_floor) if raw_floor is not None else None,
        department=_clean_optional_text(row["department"]),
        description=str(row["description"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _normalize_zone_name(name: str) -> str:
    zone_name = name.strip()
    if not zone_name:
        raise ZoneError("Zone name cannot be empty.")
    return zone_name


def _clean_optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
