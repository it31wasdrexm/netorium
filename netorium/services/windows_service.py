"""Helpers for creating Windows services with sc.exe."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence


def format_sc_binpath(executable: str, args: Sequence[str]) -> str:
    """Format the binPath value for ``sc.exe create``.

    ``sc.exe`` stores this value as the service ImagePath.  The executable is
    always quoted so the Windows Service Control Manager can split it from the
    controller arguments even when the path has no spaces.
    """
    executable_part = subprocess.list2cmdline([executable])
    if not executable_part.startswith('"'):
        executable_part = f'"{executable_part}"'
    arg_string = subprocess.list2cmdline(list(args))
    if arg_string:
        return f"{executable_part} {arg_string}"
    return executable_part


def build_sc_create_command(
    service_name: str,
    executable: str,
    args: Sequence[str],
    *,
    display_name: str,
) -> list[str]:
    """Build argument list for ``sc.exe create``."""
    binpath = format_sc_binpath(executable, args)
    return [
        "sc.exe",
        "create",
        service_name,
        "binPath=",
        binpath,
        "start=",
        "auto",
        "DisplayName=",
        display_name,
    ]


def build_sc_config_command(
    service_name: str,
    executable: str,
    args: Sequence[str],
    *,
    display_name: str,
) -> list[str]:
    """Build argument list for ``sc.exe config``."""
    binpath = format_sc_binpath(executable, args)
    return [
        "sc.exe",
        "config",
        service_name,
        "binPath=",
        binpath,
        "start=",
        "auto",
        "DisplayName=",
        display_name,
    ]
