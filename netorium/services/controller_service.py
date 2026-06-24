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

import ctypes
import os
import socket
import time
import urllib.error
import urllib.request
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

from netorium.core.settings import ConfigError, load_settings
from netorium.core.subprocess_utils import run_text, run_text_optional
from netorium.services.controller import get_controller_status
from netorium.services.linux_service_runtime import (
    LinuxServiceRuntime,
    build_sudo_reexec_command,
    resolve_linux_service_runtime,
    systemd_environment_lines,
    systemd_service_account_lines,
)
from netorium.services.windows_background import (
    build_firewall_add_command,
    build_firewall_add_program_command,
    build_firewall_delete_command,
    build_firewall_delete_program_command,
    build_schtasks_create_command,
    build_schtasks_delete_command,
    build_schtasks_run_command,
)
from netorium.services.windows_nssm import resolve_nssm_executable
from netorium.services.windows_service import (
    build_sc_config_command,
    build_sc_create_command,
    build_sc_delete_command,
    build_sc_start_command,
    build_sc_stop_command,
    service_output_indicates_exists,
)


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
        _ensure_controller_initialized()
        reexec_windows_admin_if_needed(["controller", "install-service", "--host", host, "--port", str(port)])
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
        reexec_windows_admin_if_needed(["controller", "uninstall-service"])
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
    try:
        os.execvp("sudo", build_sudo_reexec_command(
            argv_tail=[
                "controller",
                "install-service",
                "--system",
                "--host",
                host,
                "--port",
                str(port),
            ],
        ))
    except FileNotFoundError as exc:
        raise ControllerServiceError(
            "sudo was not found. Install sudo or run the install command as root:\n"
            f"  {executable} controller install-service --system"
        ) from exc


def _is_windows_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except AttributeError:
        return False


def reexec_windows_admin_if_needed(args: list[str]) -> None:
    """Re-exec this process with administrator privileges on Windows."""
    if "PYTEST_CURRENT_TEST" in os.environ:
        return
    if _is_windows_admin():
        return
    executable = resolve_netorium_executable()
    # Create the command string for the argument
    args_str = " ".join(f'"{a}"' if " " in a else a for a in args)
    try:
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, args_str, None, 1)
        if result <= 32:
            raise ControllerServiceError("Failed to request Administrator privileges.")
        # Successfully elevated, exit current non-elevated process
        sys.exit(0)
    except Exception as exc:
        raise ControllerServiceError(
            "Administrator privileges are required to manage services on Windows.\n"
            "Please run PowerShell or Windows Terminal as Administrator and try again."
        ) from exc


def uninstall_services_silently() -> None:
    """Silently stop and delete all netorium services (controller and agent).

    Called during ``netorium uninstall``.  Every operation is best-effort:
    failures are silently ignored so the uninstall flow is never interrupted.
    """
    if "PYTEST_CURRENT_TEST" in os.environ:
        return
    try:
        if sys.platform.startswith("win"):
            nssm = resolve_nssm_executable()
            for svc in ("NetoriumController", "NetoriumAgent"):
                if nssm:
                    # NSSM provides a cleaner removal than sc.exe for NSSM-managed services
                    _run_optional([nssm, "stop", svc])
                    _run_optional([nssm, "remove", svc, "confirm"])
                # Also attempt sc.exe removal (no-op if service doesn't exist)
                _run_optional(["sc.exe", "stop", svc])
                _run_optional(["sc.exe", "delete", svc])
            for task in ("NetoriumController", "NetoriumAgent"):
                _run_optional(build_schtasks_delete_command(task))
            # Remove controller firewall rules left behind by install-service
            _run_optional(build_firewall_delete_command())
            _run_optional(build_firewall_delete_program_command())
        elif sys.platform.startswith("linux"):
            _run_optional(["sudo", "systemctl", "stop", "netorium-controller"])
            _run_optional(["sudo", "systemctl", "disable", "netorium-controller"])
            _run_optional(["systemctl", "--user", "stop", "netorium-controller"])
            _run_optional(["systemctl", "--user", "disable", "netorium-controller"])

            _run_optional(["sudo", "systemctl", "stop", "netorium-agent"])
            _run_optional(["sudo", "systemctl", "disable", "netorium-agent"])
            _run_optional(["systemctl", "--user", "stop", "netorium-agent"])
            _run_optional(["systemctl", "--user", "disable", "netorium-agent"])
        elif sys.platform == "darwin":
            # Best effort
            pass
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Linux – systemd
# ──────────────────────────────────────────────────────────────────────────────

