from __future__ import annotations

import sys
from pathlib import Path


def isolated_user_env(tmp_path: Path) -> dict[str, str]:
    if sys.platform.startswith("win"):
        return {
            "APPDATA": str(tmp_path / "config"),
            "LOCALAPPDATA": str(tmp_path / "local"),
        }

    return {
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
    }


def isolated_config_dir(tmp_path: Path) -> Path:
    if sys.platform.startswith("win"):
        return tmp_path / "config" / "Netorium"
    return tmp_path / "config" / "netorium"


def isolated_config_path(tmp_path: Path) -> Path:
    return isolated_config_dir(tmp_path) / "config.toml"


def isolated_data_dir(tmp_path: Path) -> Path:
    if sys.platform.startswith("win"):
        return tmp_path / "local" / "Netorium"
    return tmp_path / "data" / "netorium"


def isolated_cache_dir(tmp_path: Path) -> Path:
    if sys.platform.startswith("win"):
        return tmp_path / "local" / "Netorium" / "Cache"
    return tmp_path / "cache" / "netorium"
