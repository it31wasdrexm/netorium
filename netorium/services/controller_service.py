"""Controller background-service management.

Supports:
* Linux  – systemd user unit (~/.config/systemd/user/) or system unit (/etc/systemd/system/)
* macOS  – launchd plist (~~/Library/LaunchAgents/)
* Windows – Windows Service via sc.exe / NSSM (Non-Sucking Service Manager)

Usage
-----
    netorium controller install-service [--host 0.0.0.0] [--port 8765] [--system]
    netorium controller uninstall-service
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

from netorium.services.windows_service import build_sc_create_command


class ControllerServiceError(RuntimeError):
    pass


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def resolve_netorium_executable() -> str:
    """Return the absolute path to the Netorium CLI executable."""
    return _find_executable("netorium")


def install_controller_service(
    *,
    host: str = "0.0.0.0",
    port: int = 8765,
    system: bool = False,
) -> str:
    """Install and enable the Netorium Controller as a persistent background service.

    Returns a human-readable summary of what was done.
    """
    platform = sys.platform
    if platform.startswith("linux"):
        reexec_system_install_if_needed(host=host, port=port, system=system)
        return _install_systemd(host=host, port=port, system=system)
    if platform == "darwin":
        return _install_launchd(host=host, port=port)
    if platform.startswith("win"):
        return _install_windows_service(host=host, port=port)
    raise ControllerServiceError(
        f"Unsupported platform: {platform}. "
        "Supported platforms: Linux (systemd), macOS (launchd), Windows (sc.exe/NSSM)."
    )


def uninstall_controller_service() -> str:
    """Stop and remove the Netorium Controller background service.

    Returns a human-readable summary of what was done.
    """
    platform = sys.platform
    if platform.startswith("linux"):
        return _uninstall_systemd()
    if platform == "darwin":
        return _uninstall_launchd()
    if platform.startswith("win"):
        return _uninstall_windows_service()
    raise ControllerServiceError(
        f"Unsupported platform: {platform}."
    )


def try_provision_controller_background_service(
    *,
    host: str = "0.0.0.0",
    port: int = 8765,
) -> str | None:
    """Install and start the controller background service after initialization."""
    try:
        return install_controller_service(host=host, port=port, system=False)
    except ControllerServiceError:
        return None


def reexec_system_install_if_needed(
    *,
    host: str,
    port: int,
    system: bool,
) -> None:
    """Re-exec this process under sudo for a Linux system service install."""
    if not system or os.geteuid() == 0:
        return

    executable = resolve_netorium_executable()
    command = [
        executable,
        "controller",
        "install-service",
        "--system",
        "--host",
        host,
        "--port",
        str(port),
    ]
    try:
        os.execvp("sudo", ["sudo", *command])
    except FileNotFoundError as exc:
        raise ControllerServiceError(
            "sudo was not found. Install sudo or run the install command as root:\n"
            f"  {executable} controller install-service --system"
        ) from exc


# ──────────────────────────────────────────────────────────────────────────────
# Linux – systemd
# ──────────────────────────────────────────────────────────────────────────────

_SYSTEMD_SERVICE_NAME = "netorium-controller"
_SYSTEMD_SYSTEM_DIR = Path("/etc/systemd/system")
_SYSTEMD_USER_DIR = Path("~/.config/systemd/user").expanduser()


def _systemd_unit_content(executable: str, host: str, port: int) -> str:
    return textwrap.dedent(f"""\
        [Unit]
        Description=Netorium Controller
        After=network.target
        Wants=network-online.target

        [Service]
        Type=simple
        ExecStart={executable} controller start --host {host} --port {port}
        Restart=on-failure
        RestartSec=10
        StandardOutput=journal
        StandardError=journal

        [Install]
        WantedBy=multi-user.target
    """)


def _systemd_user_unit_content(executable: str, host: str, port: int) -> str:
    return textwrap.dedent(f"""\
        [Unit]
        Description=Netorium Controller
        After=network.target

        [Service]
        Type=simple
        ExecStart={executable} controller start --host {host} --port {port}
        Restart=on-failure
        RestartSec=10

        [Install]
        WantedBy=default.target
    """)


def _install_systemd(host: str, port: int, *, system: bool) -> str:
    executable = resolve_netorium_executable()

    # System units require root. User units are the default for non-root installs.
    is_root = os.geteuid() == 0
    if system and not is_root:
        raise ControllerServiceError(
            "System service install requires root privileges. "
            f"Run: {executable} controller install-service --system"
        )
    if is_root or system:
        unit_dir = _SYSTEMD_SYSTEM_DIR
        unit_file = unit_dir / f"{_SYSTEMD_SERVICE_NAME}.service"
        content = _systemd_unit_content(executable, host, port)
        _write_file_root(unit_file, content)
        _run(["systemctl", "daemon-reload"])
        _run(["systemctl", "enable", "--now", _SYSTEMD_SERVICE_NAME])
        return (
            f"[systemd] System service installed and started: {unit_file}\n"
            f"  Status:  systemctl status {_SYSTEMD_SERVICE_NAME}\n"
            f"  Logs:    journalctl -u {_SYSTEMD_SERVICE_NAME} -f\n"
            f"  Stop:    systemctl stop {_SYSTEMD_SERVICE_NAME}\n"
            f"  Remove:  netorium controller uninstall-service"
        )
    else:
        unit_dir = _SYSTEMD_USER_DIR
        unit_dir.mkdir(parents=True, exist_ok=True)
        unit_file = unit_dir / f"{_SYSTEMD_SERVICE_NAME}.service"
        content = _systemd_user_unit_content(executable, host, port)
        unit_file.write_text(content, encoding="utf-8")
        _run(["systemctl", "--user", "daemon-reload"])
        _run(["systemctl", "--user", "enable", "--now", _SYSTEMD_SERVICE_NAME])
        # Enable lingering so the service survives after logout
        username = os.environ.get("USER") or os.environ.get("USERNAME") or ""
        if username:
            _run_optional(["loginctl", "enable-linger", username])
        return (
            f"[systemd --user] User service installed and started: {unit_file}\n"
            f"  Status:  systemctl --user status {_SYSTEMD_SERVICE_NAME}\n"
            f"  Logs:    journalctl --user -u {_SYSTEMD_SERVICE_NAME} -f\n"
            f"  Stop:    systemctl --user stop {_SYSTEMD_SERVICE_NAME}\n"
            f"  Remove:  netorium controller uninstall-service\n"
            "\n"
            "  Tip: Install a system-wide service that survives logout with:\n"
            f"  {executable} controller install-service --system"
        )


def _uninstall_systemd() -> str:
    is_root = os.geteuid() == 0
    if is_root:
        _run_optional(["systemctl", "stop", _SYSTEMD_SERVICE_NAME])
        _run_optional(["systemctl", "disable", _SYSTEMD_SERVICE_NAME])
        unit_file = _SYSTEMD_SYSTEM_DIR / f"{_SYSTEMD_SERVICE_NAME}.service"
        if unit_file.exists():
            unit_file.unlink()
        _run_optional(["systemctl", "daemon-reload"])
        return f"[systemd] System service removed: {unit_file}"
    else:
        _run_optional(["systemctl", "--user", "stop", _SYSTEMD_SERVICE_NAME])
        _run_optional(["systemctl", "--user", "disable", _SYSTEMD_SERVICE_NAME])
        unit_file = _SYSTEMD_USER_DIR / f"{_SYSTEMD_SERVICE_NAME}.service"
        if unit_file.exists():
            unit_file.unlink()
        _run_optional(["systemctl", "--user", "daemon-reload"])
        return f"[systemd --user] User service removed: {unit_file}"


# ──────────────────────────────────────────────────────────────────────────────
# macOS – launchd
# ──────────────────────────────────────────────────────────────────────────────

_LAUNCHD_LABEL = "com.netorium.controller"
_LAUNCHD_PLIST_DIR = Path("~/Library/LaunchAgents").expanduser()


def _launchd_plist_content(executable: str, host: str, port: int) -> str:
    return textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
          "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>Label</key>
            <string>{_LAUNCHD_LABEL}</string>
            <key>ProgramArguments</key>
            <array>
                <string>{executable}</string>
                <string>controller</string>
                <string>start</string>
                <string>--host</string>
                <string>{host}</string>
                <string>--port</string>
                <string>{port}</string>
            </array>
            <key>RunAtLoad</key>
            <true/>
            <key>KeepAlive</key>
            <true/>
            <key>StandardOutPath</key>
            <string>/tmp/netorium-controller.log</string>
            <key>StandardErrorPath</key>
            <string>/tmp/netorium-controller.err</string>
        </dict>
        </plist>
    """)