_SYSTEMD_SERVICE_NAME = "netorium-controller"
_SYSTEMD_SYSTEM_DIR = Path("/etc/systemd/system")


def _systemd_user_dir() -> Path:
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home).expanduser() / "systemd" / "user"
    return Path("~/.config/systemd/user").expanduser()


def _systemd_unit_content(runtime: LinuxServiceRuntime, *, system: bool) -> str:
    service_lines = systemd_service_account_lines(runtime) if system else []
    environment_lines = systemd_environment_lines(runtime, system=system)
    indented_service = "".join(f"        {line}\n" for line in service_lines)
    indented_environment = "".join(f"        {line}\n" for line in environment_lines)
    return textwrap.dedent(f"""\
        [Unit]
        Description=Netorium Controller
        After=network.target
        Wants=network-online.target

        [Service]
        Type=simple
{indented_service}{indented_environment}        ExecStart={runtime.exec_start}
        Restart=on-failure
        RestartSec=10
        StandardOutput=journal
        StandardError=journal

        [Install]
        WantedBy=multi-user.target
    """)


def _systemd_user_unit_content(runtime: LinuxServiceRuntime) -> str:
    environment_lines = systemd_environment_lines(runtime, system=False)
    indented_environment = "".join(f"        {line}\n" for line in environment_lines)
    return textwrap.dedent(f"""\
        [Unit]
        Description=Netorium Controller
        After=network.target

        [Service]
        Type=simple
{indented_environment}        ExecStart={runtime.exec_start}
        Restart=on-failure
        RestartSec=10

        [Install]
        WantedBy=default.target
    """)


