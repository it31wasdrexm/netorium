"""Windows background process helpers (Task Scheduler fallback for CLI apps)."""

from __future__ import annotations

from collections.abc import Sequence

from netorium.services.windows_service import format_sc_binpath


def format_task_command(executable: str, args: Sequence[str]) -> str:
    """Format a scheduled-task action string for ``schtasks /TR``."""
    return format_sc_binpath(executable, args)


def build_schtasks_create_command(
    task_name: str,
    executable: str,
    args: Sequence[str],
    *,
    schedule: str = "ONLOGON",
) -> list[str]:
    """Build argument list for ``schtasks /Create``."""
    return [
        "schtasks",
        "/Create",
        "/TN",
        task_name,
        "/TR",
        format_task_command(executable, args),
        "/SC",
        schedule,
        "/RL",
        "HIGHEST",
        "/IT",
        "/F",
    ]


def build_schtasks_delete_command(task_name: str) -> list[str]:
    """Build argument list for ``schtasks /Delete``."""
    return ["schtasks", "/Delete", "/TN", task_name, "/F"]


def build_schtasks_run_command(task_name: str) -> list[str]:
    """Build argument list for ``schtasks /Run``."""
    return ["schtasks", "/Run", "/TN", task_name]


def build_schtasks_end_command(task_name: str) -> list[str]:
    """Build argument list for ``schtasks /End``."""
    return ["schtasks", "/End", "/TN", task_name]


def build_firewall_add_command(port: int, *, program: str | None = None) -> list[str]:
    """Allow inbound TCP traffic for the controller listen port."""
    command = [
        "netsh",
        "advfirewall",
        "firewall",
        "add",
        "rule",
        'name="Netorium Controller"',
        "dir=in",
        "action=allow",
        "protocol=TCP",
        f"localport={port}",
        "profile=any",
        "enable=yes",
    ]
    if program:
        command.append(f'program="{program}"')
    return command


def build_firewall_add_program_command(program: str) -> list[str]:
    """Allow inbound traffic for the Netorium executable."""
    return [
        "netsh",
        "advfirewall",
        "firewall",
        "add",
        "rule",
        'name="Netorium Controller App"',
        "dir=in",
        "action=allow",
        f'program="{program}"',
        "profile=any",
        "enable=yes",
    ]


def build_firewall_delete_command() -> list[str]:
    """Remove the controller firewall rules created during service install."""
    return [
        "netsh",
        "advfirewall",
        "firewall",
        "delete",
        "rule",
        'name="Netorium Controller"',
    ]


def build_firewall_delete_program_command() -> list[str]:
    """Remove the controller application firewall rule."""
    return [
        "netsh",
        "advfirewall",
        "firewall",
        "delete",
        "rule",
        'name="Netorium Controller App"',
    ]
