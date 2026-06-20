"""Helpers for creating Windows services with sc.exe."""

from __future__ import annotations

from collections.abc import Sequence


def format_sc_binpath(executable: str, args: Sequence[str]) -> str:
    """Format the binPath value for ``sc.exe create``.

    ``sc.exe`` treats the first quoted segment as the full binPath when the
    executable path itself is quoted. The entire service command line must stay
    in one binPath value, with escaped inner quotes when the executable path
    contains spaces.
    """
    arg_string = " ".join(args)
    if " " in executable:
        return f'\\"{executable}\\" {arg_string}'
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
