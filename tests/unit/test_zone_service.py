from pathlib import Path

import pytest

from netorium.core.audit import list_audit_entries
from netorium.services.zones import (
    ZoneError,
    ZoneNotFoundError,
    add_zone,
    delete_zone,
    get_zone,
    list_zones,
)


def test_zone_crud_writes_audit_entries(tmp_path: Path) -> None:
    database_path = tmp_path / "netorium.db"

    created = add_zone(
        database_path,
        name="accounting",
        floor=3,
        department="Accounting",
        description="Third floor",
    )

    assert created.name == "accounting"
    assert created.floor == 3
    assert get_zone(database_path, "accounting").department == "Accounting"
    assert [zone.name for zone in list_zones(database_path)] == ["accounting"]

    deleted = delete_zone(database_path, "accounting")

    assert deleted.name == "accounting"
    assert list_zones(database_path) == []

    entries = list_audit_entries(str(database_path))
    assert [entry.action for entry in entries] == ["zone.delete", "zone.add"]
    assert entries[0].entity_id == "accounting"


def test_add_zone_rejects_duplicate_names(tmp_path: Path) -> None:
    database_path = tmp_path / "netorium.db"
    add_zone(database_path, name="accounting")

    with pytest.raises(ZoneError, match="already exists"):
        add_zone(database_path, name="accounting")


def test_get_zone_reports_missing_zone(tmp_path: Path) -> None:
    database_path = tmp_path / "netorium.db"

    with pytest.raises(ZoneNotFoundError, match="Zone not found"):
        get_zone(database_path, "missing")
