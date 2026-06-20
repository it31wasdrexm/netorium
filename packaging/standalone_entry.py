"""PyInstaller entry point for the unified Netorium standalone binary.

The same executable serves both the controller CLI and the endpoint agent:
  netorium controller init
  netorium agent enroll --controller URL --token TOKEN

Legacy invocations are also supported when the binary is named or symlinked as
``netorium-agent`` (``netorium-agent enroll ...``).
"""

from __future__ import annotations

import sys
from pathlib import Path


def _is_legacy_agent_invocation() -> bool:
    executable_name = Path(sys.argv[0]).name.lower()
    if executable_name.startswith("netorium-agent"):
        return True
    if len(sys.argv) > 1 and sys.argv[1] == "run-loop":
        return True
    return False


if __name__ == "__main__":
    if _is_legacy_agent_invocation():
        from netorium.cli.agent import app as cli_app
    else:
        from netorium.cli.app import app as cli_app

    cli_app()
