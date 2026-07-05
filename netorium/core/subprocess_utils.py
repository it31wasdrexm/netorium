"""Safe subprocess helpers for cross-platform CLI commands."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence

SUBPROCESS_TEXT_KWARGS = {"text": True, "encoding": "utf-8", "errors": "replace"}


def _windows_creationflags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run_text(
    cmd: Sequence[str],
    *,
    check: bool = True,
    capture_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    kwargs: dict[str, object] = {
        "check": check,
        "capture_output": capture_output,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = _windows_creationflags()
    return subprocess.run(list(cmd), **kwargs)


def run_text_optional(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
    kwargs: dict[str, object] = {
        "check": False,
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = _windows_creationflags()
    return subprocess.run(list(cmd), **kwargs)