def _install_launchd(host: str, port: int) -> str:
    executable = _find_executable("netorium")
    _LAUNCHD_PLIST_DIR.mkdir(parents=True, exist_ok=True)
    plist_file = _LAUNCHD_PLIST_DIR / f"{_LAUNCHD_LABEL}.plist"
    plist_file.write_text(_launchd_plist_content(executable, host, port), encoding="utf-8")
    _run(["launchctl", "load", "-w", str(plist_file)])
    return (
        f"[launchd] Launch Agent installed and started: {plist_file}\n"
        f"  Status:  launchctl list | grep netorium\n"
        f"  Logs:    tail -f /tmp/netorium-controller.log\n"
        f"  Stop:    launchctl unload {plist_file}\n"
        f"  Remove:  netorium controller uninstall-service"
    )


def _uninstall_launchd() -> str:
    plist_file = _LAUNCHD_PLIST_DIR / f"{_LAUNCHD_LABEL}.plist"
    if plist_file.exists():
        _run_optional(["launchctl", "unload", "-w", str(plist_file)])
        plist_file.unlink()
    return f"[launchd] Launch Agent removed: {plist_file}"


# ──────────────────────────────────────────────────────────────────────────────
# Windows – sc.exe or NSSM
# ──────────────────────────────────────────────────────────────────────────────

