"""Resolve Linux service commands that survive sudo and systemd."""

from __future__ import annotations

import getpass
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LinuxServiceRuntime:
    exec_start: str
    service_user: str
    environment: tuple[tuple[str, str], ...]
    python_executable: str
    launcher: str
    use_module_invocation: bool


def resolve_linux_service_runtime(*, argv_tail: list[str]) -> LinuxServiceRuntime:
    """Build a systemd-safe command line for the current Netorium install."""
    launcher = _resolve_launcher_path()
    arg_string = subprocess.list2cmdline(argv_tail)
    service_user = installing_user()
    python_executable = sys.executable

    if getattr(sys, "frozen", False):
        exec_start = f"{python_executable} {arg_string}"
        return LinuxServiceRuntime(
            exec_start=exec_start,
            service_user=service_user,
            environment=(),
            python_executable=python_executable,
            launcher=python_executable,
            use_module_invocation=False,
        )

    launcher_path = Path(launcher)
    if not _is_python_launcher(launcher_path):
        exec_start = f"{launcher} {arg_string}"
        return LinuxServiceRuntime(
            exec_start=exec_start,
            service_user=service_user,
            environment=(),
            python_executable=python_executable,
            launcher=launcher,
            use_module_invocation=False,
        )

    resolved_launcher = launcher_path.resolve()
    if _venv_python_launcher(resolved_launcher):
        exec_start = f"{resolved_launcher} {arg_string}"
        return LinuxServiceRuntime(
            exec_start=exec_start,
            service_user=service_user,
            environment=(),
            python_executable=python_executable,
            launcher=str(resolved_launcher),
            use_module_invocation=False,
        )

    import netorium

    pythonpath = str(Path(netorium.__file__).resolve().parent.parent)
    exec_start = f"{python_executable} -m netorium {arg_string}"
    environment = (("PYTHONPATH", pythonpath),) if pythonpath else ()
    return LinuxServiceRuntime(
        exec_start=exec_start,
        service_user=service_user,
        environment=environment,
        python_executable=python_executable,
        launcher=launcher,
        use_module_invocation=True,
    )


def build_sudo_reexec_command(*, argv_tail: list[str]) -> list[str]:
    """Build argv for ``os.execvp('sudo', ...)`` that preserves the install."""
    runtime = resolve_linux_service_runtime(argv_tail=argv_tail)
    home = user_home(runtime.service_user)
    command = ["sudo", "env", f"SUDO_USER={runtime.service_user}", f"HOME={home}"]
    for key, value in runtime.environment:
        command.append(f"{key}={value}")
    if runtime.use_module_invocation:
        command.extend([runtime.python_executable, "-m", "netorium", *argv_tail])
    else:
        command.extend([runtime.launcher, *argv_tail])
    return command


def installing_user() -> str:
    return os.environ.get("SUDO_USER") or os.environ.get("USER") or getpass.getuser()


def user_home(username: str) -> str:
    import pwd

    return pwd.getpwnam(username).pw_dir


def systemd_environment_lines(
    runtime: LinuxServiceRuntime,
    *,
    system: bool,
) -> list[str]:
    lines: list[str] = []
    if system:
        lines.append(f"Environment=HOME={user_home(runtime.service_user)}")
    for key, value in runtime.environment:
        lines.append(f"Environment={key}={value}")
    return lines


def systemd_service_account_lines(runtime: LinuxServiceRuntime) -> list[str]:
    return [
        f"User={runtime.service_user}",
        f"Group={runtime.service_user}",
    ]


def _resolve_launcher_path() -> str:
    if getattr(sys, "frozen", False):
        return sys.executable
    path = shutil_which("netorium")
    if path is not None:
        return path
    candidate = Path(sys.executable).parent / "netorium"
    if candidate.exists():
        return str(candidate)
    raise RuntimeError("Could not find the 'netorium' executable.")


def shutil_which(name: str) -> str | None:
    import shutil

    return shutil.which(name)


def _is_python_launcher(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(2) == b"#!"
    except OSError:
        return False


def _venv_python_launcher(path: Path) -> bool:
    if not _is_python_launcher(path):
        return False
    try:
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
    except OSError:
        return False
    return "/venv/" in first_line or "/.venv" in first_line
