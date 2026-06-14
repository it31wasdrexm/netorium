from pathlib import Path

import pytest

from netorium.core.settings import CONFIG_TEMPLATE
from netorium.services.uninstaller import (
    UninstallError,
    build_uninstall_plan,
    execute_uninstall_plan,
)


def test_uninstall_plan_uses_pipx_when_available() -> None:
    plan = build_uninstall_plan(
        executable="/usr/bin/python",
        which=lambda command: "/usr/bin/pipx" if command == "pipx" else None,
    )

    assert plan.package_manager == "pipx"
    assert plan.package_command == ("pipx", "uninstall", "netorium-cli")
    assert plan.path_targets == ()


def test_uninstall_plan_falls_back_to_pip_without_pipx() -> None:
    plan = build_uninstall_plan(
        executable="/usr/bin/python",
        which=lambda _command: None,
    )

    assert plan.package_manager == "pip"
    assert plan.package_command == (
        "/usr/bin/python",
        "-m",
        "pip",
        "uninstall",
        "-y",
        "netorium-cli",
    )


def test_uninstall_plan_rejects_unknown_package_manager() -> None:
    with pytest.raises(UninstallError, match="Package manager must be"):
        build_uninstall_plan(package_manager="brew")


def test_execute_uninstall_plan_removes_requested_data_paths(tmp_path: Path) -> None:
    env = _write_config_and_data(tmp_path)
    plan = build_uninstall_plan(
        remove_data=True,
        package_manager="none",
        env=env,
        platform_name="linux",
    )

    result = execute_uninstall_plan(plan)

    assert result.package_command_ran is False
    assert (tmp_path / "config" / "netorium").exists() is False
    assert (tmp_path / "data" / "netorium").exists() is False
    assert (tmp_path / "cache" / "netorium").exists() is False


def _write_config_and_data(tmp_path: Path) -> dict[str, str]:
    config_dir = tmp_path / "config" / "netorium"
    data_dir = tmp_path / "data" / "netorium"
    cache_dir = tmp_path / "cache" / "netorium"
    config_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    cache_dir.mkdir(parents=True)
    database_path = data_dir / "netorium.db"
    config_text = CONFIG_TEMPLATE.replace(
        'database_path = "~/.local/share/netorium/netorium.db"',
        f'database_path = "{database_path.as_posix()}"',
    )
    (config_dir / "config.toml").write_text(config_text, encoding="utf-8")
    database_path.write_text("database", encoding="utf-8")
    (cache_dir / "cache.txt").write_text("cache", encoding="utf-8")
    return {
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
    }
