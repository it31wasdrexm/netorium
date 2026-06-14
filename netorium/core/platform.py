from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Mapping


def user_config_path(
    platform_name: str | None = None,
    env: Mapping[str, str] | None = None,
) -> Path:
    active_platform = platform_name or sys.platform
    active_env = os.environ if env is None else env

    if active_platform.startswith("win"):
        appdata = active_env.get("APPDATA")
        base_path = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base_path / "Netorium" / "config.toml"

    xdg_config_home = active_env.get("XDG_CONFIG_HOME")
    home = active_env.get("HOME")
    if xdg_config_home:
        base_path = Path(xdg_config_home)
    elif home:
        base_path = Path(home) / ".config"
    else:
        base_path = Path.home() / ".config"
    return base_path / "netorium" / "config.toml"
