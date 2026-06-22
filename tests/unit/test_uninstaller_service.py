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


def test_uninstall_plan_uses_pip_directly_when_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("netorium.services.uninstaller.sys.frozen", True, raising=False)
    plan = build_uninstall_plan(
        executable="/usr/bin/python",
        which=lambda command: "/usr/bin/pip" if command == "pip" else None,
        package_manager="pip",
    )

    assert plan.package_manager == "pip"
    assert plan.package_command == (
        "pip",
        "uninstall",
        "-y",
        "netorium-cli",
    )


def test_uninstall_plan_handles_windows_standalone_when_frozen(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("netorium.services.uninstaller.sys.frozen", True, raising=False)
    env = {
        "APPDATA": str(tmp_path / "Roaming"),
        "LOCALAPPDATA": str(tmp_path / "Local"),
    }

    plan = build_uninstall_plan(
        remove_data=True,
        executable=r"C:\Users\roman\AppData\Local\Netorium\bin\netorium.exe",
        which=lambda _command: None,
        env=env,
        platform_name="win32",
    )

    assert plan.package_manager == "standalone"
    assert plan.package_command_detached is True
    assert plan.path_targets == ()
    assert plan.package_command is not None
    assert plan.package_command[:3] == ("cmd.exe", "/d", "/c")
    assert "timeout /t 3" in plan.package_command[3]
    assert "Netorium" in plan.package_command[3]
    assert [target.label for target in plan.deferred_path_targets] == [
        "Configuration directory",
        "Application data directory",
        "Cache directory",
        "Standalone executable",
    ]


def test_uninstall_plan_handles_windows_local_venv_install(tmp_path: Path) -> None:
    env = {
        "APPDATA": str(tmp_path / "Roaming"),
        "LOCALAPPDATA": str(tmp_path / "Local"),
    }
    executable = tmp_path / "Local" / "Netorium" / "venv" / "Scripts" / "python.exe"

    plan = build_uninstall_plan(
        executable=str(executable),
        which=lambda _command: None,
        env=env,
        platform_name="win32",
    )

    assert plan.package_manager == "standalone"
    assert plan.package_command_detached is True
    assert plan.path_targets == ()
    assert plan.package_command is not None
    assert plan.package_command[:3] == ("cmd.exe", "/d", "/c")
    assert [target.label for target in plan.deferred_path_targets] == [
        "Windows virtual environment",
        "Windows launcher directory",
    ]
    assert [target.path for target in plan.deferred_path_targets] == [
        tmp_path / "Local" / "Netorium" / "venv",
        tmp_path / "Local" / "Netorium" / "bin",
    ]


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
    assert result.deferred_paths == ()


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
