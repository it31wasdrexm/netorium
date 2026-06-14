from pathlib import Path

import pytest

from netorium.core.audit import list_audit_entries
from netorium.services.devices import (
    DeviceError,
    DeviceNotFoundError,
    DeviceZoneNotFoundError,
    add_device,
    delete_device,
    get_device,
    list_devices,
    move_device,
)
from netorium.services.zones import ZoneError, add_zone, delete_zone


def test_device_crud_move_and_audit_entries(tmp_path: Path) -> None:
    database_path = tmp_path / "netorium.db"
    add_zone(database_path, name="accounting")
    add_zone(database_path, name="reception")

    created = add_device(
        database_path,
        ip_address="192.168.1.25",
        zone_name="accounting",
        hostname="pc-acc-01",
    )

    assert created.ip_address == "192.168.1.25"
    assert created.zone_name == "accounting"
    assert created.hostname == "pc-acc-01"
    assert get_device(database_path, "192.168.1.25").zone_name == "accounting"
    assert [device.ip_address for device in list_devices(database_path)] == ["192.168.1.25"]

    moved = move_device(database_path, "192.168.1.25", zone_name="reception")

    assert moved.zone_name == "reception"

    deleted = delete_device(database_path, "192.168.1.25")

    assert deleted.ip_address == "192.168.1.25"
    assert list_devices(database_path) == []

    device_actions = [
        entry.action for entry in list_audit_entries(str(database_path)) if entry.entity_type == "device"
    ]
    assert device_actions == ["device.delete", "device.move", "device.add"]


def test_add_device_rejects_invalid_ip(tmp_path: Path) -> None:
    database_path = tmp_path / "netorium.db"
    add_zone(database_path, name="accounting")

    with pytest.raises(DeviceError, match="Invalid IP address"):
        add_device(database_path, ip_address="not-an-ip", zone_name="accounting")


def test_add_device_requires_existing_zone(tmp_path: Path) -> None:
    database_path = tmp_path / "netorium.db"

    with pytest.raises(DeviceZoneNotFoundError, match="Zone not found"):
        add_device(database_path, ip_address="192.168.1.25", zone_name="missing")


def test_add_device_rejects_duplicate_ip(tmp_path: Path) -> None:
    database_path = tmp_path / "netorium.db"
    add_zone(database_path, name="accounting")
    add_device(database_path, ip_address="192.168.1.25", zone_name="accounting")

    with pytest.raises(DeviceError, match="already exists"):
        add_device(database_path, ip_address="192.168.1.25", zone_name="accounting")


def test_get_device_reports_missing_device(tmp_path: Path) -> None:
    database_path = tmp_path / "netorium.db"

    with pytest.raises(DeviceNotFoundError, match="Device not found"):
        get_device(database_path, "192.168.1.25")


def test_zone_with_devices_cannot_be_deleted(tmp_path: Path) -> None:
    database_path = tmp_path / "netorium.db"
    add_zone(database_path, name="accounting")
    add_device(database_path, ip_address="192.168.1.25", zone_name="accounting")

    with pytest.raises(ZoneError, match="cannot be deleted"):
        delete_zone(database_path, "accounting")
