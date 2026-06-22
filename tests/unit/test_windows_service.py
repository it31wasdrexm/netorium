from __future__ import annotations

import netorium.services.controller_service as controller_service
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


def test_windows_sc_install_updates_existing_service(monkeypatch) -> None:
    commands: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(controller_service, "_windows_service_exists", lambda _svc: True)
    monkeypatch.setattr(
        controller_service,
        "_run_optional",
        lambda cmd: commands.append(("optional", cmd)),
    )
    monkeypatch.setattr(controller_service, "_run", lambda cmd: commands.append(("run", cmd)))

    result = controller_service._install_windows_sc(
        r"C:\Users\roman\AppData\Local\Netorium\bin\netorium.exe",
        "0.0.0.0",
        8765,
    )

    assert commands[0] == ("optional", ["sc.exe", "stop", "NetoriumController"])
    assert commands[1][0] == "run"
    assert commands[1][1][:3] == ["sc.exe", "config", "NetoriumController"]
    assert commands[2] == ("run", ["sc.exe", "start", "NetoriumController"])
    assert "installed and started with sc.exe" in result


def test_windows_sc_install_creates_missing_service(monkeypatch) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(controller_service, "_windows_service_exists", lambda _svc: False)
    monkeypatch.setattr(controller_service, "_run", lambda cmd: commands.append(cmd))

    controller_service._install_windows_sc(
        r"C:\Users\roman\AppData\Local\Netorium\bin\netorium.exe",
        "0.0.0.0",
        8765,
    )

    assert commands[0][:3] == ["sc.exe", "create", "NetoriumController"]
    assert commands[1] == ["sc.exe", "start", "NetoriumController"]
