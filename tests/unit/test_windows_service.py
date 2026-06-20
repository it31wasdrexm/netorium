from __future__ import annotations

from netorium.services.windows_service import build_sc_create_command, format_sc_binpath


def test_format_sc_binpath_keeps_service_arguments_without_inner_quotes() -> None:
    executable = r"C:\Users\roman\AppData\Local\Netorium\bin\netorium.exe"
    args = ["controller", "start", "--host", "0.0.0.0", "--port", "8765"]

    assert format_sc_binpath(executable, args) == (
        r"C:\Users\roman\AppData\Local\Netorium\bin\netorium.exe "
        "controller start --host 0.0.0.0 --port 8765"
    )


def test_format_sc_binpath_escapes_executable_paths_with_spaces() -> None:
    executable = r"C:\Program Files\Netorium\netorium.exe"
    args = ["controller", "start", "--host", "0.0.0.0", "--port", "8765"]

    assert format_sc_binpath(executable, args) == (
        r"\"C:\Program Files\Netorium\netorium.exe\" "
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
        "sc",
        "create",
        "NetoriumController",
        (
            r"binPath= C:\Users\roman\AppData\Local\Netorium\bin\netorium.exe "
            "controller start --host 0.0.0.0 --port 8765"
        ),
        "start= auto",
        "DisplayName= Netorium Controller",
    ]
