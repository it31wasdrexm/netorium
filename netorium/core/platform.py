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


def user_data_dir(
    platform_name: str | None = None,
    env: Mapping[str, str] | None = None,
) -> Path:
    active_platform = platform_name or sys.platform
    active_env = os.environ if env is None else env

    if active_platform.startswith("win"):
        local_appdata = active_env.get("LOCALAPPDATA")
        appdata = active_env.get("APPDATA")
        base_path = (
            Path(local_appdata)
            if local_appdata
            else Path(appdata)
            if appdata
            else Path.home() / "AppData" / "Local"
        )
        return base_path / "Netorium"

    if active_platform == "darwin":
        home = active_env.get("HOME")
        base_path = Path(home) if home else Path.home()
        return base_path / "Library" / "Application Support" / "netorium"

    xdg_data_home = active_env.get("XDG_DATA_HOME")
    home = active_env.get("HOME")
    if xdg_data_home:
        base_path = Path(xdg_data_home)
    elif home:
        base_path = Path(home) / ".local" / "share"
    else:
        base_path = Path.home() / ".local" / "share"
    return base_path / "netorium"


def user_cache_dir(
    platform_name: str | None = None,
    env: Mapping[str, str] | None = None,
) -> Path:
    active_platform = platform_name or sys.platform
    active_env = os.environ if env is None else env

    if active_platform.startswith("win"):
        local_appdata = active_env.get("LOCALAPPDATA")
        base_path = Path(local_appdata) if local_appdata else Path.home() / "AppData" / "Local"
        return base_path / "Netorium" / "Cache"

    if active_platform == "darwin":
        home = active_env.get("HOME")
        base_path = Path(home) if home else Path.home()
        return base_path / "Library" / "Caches" / "netorium"

    xdg_cache_home = active_env.get("XDG_CACHE_HOME")
    home = active_env.get("HOME")
    if xdg_cache_home:
        base_path = Path(xdg_cache_home)
    elif home:
        base_path = Path(home) / ".cache"
    else:
        base_path = Path.home() / ".cache"
    return base_path / "netorium"
