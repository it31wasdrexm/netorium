from __future__ import annotations

import ipaddress
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from netorium.core.audit import write_audit_entry
from netorium.core.database import connect_database, initialize_database

FirewallAction = Literal["block", "unblock"]


class FirewallError(RuntimeError):
    pass


@dataclass(frozen=True)
class FirewallStatus:
    platform_name: str
    real_firewall_supported: bool
    dry_run_supported: bool


@dataclass(frozen=True)
class FirewallPlan:
    action: FirewallAction
    ip_address: str
    reason: str
    dry_run: bool
    platform_name: str
    command: str
    audit_action: str


def firewall_status(platform_name: str | None = None) -> FirewallStatus:
    active_platform = platform_name or sys.platform
    return FirewallStatus(
        platform_name=active_platform,
        real_firewall_supported=_is_windows(active_platform),
        dry_run_supported=True,
    )


def block_ip(
    database_path: str | Path,
    *,
    ip_address: str,
    reason: str,
    dry_run: bool = True,
    yes: bool = False,
    platform_name: str | None = None,
) -> FirewallPlan:
    return _run_firewall_plan(
        database_path,
        action="block",
        ip_address=ip_address,
        reason=reason,
        dry_run=dry_run,
        yes=yes,
        platform_name=platform_name,
    )


def unblock_ip(
    database_path: str | Path,
    *,
    ip_address: str,
    reason: str,
    dry_run: bool = True,
    yes: bool = False,
    platform_name: str | None = None,
) -> FirewallPlan:
    return _run_firewall_plan(
        database_path,
        action="unblock",
        ip_address=ip_address,
        reason=reason,
        dry_run=dry_run,
        yes=yes,
        platform_name=platform_name,
    )


def _run_firewall_plan(
    database_path: str | Path,
    *,
    action: FirewallAction,
    ip_address: str,
    reason: str,
    dry_run: bool,
    yes: bool,
    platform_name: str | None,
) -> FirewallPlan:
    clean_ip = _normalize_ip_address(ip_address)
    clean_reason = _normalize_reason(reason)
    active_platform = platform_name or sys.platform
    command = _build_windows_command(action, clean_ip)
    audit_action = f"firewall.{action}.dry_run" if dry_run else f"firewall.{action}"
    plan = FirewallPlan(
        action=action,
        ip_address=clean_ip,
        reason=clean_reason,
        dry_run=dry_run,
        platform_name=active_platform,
        command=command,
        audit_action=audit_action,
    )

    if not dry_run:
        _validate_real_mode(active_platform, yes)

    _write_firewall_audit(database_path, plan)
    return plan


def _validate_real_mode(platform_name: str, yes: bool) -> None:
    if not yes:
        raise FirewallError("Real firewall changes require --yes. Re-run with --dry-run to preview.")
    if not _is_windows(platform_name):
        raise FirewallError("Real firewall changes are Windows-only. Re-run with --dry-run on this OS.")
    raise FirewallError("Real Windows Firewall execution is not implemented yet. Re-run with --dry-run.")


def _write_firewall_audit(database_path: str | Path, plan: FirewallPlan) -> None:
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    path = initialize_database(database_path)
    try:
        connection = connect_database(path)
        try:
            with connection:
                write_audit_entry(
                    connection,
                    action=plan.audit_action,
                    entity_type="firewall",
                    entity_id=plan.ip_address,
                    details={
                        "action": plan.action,
                        "ip_address": plan.ip_address,
                        "reason": plan.reason,
                        "dry_run": plan.dry_run,
                        "platform": plan.platform_name,
                        "command": plan.command,
                    },
                    created_at=timestamp,
                )
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise FirewallError(f"Could not write firewall audit entry: {exc}") from exc


def _build_windows_command(action: FirewallAction, ip_address: str) -> str:
    rule_name = f"Netorium Block {ip_address}"
    if action == "block":
        return (
            "New-NetFirewallRule "
            f"-DisplayName '{rule_name}' "
            "-Direction Outbound "
            f"-RemoteAddress {ip_address} "
            "-Action Block"
        )
    return f"Remove-NetFirewallRule -DisplayName '{rule_name}'"


def _normalize_ip_address(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError as exc:
        raise FirewallError(f"Invalid IP address: {value}") from exc


def _normalize_reason(value: str) -> str:
    reason = value.strip()
    if not reason:
        raise FirewallError("Firewall reason cannot be empty.")
    return reason


def _is_windows(platform_name: str) -> bool:
    return platform_name.startswith("win")
