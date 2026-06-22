from __future__ import annotations

from pathlib import Path

import pytest

import netorium.services.linux_service_runtime as runtime_module
from netorium.services.linux_service_runtime import (
    build_sudo_reexec_command,
    resolve_linux_service_runtime,
)


def test_resolve_runtime_uses_module_invocation_for_user_pip_launcher(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    launcher = tmp_path / "netorium"
    launcher.write_text("#!/usr/bin/python3\n", encoding="utf-8")
    monkeypatch.setattr(runtime_module, "_resolve_launcher_path", lambda: str(launcher))
    monkeypatch.setattr(runtime_module, "installing_user", lambda: "alice")
    monkeypatch.setattr(runtime_module.sys, "executable", "/usr/bin/python3")

    runtime = resolve_linux_service_runtime(
        argv_tail=["controller", "start", "--host", "0.0.0.0", "--port", "8765", "--quiet"],
    )

    assert runtime.use_module_invocation is True
    assert runtime.exec_start == (
        "/usr/bin/python3 -m netorium controller start --host 0.0.0.0 --port 8765 --quiet"
    )
    assert runtime.environment[0][0] == "PYTHONPATH"
    assert runtime.service_user == "alice"


def test_resolve_runtime_uses_venv_launcher(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    venv_launcher = tmp_path / "venv" / "bin" / "netorium"
    venv_launcher.parent.mkdir(parents=True)
    venv_launcher.write_text("#!/home/alice/.local/share/netorium/venv/bin/python\n", encoding="utf-8")
    launcher = tmp_path / "bin" / "netorium"
    launcher.parent.mkdir(parents=True)
    launcher.symlink_to(venv_launcher)
    monkeypatch.setattr(runtime_module, "_resolve_launcher_path", lambda: str(launcher))

    runtime = resolve_linux_service_runtime(argv_tail=["agent", "run-loop"])

    assert runtime.use_module_invocation is False
    assert runtime.exec_start == f"{venv_launcher} agent run-loop"


def test_build_sudo_reexec_command_preserves_pythonpath(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    launcher = tmp_path / "netorium"
    launcher.write_text("#!/usr/bin/python3\n", encoding="utf-8")
    monkeypatch.setattr(runtime_module, "_resolve_launcher_path", lambda: str(launcher))
    monkeypatch.setattr(runtime_module, "installing_user", lambda: "alice")
    monkeypatch.setattr(runtime_module, "user_home", lambda _user: "/home/alice")
    monkeypatch.setattr(runtime_module.sys, "executable", "/usr/bin/python3")

    command = build_sudo_reexec_command(
        argv_tail=["controller", "install-service", "--system", "--host", "0.0.0.0", "--port", "8765"],
    )

    assert command[0:2] == ["sudo", "env"]
    assert "SUDO_USER=alice" in command
    assert "HOME=/home/alice" in command
    assert any(item.startswith("PYTHONPATH=") for item in command)
    assert command[command.index("/usr/bin/python3") :] == [
        "/usr/bin/python3",
        "-m",
        "netorium",
        "controller",
        "install-service",
        "--system",
        "--host",
        "0.0.0.0",
        "--port",
        "8765",
    ]
