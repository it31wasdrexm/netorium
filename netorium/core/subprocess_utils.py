"""Safe subprocess helpers for cross-platform CLI commands."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence

SUBPROCESS_TEXT_KWARGS = {"text": True, "encoding": "utf-8", "errors": "replace"}


def run_text(
    cmd: Sequence[str],
    *,
    check: bool = True,
    capture_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(cmd),
        check=check,
        capture_output=capture_output,
        **SUBPROCESS_TEXT_KWARGS,
    )


def run_text_optional(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(cmd),
        check=False,
        capture_output=True,
        **SUBPROCESS_TEXT_KWARGS,
    )
