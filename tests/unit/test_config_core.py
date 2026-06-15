from pathlib import Path

import pytest

from netorium.core.platform import user_cache_dir, user_config_path, user_data_dir
from netorium.core.settings import (
    ConfigError,
    init_config,
    load_settings,
    mask_secrets,
    masked_config_text,
)


def test_user_config_path_uses_xdg_config_home() -> None:
    path = user_config_path(
        platform_name="linux",
        env={"XDG_CONFIG_HOME": "/tmp/netorium-config"},
    )

    assert path == Path("/tmp/netorium-config/netorium/config.toml")


def test_user_config_path_uses_linux_home_fallback() -> None:
    path = user_config_path(
        platform_name="darwin",
        env={"HOME": "/home/admin"},
    )

    assert path == Path("/home/admin/.config/netorium/config.toml")


def test_user_config_path_uses_windows_appdata() -> None:
    path = user_config_path(
        platform_name="win32",
        env={"APPDATA": "C:/Users/Admin/AppData/Roaming"},
    )

    assert str(path) == "C:/Users/Admin/AppData/Roaming/Netorium/config.toml"


def test_user_data_dir_uses_xdg_data_home() -> None:
    path = user_data_dir(
        platform_name="linux",
        env={"XDG_DATA_HOME": "/tmp/netorium-data"},
    )

    assert path == Path("/tmp/netorium-data/netorium")


def test_user_cache_dir_uses_xdg_cache_home() -> None:
    path = user_cache_dir(
        platform_name="linux",
        env={"XDG_CACHE_HOME": "/tmp/netorium-cache"},
    )

    assert path == Path("/tmp/netorium-cache/netorium")


def test_init_config_writes_valid_default_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"

    created_path = init_config(config_path)
    settings = load_settings(created_path)

    assert created_path == config_path
    assert settings.app.timezone == "Asia/Almaty"
    assert settings.updates.repo == "it31wasdrexm/netorium"
    assert settings.updates.check_on_start is True


def test_init_config_refuses_existing_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    init_config(config_path)

    with pytest.raises(ConfigError, match="Config already exists"):
        init_config(config_path)


def test_mask_secrets_masks_nested_sensitive_values() -> None:
    masked = mask_secrets(
        {
            "telegram": {"bot_token": "secret-token", "chat_id": "123"},
            "active_directory": {"bind_password": "secret-password"},
            "app": {"timezone": "Asia/Almaty"},
        }
    )

    assert masked["telegram"]["bot_token"] == "********"
    assert masked["telegram"]["chat_id"] == "********"
    assert masked["active_directory"]["bind_password"] == "********"
    assert masked["app"]["timezone"] == "Asia/Almaty"


def test_masked_config_text_does_not_expose_default_secrets(tmp_path: Path) -> None:
    config_path = init_config(tmp_path / "config.toml")

    text = masked_config_text(config_path)

    assert "passhash = \"********\"" in text
    assert "bind_password = \"********\"" in text
    assert "bot_token = \"********\"" in text
    assert "CHANGE_ME" not in text


def test_load_settings_reports_friendly_validation_error(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[app]\nlog_level = \"INFO\"\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="Invalid config: app.database_path"):
        load_settings(config_path)
