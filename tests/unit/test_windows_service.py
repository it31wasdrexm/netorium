from __future__ import annotations

import netorium.services.controller_service as controller_service
from netorium.services.windows_background import (
    build_firewall_add_command,
    build_schtasks_create_command,
    build_schtasks_run_command,
)
from netorium.services.windows_service import (
    build_sc_config_command,
    build_sc_create_command,
    format_sc_binpath,
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
    assert build_firewall_add_command(8765)[-1] == "localport=8765"


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