_WINDOWS_SERVICE_NAME = "NetoriumController"


def _install_windows_service(host: str, port: int) -> str:
    executable = _find_executable("netorium")

    # Prefer NSSM if available – it handles stdout/stderr better.
    nssm = shutil.which("nssm")
    if nssm:
        return _install_windows_nssm(nssm, executable, host, port)
    return _install_windows_sc(executable, host, port)


def _install_windows_nssm(nssm: str, executable: str, host: str, port: int) -> str:
    svc = _WINDOWS_SERVICE_NAME
    _run([nssm, "install", svc, executable,
          "controller", "start", "--host", host, "--port", str(port)])
    _run([nssm, "set", svc, "Start", "SERVICE_AUTO_START"])
    _run([nssm, "set", svc, "AppStdout", r"C:\ProgramData\Netorium\controller.log"])
    _run([nssm, "set", svc, "AppStderr", r"C:\ProgramData\Netorium\controller.err"])
    _run([nssm, "start", svc])
    return (
        f"[Windows/NSSM] Service '{svc}' installed and started.\n"
        f"  Status:  sc query {svc}\n"
        f"  Logs:    C:\\ProgramData\\Netorium\\controller.log\n"
        f"  Stop:    sc stop {svc}\n"
        f"  Remove:  netorium controller uninstall-service"
    )


def _install_windows_sc(executable: str, host: str, port: int) -> str:
    svc = _WINDOWS_SERVICE_NAME
    _run(
        build_sc_create_command(
            svc,
            executable,
            ["controller", "start", "--host", host, "--port", str(port)],
            display_name="Netorium Controller",
        )
    )
    _run(["sc", "start", svc])
    return (
        f"[Windows/sc.exe] Service '{svc}' installed and started.\n"
        f"  Status:  sc query {svc}\n"
        f"  Stop:    sc stop {svc}\n"
        f"  Remove:  netorium controller uninstall-service\n"
        "\n"
        "  Tip: Install NSSM (https://nssm.cc) for better log capture."
    )


def _uninstall_windows_service() -> str:
    svc = _WINDOWS_SERVICE_NAME
    nssm = shutil.which("nssm")
    if nssm:
        _run_optional([nssm, "stop", svc])
        _run_optional([nssm, "remove", svc, "confirm"])
    else:
        _run_optional(["sc", "stop", svc])
        _run_optional(["sc", "delete", svc])
    return f"[Windows] Service '{svc}' stopped and removed."


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _find_executable(name: str) -> str:
    if getattr(sys, "frozen", False):
        return sys.executable
    path = shutil.which(name)
    if path:
        return path
    # Fall back to the executable next to sys.executable (pipx / venv layout)
    candidate = Path(sys.executable).parent / name
    if candidate.exists():
        return str(candidate)
    candidate_exe = Path(sys.executable).parent / f"{name}.exe"
    if candidate_exe.exists():
        return str(candidate_exe)
    raise ControllerServiceError(
        f"Could not find the '{name}' executable. "
        "Make sure Netorium is installed and on your PATH."
    )


def _run(cmd: list[str]) -> None:
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise ControllerServiceError(
            f"Command not found: {cmd[0]}. Is it installed and on PATH?"
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise ControllerServiceError(
            f"Command failed: {' '.join(cmd)}\n{stderr}"
        ) from exc


def _run_optional(cmd: list[str]) -> None:
    """Run a command, ignoring errors (used for cleanup steps)."""
    try:
        subprocess.run(cmd, check=False, capture_output=True, text=True)
    except FileNotFoundError:
        pass


def _write_file_root(path: Path, content: str) -> None:
    """Write a file, raising ControllerServiceError if it fails (e.g. not root)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except PermissionError as exc:
        raise ControllerServiceError(
            f"Permission denied writing {path}. Run with sudo to install a system service."
        ) from exc
