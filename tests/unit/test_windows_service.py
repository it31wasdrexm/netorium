from __future__ import annotations

import pytest

import netorium.services.controller_service as controller_service
from netorium.services.windows_background import (
    build_firewall_add_command,
    build_schtasks_create_command,
    build_schtasks_run_command,
)
from netorium.services.windows_service import (
    build_sc_config_command,
    build_sc_create_command,
    build_sc_start_command,
    build_sc_stop_command,
    format_sc_binpath,
    service_output_indicates_exists,
)


def test_format_sc_binpath_quotes_executable_without_spaces() -> None:
    executable = r"C:\Users\roman\AppData\Local\Netorium\bin\netorium.exe"
    args = ["controller", "start", "--host", "0.0.0.0", "--port", "8765"]

    assert format_sc_binpath(executable, args) == (
        r'"C:\Users\roman\AppData\Local\Netorium\bin\netorium.exe" '
        "controller start --host 0.0.0.0 --port 8765"
    )


def test_format_sc_binpath_escapes_executable_paths_with_spaces() -> None:
    executable = r"C:\Program Files\Netorium\netorium.exe"
    args = ["controller", "start", "--host", "0.0.0.0", "--port", "8765"]

    assert format_sc_binpath(executable, args) == (
        r'"C:\Program Files\Netorium\netorium.exe" '
        "controller start --host 0.0.0.0 --port 8765"
    )


def test_build_sc_create_command_uses_single_binpath_argument() -> None:
    command = build_sc_create_command(
        "NetoriumController",
        r"C:\Users\roman\AppData\Local\Netorium\bin\netorium.exe",
        ["controller", "start", "--host", "0.0.0.0", "--port", "8765"],
        display_name="Netorium Controller",
    )

    assert command == [
        "sc.exe",
        "create",
        "NetoriumController",
        "binPath=",
        (
            r'"C:\Users\roman\AppData\Local\Netorium\bin\netorium.exe" '
            "controller start --host 0.0.0.0 --port 8765"
        ),
        "start=",
        "auto",
        "DisplayName=",
        "Netorium Controller",
    ]


def test_build_sc_config_command_uses_single_binpath_argument() -> None:
    command = build_sc_config_command(
        "NetoriumController",
        r"C:\Users\roman\AppData\Local\Netorium\bin\netorium.exe",
        ["controller", "start", "--host", "0.0.0.0", "--port", "8765"],
        display_name="Netorium Controller",
    )

    assert command == [
        "sc.exe",
        "config",
        "NetoriumController",
        "binPath=",
        (
            r'"C:\Users\roman\AppData\Local\Netorium\bin\netorium.exe" '
            "controller start --host 0.0.0.0 --port 8765"
        ),
        "start=",
        "auto",
        "DisplayName=",
        "Netorium Controller",
    ]


def test_build_schtasks_create_command_includes_quiet_controller_start() -> None:
    command = build_schtasks_create_command(
        "NetoriumController",
        r"C:\Users\roman\AppData\Local\Netorium\bin\netorium.exe",
        ["controller", "start", "--host", "0.0.0.0", "--port", "8765", "--quiet"],
    )

    assert command[:4] == ["schtasks", "/Create", "/TN", "NetoriumController"]
    assert "--quiet" in command[5]
    assert command[-3:] == ["/RL", "HIGHEST", "/F"]


def test_build_firewall_add_command_uses_controller_port() -> None:
    command = build_firewall_add_command(8765)
    assert command[-1] == "localport=8765"
    assert 'name="Netorium Controller"' in command


def test_service_output_indicates_exists() -> None:
    assert service_output_indicates_exists("CreateService FAILED 1073: The specified service already exists.")
    assert service_output_indicates_exists("уже существует")
    assert not service_output_indicates_exists("Access is denied.")


def test_windows_sc_install_creates_starts_and_opens_firewall(monkeypatch) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(controller_service, "_run", lambda cmd: commands.append(cmd))
    monkeypatch.setattr(controller_service, "_run_optional", lambda cmd: commands.append(cmd))

    result = controller_service._install_windows_sc(
        executable=r"C:\Users\roman\AppData\Local\Netorium\bin\netorium.exe",
        args=["controller", "start", "--host", "0.0.0.0", "--port", "8765", "--quiet"],
        port=8765,
        service_name="NetoriumController",
        display_name="Netorium Controller",
    )

    assert commands[0][:3] == ["sc.exe", "create", "NetoriumController"]
    assert commands[1] == build_sc_stop_command("NetoriumController")
    assert commands[2] == build_firewall_add_command(8765)
    assert commands[3] == build_sc_start_command("NetoriumController")
    assert "sc.exe" in result


def test_windows_sc_install_updates_existing_service(monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run(cmd: list[str]) -> None:
        commands.append(cmd)
        if cmd[:3] == ["sc.exe", "create", "NetoriumController"]:
            raise controller_service.ControllerServiceError(
                "Command failed: sc.exe create NetoriumController\n"
                "CreateService FAILED 1073: The specified service already exists."
            )

    monkeypatch.setattr(controller_service, "_run", fake_run)
    monkeypatch.setattr(controller_service, "_run_optional", lambda cmd: commands.append(cmd))

    controller_service._install_windows_sc(
        executable=r"C:\Users\roman\AppData\Local\Netorium\bin\netorium.exe",
        args=["controller", "start", "--host", "0.0.0.0", "--port", "8765", "--quiet"],
        port=8765,
        service_name="NetoriumController",
        display_name="Netorium Controller",
    )

    assert commands[0][:3] == ["sc.exe", "create", "NetoriumController"]
    assert commands[1][:3] == ["sc.exe", "config", "NetoriumController"]


def test_install_controller_service_requires_init_on_windows(monkeypatch) -> None:
    monkeypatch.setattr(controller_service.sys, "platform", "win32")
    monkeypatch.setattr(controller_service, "reexec_windows_admin_if_needed", lambda _args: None)

    class FakeSettings:
        class app:
            database_path = r"C:\Users\roman\AppData\Local\Netorium\netorium.db"

    class FakeStatus:
        initialized = False

    monkeypatch.setattr(controller_service, "load_settings", lambda: FakeSettings())
    monkeypatch.setattr(controller_service, "get_controller_status", lambda _path: FakeStatus())

    with pytest.raises(controller_service.ControllerServiceError, match="not initialized"):
        controller_service.install_controller_service()


def test_windows_task_install_creates_runs_and_opens_firewall(monkeypatch) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(
        controller_service,
        "_remove_windows_task",
        lambda _task: commands.append(["delete-task"]),
    )
    monkeypatch.setattr(controller_service, "_run", lambda cmd: commands.append(cmd))
    monkeypatch.setattr(controller_service, "_run_optional", lambda cmd: commands.append(cmd))

    result = controller_service._install_windows_task(
        r"C:\Users\roman\AppData\Local\Netorium\bin\netorium.exe",
        "0.0.0.0",
        8765,
    )

    assert commands[0] == ["delete-task"]
    assert commands[1][:3] == ["schtasks", "/Create", "/TN"]
    assert commands[2] == build_firewall_add_command(8765)
    assert commands[3] == build_schtasks_run_command("NetoriumController")
    assert "scheduled task" in result
