import os
from pathlib import Path

import pytest

from netorium.core.settings import CONFIG_TEMPLATE
import netorium.services.uninstaller as uninstaller_service
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
    assert plan.package_command_detached is True
    assert plan.package_command == ("sh", "-c", "sleep 3; pipx uninstall netorium-cli")
    assert plan.path_targets == ()


def test_uninstall_plan_falls_back_to_pip_without_pipx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("netorium.services.uninstaller._is_externally_managed_python", lambda: True)
    plan = build_uninstall_plan(
        executable="/usr/bin/python",
        which=lambda _command: None,
    )

    assert plan.package_manager == "pip"
    assert plan.package_command_detached is True
    assert plan.package_command == (
        "sh",
        "-c",
        "sleep 3; /usr/bin/python -m pip uninstall -y netorium-cli --break-system-packages",
    )


def test_uninstall_plan_includes_launcher_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("netorium.services.uninstaller._is_externally_managed_python", lambda: False)
    plan = build_uninstall_plan(
        executable="/usr/bin/python",
        which=lambda command: "/home/user/.local/bin/netorium" if command == "netorium" else None,
    )

    assert plan.package_command is not None
    assert "rm -f /home/user/.local/bin/netorium" in plan.package_command[2]


def test_uninstall_plan_uses_pip_directly_when_frozen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("netorium.services.uninstaller.sys.frozen", True, raising=False)
    monkeypatch.setattr("netorium.services.uninstaller._is_externally_managed_python", lambda: True)
    plan = build_uninstall_plan(
        executable="/usr/bin/python",
        which=lambda command: "/usr/bin/pip" if command == "pip" else None,
        package_manager="pip",
    )

    assert plan.package_manager == "pip"
    assert plan.package_command_detached is True
    assert plan.package_command == (
        "sh",
        "-c",
        "sleep 3; pip uninstall -y netorium-cli --break-system-packages",
    )


def test_uninstall_plan_handles_windows_standalone_when_frozen(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("netorium.services.uninstaller.sys.frozen", True, raising=False)
    env = {
        "APPDATA": r"C:\Users\roman\AppData\Roaming",
        "LOCALAPPDATA": r"C:\Users\roman\AppData\Local",
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
    assert "timeout /t 5" in plan.package_command[3]
    assert "taskkill /IM netorium.exe /F" in plan.package_command[3]
    assert "Netorium" in plan.package_command[3]
    assert r"C:\Users\roman\AppData\Local\Netorium\bin\netorium.exe\NUL" in plan.package_command[3]
    assert r"C:\Users\roman\AppData\Local\Netorium\bin\netorium.exe\\" not in plan.package_command[3]
    assert "Local/Netorium" not in plan.package_command[3]
    assert "bin/netorium.exe" not in plan.package_command[3]
    assert "$entry='C:" in plan.package_command[3]
    assert "$entry=\"C:" not in plan.package_command[3]
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


def test_windows_cleanup_detached_launches_script_without_start_parser(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    launched: list[tuple[str, ...]] = []

    class FakePopen:
        def __init__(self, args: tuple[str, ...], **_kwargs: object) -> None:
            launched.append(args)

    monkeypatch.setattr(uninstaller_service.sys, "platform", "win32")
    monkeypatch.setattr(uninstaller_service.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(uninstaller_service.subprocess, "Popen", FakePopen)

    exit_code = uninstaller_service._run_windows_cleanup_detached(
        ("cmd.exe", "/d", "/c", "echo cleanup")
    )

    assert exit_code == 0
    script_path = tmp_path / f"netorium-uninstall-{os.getpid()}.cmd"
    assert launched == [("cmd.exe", "/d", "/c", str(script_path))]
    assert "start" not in launched[0]
    script = script_path.read_text(encoding="utf-8")
    assert f"Wait-Process -Id {os.getpid()}" in script
    assert "tasklist /FI" not in script


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
