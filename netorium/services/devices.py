from __future__ import annotations

import ipaddress
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from netorium.core.audit import write_audit_entry
from netorium.core.database import connect_database, initialize_database


class DeviceError(RuntimeError):
    pass


class DeviceNotFoundError(DeviceError):
    pass


class DeviceZoneNotFoundError(DeviceError):
    pass


@dataclass(frozen=True)
class Device:
    id: int
    ip_address: str
    zone_name: str
    hostname: str | None
    created_at: str
    updated_at: str


def add_device(
    database_path: str | Path,
    *,
    ip_address: str,
    zone_name: str,
    hostname: str | None = None,
) -> Device:
    clean_ip = _normalize_ip_address(ip_address)
    clean_zone = _normalize_zone_name(zone_name)
    clean_hostname = _clean_optional_text(hostname)
    timestamp = _utc_timestamp()
    path = initialize_database(database_path)

    try:
        connection = connect_database(path)
        try:
            with connection:
                zone_id = _zone_id(connection, clean_zone)
                connection.execute(
                    """
                    INSERT INTO devices(ip_address, zone_id, hostname, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (clean_ip, zone_id, clean_hostname, timestamp, timestamp),
                )
                write_audit_entry(
                    connection,
                    action="device.add",
                    entity_type="device",
                    entity_id=clean_ip,
                    details={
                        "ip_address": clean_ip,
                        "zone": clean_zone,
                        "hostname": clean_hostname,
                    },
                    created_at=timestamp,
                )
        finally:
            connection.close()
    except sqlite3.IntegrityError as exc:
        raise DeviceError(f"Device already exists: {clean_ip}") from exc
    except sqlite3.Error as exc:
        raise DeviceError(f"Could not add device {clean_ip}: {exc}") from exc

    return get_device(path, clean_ip)


def list_devices(database_path: str | Path) -> list[Device]:
    path = initialize_database(database_path)
    try:
        connection = connect_database(path)
        try:
            rows = connection.execute(
                """
                SELECT
                    devices.id,
                    devices.ip_address,
                    zones.name AS zone_name,
                    devices.hostname,
                    devices.created_at,
                    devices.updated_at
                FROM devices
                JOIN zones ON zones.id = devices.zone_id
                ORDER BY devices.ip_address
                """
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise DeviceError(f"Could not list devices: {exc}") from exc

    return [_device_from_row(row) for row in rows]


def get_device(database_path: str | Path, ip_address: str) -> Device:
    clean_ip = _normalize_ip_address(ip_address)
    path = initialize_database(database_path)
    try:
        connection = connect_database(path)
        try:
            row = connection.execute(
                """
                SELECT
                    devices.id,
                    devices.ip_address,
                    zones.name AS zone_name,
                    devices.hostname,
                    devices.created_at,
                    devices.updated_at
                FROM devices
                JOIN zones ON zones.id = devices.zone_id
                WHERE devices.ip_address = ?
                """,
                (clean_ip,),
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise DeviceError(f"Could not read device {clean_ip}: {exc}") from exc

    if row is None:
        raise DeviceNotFoundError(f"Device not found: {clean_ip}")
    return _device_from_row(row)


def move_device(database_path: str | Path, ip_address: str, *, zone_name: str) -> Device:
    clean_ip = _normalize_ip_address(ip_address)
    clean_zone = _normalize_zone_name(zone_name)
    timestamp = _utc_timestamp()
    path = initialize_database(database_path)

    try:
        connection = connect_database(path)
        try:
            with connection:
                current = _device_row(connection, clean_ip)
                target_zone_id = _zone_id(connection, clean_zone)
                connection.execute(
                    """
                    UPDATE devices
                    SET zone_id = ?, updated_at = ?
                    WHERE ip_address = ?
                    """,
                    (target_zone_id, timestamp, clean_ip),
                )
                write_audit_entry(
                    connection,
                    action="device.move",
                    entity_type="device",
                    entity_id=clean_ip,
                    details={
                        "ip_address": clean_ip,
                        "from_zone": str(current["zone_name"]),
                        "to_zone": clean_zone,
                    },
                    created_at=timestamp,
                )
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise DeviceError(f"Could not move device {clean_ip}: {exc}") from exc

    return get_device(path, clean_ip)


def delete_device(database_path: str | Path, ip_address: str) -> Device:
    device = get_device(database_path, ip_address)
    timestamp = _utc_timestamp()
    path = initialize_database(database_path)

    try:
        connection = connect_database(path)
        try:
            with connection:
                connection.execute("DELETE FROM devices WHERE ip_address = ?", (device.ip_address,))
                write_audit_entry(
                    connection,
                    action="device.delete",
                    entity_type="device",
                    entity_id=device.ip_address,
                    details={
                        "ip_address": device.ip_address,
                        "zone": device.zone_name,
                        "hostname": device.hostname,
                    },
                    created_at=timestamp,
                )
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise DeviceError(f"Could not delete device {device.ip_address}: {exc}") from exc

    return device


def _device_row(connection: sqlite3.Connection, ip_address: str) -> sqlite3.Row:
    row = cast(
        sqlite3.Row | None,
        connection.execute(
            """
            SELECT
                devices.id,
                devices.ip_address,
                zones.name AS zone_name,
                devices.hostname,
                devices.created_at,
                devices.updated_at
            FROM devices
            JOIN zones ON zones.id = devices.zone_id
            WHERE devices.ip_address = ?
            """,
            (ip_address,),
        ).fetchone(),
    )
    if row is None:
        raise DeviceNotFoundError(f"Device not found: {ip_address}")
    return row


def _zone_id(connection: sqlite3.Connection, zone_name: str) -> int:
    row = connection.execute("SELECT id FROM zones WHERE name = ?", (zone_name,)).fetchone()
    if row is None:
        raise DeviceZoneNotFoundError(f"Zone not found: {zone_name}")
    return int(row["id"])


def _device_from_row(row: sqlite3.Row) -> Device:
    return Device(
        id=int(row["id"]),
        ip_address=str(row["ip_address"]),
        zone_name=str(row["zone_name"]),
        hostname=_clean_optional_text(row["hostname"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _normalize_ip_address(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError as exc:
        raise DeviceError(f"Invalid IP address: {value}") from exc


def _normalize_zone_name(name: str) -> str:
    zone_name = name.strip()
    if not zone_name:
        raise DeviceZoneNotFoundError("Zone name cannot be empty.")
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
