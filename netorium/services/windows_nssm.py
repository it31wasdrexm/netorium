"""Locate a bundled or installed NSSM executable on Windows."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


def resolve_nssm_executable() -> str | None:
    """Return the path to NSSM when available beside Netorium or on PATH."""
    if not sys.platform.startswith("win"):
        return None

    for candidate in _nssm_candidates():
        if candidate.is_file():
            return str(candidate)

    located = shutil.which("nssm")
    if located:
        return located

    located_exe = shutil.which("nssm.exe")
    if located_exe:
        return located_exe

    return None


def _nssm_candidates() -> tuple[Path, ...]:
    candidates: list[Path] = []

    if getattr(sys, "frozen", False):
        install_dir = Path(sys.executable).resolve().parent
        candidates.extend(
            [
                install_dir / "nssm.exe",
                install_dir / "nssm" / "nssm.exe",
                install_dir / "nssm" / "win64" / "nssm.exe",
            ]
        )

    package_root = Path(__file__).resolve().parents[1]
    candidates.extend(
        [
            package_root / "vendor" / "nssm" / "win64" / "nssm.exe",
            package_root / "vendor" / "nssm" / "nssm.exe",
        ]
    )

    return tuple(candidates)