def _install_systemd(host: str, port: int, *, system: bool) -> str:
    runtime = resolve_linux_service_runtime(
        argv_tail=["controller", "start", "--host", host, "--port", str(port), "--quiet"],
    )
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
        content = _systemd_unit_content(runtime, system=True)
        _write_file_root(unit_file, content)
        _run(["systemctl", "daemon-reload"])
        _run(["systemctl", "enable", "--now", _SYSTEMD_SERVICE_NAME])
        return (
            f"System service installed and started: {unit_file}\n"
            f"  Runs as: {runtime.service_user}\n"
            f"  Status:  systemctl status {_SYSTEMD_SERVICE_NAME}\n"
            f"  Logs:    journalctl -u {_SYSTEMD_SERVICE_NAME} -f\n"
            f"  Stop:    systemctl stop {_SYSTEMD_SERVICE_NAME}\n"
            f"  Remove:  netorium controller uninstall-service"
        )

    unit_dir = _systemd_user_dir()
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_file = unit_dir / f"{_SYSTEMD_SERVICE_NAME}.service"
    content = _systemd_user_unit_content(runtime)
    unit_file.write_text(content, encoding="utf-8")
    _run(["systemctl", "--user", "daemon-reload"])
    _run(["systemctl", "--user", "enable", "--now", _SYSTEMD_SERVICE_NAME])
    # Enable lingering so the service survives after logout
    username = os.environ.get("USER") or os.environ.get("USERNAME") or ""
    if username:
        _run_optional(["loginctl", "enable-linger", username])
    return (
        f"User service installed and started: {unit_file}\n"
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
        return f"System service removed: {unit_file}"
    else:
        _run_optional(["systemctl", "--user", "stop", _SYSTEMD_SERVICE_NAME])
        _run_optional(["systemctl", "--user", "disable", _SYSTEMD_SERVICE_NAME])
        unit_file = _systemd_user_dir() / f"{_SYSTEMD_SERVICE_NAME}.service"
        if unit_file.exists():
            unit_file.unlink()
        _run_optional(["systemctl", "--user", "daemon-reload"])
        return f"User service removed: {unit_file}"


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
        f"Launch Agent installed and started: {plist_file}\n"
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
    return f"Launch Agent removed: {plist_file}"


# ──────────────────────────────────────────────────────────────────────────────
# Windows – sc.exe or NSSM
# ──────────────────────────────────────────────────────────────────────────────

_WINDOWS_SERVICE_NAME = "NetoriumController"
_WINDOWS_TASK_NAME = "NetoriumController"


def _install_windows_service(host: str, port: int) -> str:
    executable = _find_executable("netorium")
    controller_args = ["controller", "start", "--host", host, "--port", str(port), "--quiet"]

    nssm = resolve_nssm_executable()
    if nssm:
        return _append_windows_service_health_note(
            _install_windows_nssm(nssm, executable, host, port),
            host=host,
            port=port,
        )

    try:
        return _append_windows_service_health_note(
            _install_windows_sc(
                executable=executable,
                args=controller_args,
                host=host,
                port=port,
                service_name=_WINDOWS_SERVICE_NAME,
                display_name="Netorium Controller",
            ),
            host=host,
            port=port,
        )
    except ControllerServiceError:
        return _append_windows_service_health_note(
            _install_windows_task(executable, host, port),
            host=host,
            port=port,
        )


def _install_windows_nssm(nssm: str, executable: str, host: str, port: int) -> str:
    svc = _WINDOWS_SERVICE_NAME
    _ensure_windows_programdata_dir()
    _remove_windows_service(svc, nssm=nssm)
    _run([nssm, "install", svc, executable,
          "controller", "start", "--host", host, "--port", str(port), "--quiet"])
    _run([nssm, "set", svc, "Start", "SERVICE_AUTO_START"])
    _run([nssm, "set", svc, "AppDirectory", str(Path(executable).parent)])
    
    env_args = []
    for var in ("USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOME"):
        if val := os.environ.get(var):
            env_args.append(f"{var}={val}")
    if env_args:
        _run([nssm, "set", svc, "AppEnvironmentExtra", *env_args])
        
    _run([nssm, "set", svc, "AppStdout", r"C:\ProgramData\Netorium\controller.log"])
    _run([nssm, "set", svc, "AppStderr", r"C:\ProgramData\Netorium\controller.err"])
    fw_warnings = _configure_windows_firewall(executable=executable, port=port)
    _run([nssm, "start", svc])
    parts = [
        f"Windows service '{svc}' installed and started with bundled NSSM.",
        f"  Listen:  http://{host}:{port}",
        f"  Status:  sc query {svc}",
        f"  Firewall: inbound TCP port {port} allowed on all profiles.",
        f"  Logs:    C:\\ProgramData\\Netorium\\controller.log",
        f"  Stop:    sc stop {svc}",
        f"  Remove:  netorium controller uninstall-service",
    ]
    parts.extend(fw_warnings)
    return "\n".join(parts)


def _install_windows_sc(
    *,
    executable: str,
    args: list[str],
    host: str,
    port: int,
    service_name: str,
    display_name: str,
) -> str:
    create_cmd = build_sc_create_command(
        service_name,
        executable,
        args,
        display_name=display_name,
    )
    config_cmd = build_sc_config_command(
        service_name,
        executable,
        args,
        display_name=display_name,
    )

    try:
        _run(create_cmd)
    except ControllerServiceError as exc:
        if not service_output_indicates_exists(str(exc)):
            raise
        _run(config_cmd)

    _run_optional(build_sc_stop_command(service_name))
    fw_warnings = _configure_windows_firewall(executable=executable, port=port)
    _run(build_sc_start_command(service_name))
    parts = [
        f"Windows service '{service_name}' installed and started with sc.exe.",
        f"  Listen:  http://{host}:{port}",
        f"  Status:  sc query {service_name}",
        f"  Firewall: inbound TCP port {port} allowed on all profiles.",
        f"  Stop:    sc stop {service_name}",
        f"  Remove:  netorium controller uninstall-service",
    ]
    parts.extend(fw_warnings)
    return "\n".join(parts)


def _install_windows_task(executable: str, host: str, port: int) -> str:
    task = _WINDOWS_TASK_NAME
    controller_args = ["controller", "start", "--host", host, "--port", str(port), "--quiet"]
    _remove_windows_task(task)
    _run(
        build_schtasks_create_command(
            task,
            executable,
            controller_args,
        )
    )
    fw_warnings = _configure_windows_firewall(executable=executable, port=port)
    _run(build_schtasks_run_command(task))
    parts = [
        f"Windows scheduled task '{task}' installed and started.",
        f"  Listen:  http://{host}:{port}",
        f"  Runs at logon and starts the controller in the background.",
        f"  Firewall: inbound TCP port {port} allowed on all profiles.",
        f"  Status:  schtasks /Query /TN {task}",
        f"  Stop:    taskkill /IM netorium.exe /F",
        f"  Remove:  netorium controller uninstall-service",
    ]
    parts.extend(fw_warnings)
    return "\n".join(parts)


def _remove_windows_task(task_name: str) -> None:
    _run_optional(build_schtasks_delete_command(task_name))


def _remove_windows_service(svc: str, *, nssm: str | None = None) -> None:
    if nssm:
        _run_optional([nssm, "stop", svc])
        _run_optional([nssm, "remove", svc, "confirm"])
        return

    _run_optional(build_sc_stop_command(svc))
    _run_optional(build_sc_delete_command(svc))


def _uninstall_windows_service() -> str:
    svc = _WINDOWS_SERVICE_NAME
    task = _WINDOWS_TASK_NAME
    nssm = resolve_nssm_executable()
    if nssm:
        # Try NSSM removal first (clean for NSSM-managed services)
        _run_optional([nssm, "stop", svc])
        _run_optional([nssm, "remove", svc, "confirm"])
    # Also attempt sc.exe removal (no-op if already gone or was never an sc service)
    _run_optional(build_sc_stop_command(svc))
    _run_optional(build_sc_delete_command(svc))
    # Remove the Task Scheduler fallback entry too
    _remove_windows_task(task)
    # Remove firewall rules added by install-service
    _run_optional(build_firewall_delete_command())
    _run_optional(build_firewall_delete_program_command())
    return f"Windows controller background task/service '{task}' stopped and removed."


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _ensure_controller_initialized() -> None:
    try:
        settings = load_settings()
        status = get_controller_status(settings.app.database_path)
    except ConfigError as exc:
        raise ControllerServiceError(str(exc)) from exc

    if not status.initialized:
        raise ControllerServiceError(
            "Controller is not initialized. Run `netorium controller init` before install-service."
        )


def _ensure_windows_programdata_dir() -> None:
    programdata = os.environ.get("ProgramData")
    if not programdata:
        return
    Path(programdata, "Netorium").mkdir(parents=True, exist_ok=True)


def _configure_windows_firewall(*, executable: str, port: int) -> list[str]:
    """Add Windows Firewall inbound rules for the Netorium Controller.

    Returns a list of warning strings (empty when all rules were added successfully).
    Firewall configuration is non-fatal so the service is still installed even if
    netsh fails (e.g. partial admin rights or policy restriction).
    """
    _run_optional(build_firewall_delete_command())
    _run_optional(build_firewall_delete_program_command())
    warnings: list[str] = []
    try:
        _run(build_firewall_add_command(port))
    except ControllerServiceError as exc:
        warnings.append(
            f"  Warning: Could not add Windows Firewall port rule (TCP {port}): {exc}\n"
            f"  Add the rule manually (run as Administrator):\n"
            f"    netsh advfirewall firewall add rule name=\"Netorium Controller\" "
            f"dir=in action=allow protocol=TCP localport={port} profile=any enable=yes"
        )
        return warnings
    try:
        _run(build_firewall_add_program_command(executable))
    except ControllerServiceError as exc:
        warnings.append(
            f"  Warning: Could not add Windows Firewall program rule for '{executable}': {exc}\n"
            "  The port rule was added successfully; inbound connections should still work."
        )
    return warnings




def _append_windows_service_health_note(message: str, *, host: str, port: int) -> str:
    health_note = _wait_for_controller_health(port)
    lan_note = _format_windows_lan_health_hint(host=host, port=port)
    parts = [message.rstrip()]
    if health_note is not None:
        parts.append(health_note)
    if lan_note is not None:
        parts.append(lan_note)
    return "\n".join(parts) + "\n"


def _wait_for_controller_health(port: int, *, timeout: float | None = None) -> str | None:
    active_timeout = timeout
    if active_timeout is None:
        active_timeout = 0.25 if "PYTEST_CURRENT_TEST" in os.environ else 15.0
    deadline = time.monotonic() + active_timeout
    url = f"http://127.0.0.1:{port}/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return f"  Health:  {url} OK"
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(1)
    return (
        f"  Warning: controller is not responding on {url} yet.\n"
        "  Check logs, Windows Firewall, and run: netorium controller status"
    )


def _format_windows_lan_health_hint(*, host: str, port: int) -> str | None:
    if host not in {"0.0.0.0", "::"}:
        return None

    lan_host = _detect_windows_lan_host()
    if lan_host is None:
        return None

    return (
        f"  LAN test: curl http://{lan_host}:{port}/health\n"
        f"  Enrollment from other PCs: http://{lan_host}:{port}/enroll\n"
        "  If another PC cannot connect, run there:\n"
        f"    Test-NetConnection {lan_host} -Port {port}\n"
        "  If that fails, check Windows network profile/firewall rules and router/Wi-Fi client isolation."
    )


def _detect_windows_lan_host() -> str | None:
    try:
        for result in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = str(result[4][0])
            if not address.startswith("127.") and address != "0.0.0.0":
                return address
    except OSError:
        return None
    return None


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
        run_text(cmd)
    except FileNotFoundError as exc:
        raise ControllerServiceError(
            f"Command not found: {cmd[0]}. Is it installed and on PATH?"
        ) from exc
    except subprocess.CalledProcessError as exc:
        stdout = (exc.stdout or "").strip()
        stderr = (exc.stderr or "").strip()
        output = "\n".join(part for part in (stdout, stderr) if part)
        command_text = subprocess.list2cmdline(cmd)
        hint = _service_command_hint(cmd, output)
        details = "\n".join(part for part in (output, hint) if part)
        raise ControllerServiceError(
            f"Command failed: {command_text}" + (f"\n{details}" if details else "")
        ) from exc


def _run_optional(cmd: list[str]) -> None:
    """Run a command, ignoring errors (used for cleanup steps)."""
    try:
        run_text_optional(cmd)
    except FileNotFoundError:
        pass


def _service_command_hint(cmd: list[str], output: str) -> str:
    if not cmd:
        return ""

    command_name = Path(cmd[0]).name.lower()
    if command_name in {"sc", "sc.exe"}:
        normalized_output = output.lower()
        if "access is denied" in normalized_output or "отказано в доступе" in normalized_output:
            return "Hint: open Windows Terminal or PowerShell as Administrator, then run this command again."
        if "already exists" in normalized_output or "уже существует" in normalized_output:
            return "Hint: remove the old service first with: netorium controller uninstall-service"
        return ""

    if command_name == "schtasks":
        normalized_output = output.lower()
        if "access is denied" in normalized_output or "отказано в доступе" in normalized_output:
            return "Hint: open Windows Terminal or PowerShell as Administrator, then run this command again."
    return ""


def _write_file_root(path: Path, content: str) -> None:
    """Write a file, raising ControllerServiceError if it fails (e.g. not root)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except PermissionError as exc:
        raise ControllerServiceError(
            f"Permission denied writing {path}. Run with sudo to install a system service."
        ) from exc
