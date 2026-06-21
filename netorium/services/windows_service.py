"""Helpers for creating Windows services with sc.exe."""

from __future__ import annotations

from collections.abc import Sequence


def format_sc_binpath(executable: str, args: Sequence[str]) -> str:
    """Format the binPath value for ``sc.exe create``.

    When the executable path contains spaces, it is wrapped in double quotes
    so that ``sc.exe`` / the SCM correctly identifies the executable boundary
    from its arguments.  These inner quotes are then properly escaped by
    :func:`subprocess.list2cmdline` when the command is run as a list via
    :func:`subprocess.run`.
    """
    arg_string = " ".join(args)
    if " " in executable:
        return f'"{executable}" {arg_string}'
    return f"{executable} {arg_string}"


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
        "sc",
        "create",
        service_name,
        f"binPath= {binpath}",
        "start= auto",
        f"DisplayName= {display_name}",
    ]
