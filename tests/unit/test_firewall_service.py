from pathlib import Path

import pytest

from netorium.core.audit import list_audit_entries
from netorium.services.firewall import FirewallError, block_ip, firewall_status, unblock_ip


def test_firewall_status_reports_dry_run_everywhere() -> None:
    status = firewall_status(platform_name="linux")

    assert status.dry_run_supported is True
    assert status.real_firewall_supported is False


def test_block_ip_dry_run_writes_audit_entry(tmp_path: Path) -> None:
    database_path = tmp_path / "netorium.db"

    plan = block_ip(
        database_path,
        ip_address="192.168.1.25",
        reason="Policy violation",
        dry_run=True,
        platform_name="linux",
    )

    assert plan.dry_run is True
    assert plan.audit_action == "firewall.block.dry_run"
    assert "New-NetFirewallRule" in plan.command

    entries = list_audit_entries(str(database_path))
    assert entries[0].action == "firewall.block.dry_run"
    assert entries[0].entity_id == "192.168.1.25"
    assert entries[0].details["reason"] == "Policy violation"


def test_unblock_ip_dry_run_writes_audit_entry(tmp_path: Path) -> None:
    database_path = tmp_path / "netorium.db"

    plan = unblock_ip(
        database_path,
        ip_address="192.168.1.25",
        reason="Access restored",
        dry_run=True,
        platform_name="linux",
    )

    assert plan.audit_action == "firewall.unblock.dry_run"
    assert "Remove-NetFirewallRule" in plan.command


def test_firewall_rejects_invalid_ip(tmp_path: Path) -> None:
    with pytest.raises(FirewallError, match="Invalid IP address"):
        block_ip(tmp_path / "netorium.db", ip_address="not-an-ip", reason="Policy violation")


def test_firewall_requires_reason(tmp_path: Path) -> None:
    with pytest.raises(FirewallError, match="reason cannot be empty"):
        block_ip(tmp_path / "netorium.db", ip_address="192.168.1.25", reason=" ")


def test_real_firewall_requires_yes(tmp_path: Path) -> None:
    with pytest.raises(FirewallError, match="require --yes"):
        block_ip(
            tmp_path / "netorium.db",
            ip_address="192.168.1.25",
            reason="Policy violation",
            dry_run=False,
            yes=False,
            platform_name="linux",
        )


def test_real_firewall_is_windows_only(tmp_path: Path) -> None:
    with pytest.raises(FirewallError, match="Windows-only"):
        block_ip(
            tmp_path / "netorium.db",
            ip_address="192.168.1.25",
            reason="Policy violation",
            dry_run=False,
            yes=True,
            platform_name="linux",
        )
