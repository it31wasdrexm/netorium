from __future__ import annotations

import json
import ipaddress
import os
import shutil
import socket
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urlparse

import requests

from netorium.core.platform import user_config_path
from netorium.core.subprocess_utils import run_text, run_text_optional
from netorium.services.command_signing import hash_shared_secret, verify_agent_command_signature
from netorium.services.endpoint_policy import (
    EndpointPolicyError,
    apply_app_policy,
    apply_ip_firewall_policy,
    apply_site_policy,
    apply_speed_policy,
    enforce_unix_app_blocklist,
    enforce_unix_site_blocklist,
)
from netorium.services.controller_service import reexec_windows_admin_if_needed
from netorium.services.traffic_monitor import collect_local_traffic_counters
from netorium.services.linux_service_runtime import (
    LinuxServiceRuntime,
    build_sudo_reexec_command,
    resolve_linux_service_runtime,
    systemd_environment_lines,
    user_home,
)
from netorium.services.windows_background import (
    build_schtasks_create_command,
    build_schtasks_delete_command,
    build_schtasks_end_command,
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

DEFAULT_TIMEOUT_SECONDS = 10.0
COMMAND_TYPE_FIREWALL_IP = "firewall.ip"
COMMAND_TYPE_SITE_ACCESS = "network.site"
COMMAND_TYPE_APP_ACCESS = "network.app"
COMMAND_TYPE_SPEED_LIMIT = "network.speed"


class AgentError(RuntimeError):
    pass


class HttpResponse(Protocol):
    status_code: int
    text: str

    def json(self) -> Any:
        pass


class HttpClient(Protocol):
    def post(self, url: str, json: dict[str, Any], timeout: float) -> HttpResponse:
        pass


@dataclass(frozen=True)
class AgentState:
    controller_url: str
    agent_id: str
    hostname: str
    zone: str
    device_token: str
    enrolled_at: str
    state_path: Path


@dataclass(frozen=True)
class AgentStatus:
    enrolled: bool
    state_path: Path
    controller_url: str | None = None
    agent_id: str | None = None
    hostname: str | None = None
    zone: str | None = None
    enrolled_at: str | None = None


@dataclass(frozen=True)
class AgentRunResult:
    enrolled: bool
    message: str
    controller_url: str | None = None
    accepted_at: str | None = None
    pending_commands: tuple[dict[str, Any], ...] = ()
    command_results: tuple["AgentCommandExecution", ...] = ()


@dataclass(frozen=True)
class AgentCommandExecution:
    command_id: str
    status: str
    message: str


def default_agent_state_path() -> Path:
    return user_config_path().with_name("agent.json")


def enroll_agent(
    *,
    controller_url: str,
    token: str,
    hostname: str | None = None,
    state_path: str | Path | None = None,
    client: HttpClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> AgentState:
    clean_controller_url = _normalize_controller_url(controller_url)
    clean_token = _normalize_text(token, "Enrollment token")
    clean_hostname = _normalize_text(hostname or socket.gethostname(), "Agent hostname")
    active_client: HttpClient = client or cast(HttpClient, _default_http_client())
    enroll_url = f"{clean_controller_url}/enroll"

    try:
        response = active_client.post(
            enroll_url,
            json={"token": clean_token, "hostname": clean_hostname},
            timeout=timeout,
        )
    except requests.Timeout as exc:
        raise _controller_unreachable_error(enroll_url, clean_controller_url) from exc
    except requests.ConnectionError as exc:
        if _looks_like_connection_timeout(exc):
            raise _controller_unreachable_error(enroll_url, clean_controller_url) from exc
        raise AgentError(f"Could not reach controller enrollment endpoint: {exc}") from exc
    except requests.RequestException as exc:
        raise AgentError(f"Could not reach controller enrollment endpoint: {exc}") from exc

    if response.status_code >= 400:
        raise AgentError(_format_enrollment_failure(response, controller_url=clean_controller_url))

    payload = _read_json_object(response)
    agent_id = _read_required_string(payload, "agent_id")
    device_token = _read_required_string(payload, "device_token")
    zone = _read_string_allow_empty(payload, "zone")
    enrolled_at = _read_required_string(payload, "enrolled_at")

    path = Path(state_path).expanduser() if state_path is not None else default_agent_state_path()
    state = AgentState(
        controller_url=clean_controller_url,
        agent_id=agent_id,
        hostname=clean_hostname,
        zone=zone,
        device_token=device_token,
        enrolled_at=enrolled_at,
        state_path=path,
    )
    _write_state(state)
    return state


def load_agent_state(state_path: str | Path | None = None) -> AgentState:
    path = Path(state_path).expanduser() if state_path is not None else default_agent_state_path()
    if not path.exists():
        raise AgentError(f"Agent is not enrolled. Run `netorium agent enroll` first. State: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AgentError(f"Could not read agent state {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise AgentError(f"Agent state is invalid: {path}")

    return AgentState(
        controller_url=_read_required_string(data, "controller_url"),
        agent_id=_read_required_string(data, "agent_id"),
        hostname=_read_required_string(data, "hostname"),
        zone=_read_string_allow_empty(data, "zone"),
        device_token=_read_required_string(data, "device_token"),
        enrolled_at=_read_required_string(data, "enrolled_at"),
        state_path=path,
    )


def get_agent_status(state_path: str | Path | None = None) -> AgentStatus:
    path = Path(state_path).expanduser() if state_path is not None else default_agent_state_path()
    try:
        state = load_agent_state(path)
    except AgentError:
        return AgentStatus(enrolled=False, state_path=path)

    return AgentStatus(
        enrolled=True,
        state_path=path,
        controller_url=state.controller_url,
        agent_id=state.agent_id,
        hostname=state.hostname,
        zone=state.zone,
        enrolled_at=state.enrolled_at,
    )


def run_agent_once(
    state_path: str | Path | None = None,
    *,
    client: HttpClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> AgentRunResult:
    _enforce_local_unix_policies()
    try:
        state = load_agent_state(state_path)
    except AgentError as exc:
        return AgentRunResult(enrolled=False, message=str(exc))

    active_client: HttpClient = client or cast(HttpClient, _default_http_client())
    heartbeat_url = f"{state.controller_url}/heartbeat"
    heartbeat_payload: dict[str, object] = {
        "agent_id": state.agent_id,
        "device_token": state.device_token,
    }
    traffic_counters = _collect_agent_traffic_counters()
    if traffic_counters is not None:
        heartbeat_payload["bytes_sent"] = traffic_counters[0]
        heartbeat_payload["bytes_received"] = traffic_counters[1]
    try:
        response = active_client.post(
            heartbeat_url,
            json=heartbeat_payload,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise AgentError(f"Could not reach controller heartbeat endpoint: {exc}") from exc

    if response.status_code >= 400:
        raise AgentError(f"Controller heartbeat failed with HTTP {response.status_code}: {response.text}")

    payload = _read_json_object(response)
    accepted_at = _read_required_string(payload, "accepted_at")
    commands = _read_commands(payload)
    command_results = tuple(_execute_agent_command(state, command) for command in commands)
    for result in command_results:
        _post_command_result(
            active_client,
            state=state,
            result=result,
            timeout=timeout,
        )

    return AgentRunResult(
        enrolled=True,
        controller_url=state.controller_url,
        accepted_at=accepted_at,
        pending_commands=commands,
        command_results=command_results,
        message=(
            "Heartbeat accepted; no endpoint commands are queued yet."
            if not commands
            else f"Heartbeat accepted; processed {len(command_results)} endpoint command(s)."
        ),
    )


def run_agent_loop(
    state_path: str | Path | None = None,
    *,
    client: HttpClient | None = None,
    interval_seconds: float = 2.0,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Run the agent heartbeat loop forever (used by the background service)."""
    import time

    while True:
        status = get_agent_status(state_path)
        if not status.enrolled:
            time.sleep(interval_seconds)
            continue

        try:
            run_agent_once(state_path, client=client, timeout=timeout)
        except AgentError:
            pass  # Log silently; the service manager will restart on crash
        time.sleep(interval_seconds)


def try_provision_agent_background_service() -> str:
    """Install and start the agent background service when enrollment succeeded."""
    try:
        return service_action("install")
    except AgentError:
        pass

    try:
        return service_action("start")
    except AgentError:
        pass

    return _start_detached_agent_loop()


def _start_detached_agent_loop() -> str:
    """Fall back to a detached heartbeat loop when service install is unavailable."""
    executable = _find_netorium_executable()
    popen_kwargs: dict[str, object] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform.startswith("win"):
        popen_kwargs["creationflags"] = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    else:
        popen_kwargs["start_new_session"] = True

    try:
        subprocess.Popen([executable, "agent", "run-loop"], **popen_kwargs)
    except OSError as exc:
        raise AgentError(f"Could not start background agent loop: {exc}") from exc

    return (
        "Agent heartbeat loop started in the background.\n"
        "  Commands from the controller are applied automatically."
    )


# ──────────────────────────────────────────────────────────────────────────────
# Service management
# ──────────────────────────────────────────────────────────────────────────────

_SYSTEMD_SERVICE_NAME = "netorium-agent"
_SYSTEMD_SYSTEM_DIR = Path("/etc/systemd/system")
_SYSTEMD_USER_DIR = Path("~/.config/systemd/user").expanduser()
_LAUNCHD_LABEL = "com.netorium.agent"
_LAUNCHD_PLIST_DIR = Path("~/Library/LaunchAgents").expanduser()
_WINDOWS_SERVICE_NAME = "NetoriumAgent"
_WINDOWS_TASK_NAME = "NetoriumAgent"


def service_action(action: str, *, system: bool = False) -> str:
    """Install, start, stop, or uninstall the agent background service."""
    clean_action = _normalize_text(action, "Service action")
    if clean_action not in {"install", "start", "stop", "uninstall"}:
        raise AgentError(f"Unsupported service action: {clean_action}")

    platform = sys.platform
    if platform.startswith("linux"):
        reexec_sudo_agent_install_if_needed(action=clean_action, system=system)
        return _systemd_action(clean_action, system=system)
    if platform == "darwin":
        return _launchd_action(clean_action)
    if platform.startswith("win"):
        return _windows_service_action(clean_action)
    raise AgentError(
        f"Unsupported platform for service management: {platform}. "
        "Supported: Linux (systemd), macOS (launchd), Windows (sc.exe/NSSM)."
    )


def reexec_sudo_agent_install_if_needed(*, action: str, system: bool) -> None:
    """Re-exec this process under sudo for a Linux system agent service install."""
    if action != "install" or not system or os.geteuid() == 0:
        return
    if "PYTEST_CURRENT_TEST" in os.environ:
        return
    executable = _find_netorium_executable()
    try:
        os.execvp(
            "sudo",
            build_sudo_reexec_command(argv_tail=["agent", "service", "install", "--system"]),
        )
    except FileNotFoundError as exc:
        raise AgentError(
            "sudo was not found. Install sudo or run the install command as root:\n"
            f"  {executable} agent service install --system"
        ) from exc


# ─── Helpers for combined binary ─────────────────────────────────────────────

def _find_netorium_executable() -> str:
    """Find the netorium executable (the single combined binary)."""
    if getattr(sys, "frozen", False):
        return sys.executable
    for name in ("netorium",):
        path = shutil.which(name)
        if path:
            return path
    candidate = Path(sys.executable).parent / "netorium"
    if candidate.exists():
        return str(candidate)
    candidate_exe = Path(sys.executable).parent / "netorium.exe"
    if candidate_exe.exists():
        return str(candidate_exe)
    raise AgentError(
        "Could not find the 'netorium' executable. "
        "Make sure Netorium is installed and on your PATH."
    )


# ─── Linux / systemd ──────────────────────────────────────────────────────────

def _systemd_unit_content(runtime: LinuxServiceRuntime, *, system: bool) -> str:
    # System units run as root so Linux site policies can update /etc/hosts.
    service_lines = [] if system else []
    environment_lines = systemd_environment_lines(runtime, system=system)
    indented_service = "".join(f"        {line}\n" for line in service_lines)
    indented_environment = "".join(f"        {line}\n" for line in environment_lines)
    wanted_by = "multi-user.target" if system else "default.target"
    return textwrap.dedent(f"""\
        [Unit]
        Description=Netorium Agent
        After=network.target

        [Service]
        Type=simple
{indented_service}{indented_environment}        ExecStart={runtime.exec_start}
        Restart=always
        RestartSec=15

        [Install]
        WantedBy={wanted_by}
    """)


def _systemd_action(action: str, *, system: bool) -> str:
    runtime = resolve_linux_service_runtime(argv_tail=["agent", "run-loop"])
    is_root = os.geteuid() == 0
    use_system_unit = system or is_root or (
        action in {"start", "stop", "uninstall"} and _agent_system_unit_installed()
    )
    if system and not is_root:
        executable = _find_netorium_executable()
        raise AgentError(
            "System agent service install requires root privileges. "
            f"Run: {executable} agent service install --system"
        )

    if use_system_unit:
        unit_file = _SYSTEMD_SYSTEM_DIR / f"{_SYSTEMD_SERVICE_NAME}.service"
        if action == "install":
            _write_systemd_unit_file(unit_file, _systemd_unit_content(runtime, system=True))
            _run_service_cmd(["systemctl", "daemon-reload"])
            _run_service_cmd(["systemctl", "enable", "--now", _SYSTEMD_SERVICE_NAME])
            return (
                f"[systemd system] Agent service installed: {unit_file}\n"
                f"  Runs as: root (required for /etc/hosts site policies)\n"
                f"  Data dir: {user_home(runtime.service_user)}/.local/share/netorium\n"
                f"  Status:  systemctl status {_SYSTEMD_SERVICE_NAME}\n"
                f"  Logs:    journalctl -u {_SYSTEMD_SERVICE_NAME} -f\n"
                f"  Stop:    systemctl stop {_SYSTEMD_SERVICE_NAME}"
            )
        if action == "start":
            _run_service_cmd(["systemctl", "start", _SYSTEMD_SERVICE_NAME])
            return f"[systemd system] Agent service started: {_SYSTEMD_SERVICE_NAME}"
        if action == "stop":
            _run_service_cmd(["systemctl", "stop", _SYSTEMD_SERVICE_NAME])
            return f"[systemd system] Agent service stopped: {_SYSTEMD_SERVICE_NAME}"
        if action == "uninstall":
            _run_service_cmd_optional(["systemctl", "stop", _SYSTEMD_SERVICE_NAME])
            _run_service_cmd_optional(["systemctl", "disable", _SYSTEMD_SERVICE_NAME])
            if unit_file.exists():
                unit_file.unlink()
            _run_service_cmd_optional(["systemctl", "daemon-reload"])
            return f"[systemd system] Agent service removed: {unit_file}"
        raise AgentError(f"Unknown service action: {action}")

    unit_dir = _SYSTEMD_USER_DIR
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_file = unit_dir / f"{_SYSTEMD_SERVICE_NAME}.service"

    if action == "install":
        unit_file.write_text(_systemd_unit_content(runtime, system=False), encoding="utf-8")
        _run_service_cmd(["systemctl", "--user", "daemon-reload"])
        _run_service_cmd(["systemctl", "--user", "enable", "--now", _SYSTEMD_SERVICE_NAME])
        username = os.environ.get("USER") or ""
        if username:
            _run_service_cmd_optional(["loginctl", "enable-linger", username])
        return (
            f"[systemd --user] Agent service installed: {unit_file}\n"
            f"  Status:  systemctl --user status {_SYSTEMD_SERVICE_NAME}\n"
            f"  Logs:    journalctl --user -u {_SYSTEMD_SERVICE_NAME} -f\n"
            f"  Stop:    systemctl --user stop {_SYSTEMD_SERVICE_NAME}\n"
            "  Note: Linux site policies need /etc/hosts access. Prefer "
            "`netorium agent service install --system` for managed endpoints."
        )

    if action == "start":
        _run_service_cmd(["systemctl", "--user", "start", _SYSTEMD_SERVICE_NAME])
        return f"[systemd --user] Agent service started: {_SYSTEMD_SERVICE_NAME}"

    if action == "stop":
        _run_service_cmd(["systemctl", "--user", "stop", _SYSTEMD_SERVICE_NAME])
        return f"[systemd --user] Agent service stopped: {_SYSTEMD_SERVICE_NAME}"

    if action == "uninstall":
        _run_service_cmd_optional(["systemctl", "--user", "stop", _SYSTEMD_SERVICE_NAME])
        _run_service_cmd_optional(["systemctl", "--user", "disable", _SYSTEMD_SERVICE_NAME])
        if unit_file.exists():
            unit_file.unlink()
        _run_service_cmd_optional(["systemctl", "--user", "daemon-reload"])
        return f"[systemd --user] Agent service removed: {unit_file}"

    raise AgentError(f"Unknown service action: {action}")


def _write_systemd_unit_file(path: Path, content: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except PermissionError as exc:
        raise AgentError(
            f"Permission denied writing {path}. Run with sudo to install a system service."
        ) from exc


def _agent_system_unit_installed() -> bool:
    return (_SYSTEMD_SYSTEM_DIR / f"{_SYSTEMD_SERVICE_NAME}.service").exists()


# ─── macOS / launchd ──────────────────────────────────────────────────────────

def _launchd_plist_content(executable: str) -> str:
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
                <string>agent</string>
                <string>run-loop</string>
            </array>
            <key>RunAtLoad</key>
            <true/>
            <key>KeepAlive</key>
            <true/>
            <key>StandardOutPath</key>
            <string>/tmp/netorium-agent.log</string>
            <key>StandardErrorPath</key>
            <string>/tmp/netorium-agent.err</string>
        </dict>
        </plist>
    """)


def _launchd_action(action: str) -> str:
    executable = _find_netorium_executable()
    _LAUNCHD_PLIST_DIR.mkdir(parents=True, exist_ok=True)
    plist_file = _LAUNCHD_PLIST_DIR / f"{_LAUNCHD_LABEL}.plist"

    if action == "install":
        plist_file.write_text(_launchd_plist_content(executable), encoding="utf-8")
        _run_service_cmd(["launchctl", "load", "-w", str(plist_file)])
        return (
            f"[launchd] Agent Launch Agent installed: {plist_file}\n"
            f"  Status:  launchctl list | grep netorium\n"
            f"  Logs:    tail -f /tmp/netorium-agent.log"
        )
    if action == "start":
        _run_service_cmd(["launchctl", "start", _LAUNCHD_LABEL])
        return "[launchd] Agent service started."
    if action == "stop":
        _run_service_cmd(["launchctl", "stop", _LAUNCHD_LABEL])
        return "[launchd] Agent service stopped."
    if action == "uninstall":
        _run_service_cmd_optional(["launchctl", "unload", "-w", str(plist_file)])
        if plist_file.exists():
            plist_file.unlink()
        return f"[launchd] Agent Launch Agent removed: {plist_file}"
    raise AgentError(f"Unknown service action: {action}")


# ─── Windows ──────────────────────────────────────────────────────────────────

def _windows_service_action(action: str) -> str:
    reexec_windows_admin_if_needed(["agent", "service", action])
    executable = _find_netorium_executable()
    svc = _WINDOWS_SERVICE_NAME
    nssm = resolve_nssm_executable()

    if action == "install":
        agent_args = ["agent", "run-loop"]
        if nssm:
            _ensure_windows_programdata_dir()
            _run_service_cmd_optional([nssm, "stop", svc])
            _run_service_cmd_optional([nssm, "remove", svc, "confirm"])
            _run_service_cmd([nssm, "install", svc, executable, *agent_args])
            _run_service_cmd([nssm, "set", svc, "Start", "SERVICE_AUTO_START"])
            _run_service_cmd([nssm, "set", svc, "AppNoConsole", "1"])
            env_args = []
            for var in ("USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOME"):
                if val := os.environ.get(var):
                    env_args.append(f"{var}={val}")
            if env_args:
                _run_service_cmd([nssm, "set", svc, "AppEnvironmentExtra", *env_args])
            _run_service_cmd([nssm, "set", svc, "AppStdout",
                              r"C:\ProgramData\Netorium\agent.log"])
            _run_service_cmd([nssm, "set", svc, "AppStderr",
                              r"C:\ProgramData\Netorium\agent.err"])
            _run_service_cmd_optional([nssm, "start", svc])
            return (
                f"[Windows/NSSM] Agent service '{svc}' installed and started.\n"
                f"  Status:  sc query {svc}\n"
                f"  Logs:    C:\\ProgramData\\Netorium\\agent.log"
            )

        try:
            return _install_windows_agent_sc(
                executable=executable,
                args=agent_args,
                service_name=svc,
            )
        except AgentError:
            task = _WINDOWS_TASK_NAME
            _run_service_cmd_optional(build_schtasks_delete_command(task))
            _run_service_cmd(
                build_schtasks_create_command(
                    task,
                    executable,
                    agent_args,
                )
            )
            _run_service_cmd(build_schtasks_run_command(task))
            return (
                f"[Windows] Agent scheduled task '{task}' installed and started.\n"
                f"  Runs at logon and keeps the agent connected in the background.\n"
                f"  Status:  schtasks /Query /TN {_WINDOWS_TASK_NAME}"
            )

    if action == "start":
        if nssm:
            try:
                _run_service_cmd([nssm, "start", svc])
            except AgentError as exc:
                completed = run_text_optional(["sc.exe", "query", svc])
                if "RUNNING" not in completed.stdout and "RUNNING" not in completed.stderr:
                    raise exc
        else:
            try:
                _run_service_cmd(build_sc_start_command(svc))
            except AgentError:
                _run_service_cmd(build_schtasks_run_command(_WINDOWS_TASK_NAME))
        return "[Windows] Agent background task/service started."

    if action == "stop":
        if nssm:
            _run_service_cmd([nssm, "stop", svc])
        else:
            _run_service_cmd_optional(build_sc_stop_command(svc))
            _run_service_cmd_optional(build_schtasks_end_command(_WINDOWS_TASK_NAME))
        return "[Windows] Agent background task/service stopped."

    if action == "uninstall":
        if nssm:
            _run_service_cmd_optional([nssm, "stop", svc])
            _run_service_cmd_optional([nssm, "remove", svc, "confirm"])
        else:
            _run_service_cmd_optional(build_schtasks_delete_command(_WINDOWS_TASK_NAME))
        _run_service_cmd_optional(build_sc_stop_command(svc))
        _run_service_cmd_optional(build_sc_delete_command(svc))
        return "[Windows] Agent background task/service removed."

    raise AgentError(f"Unknown service action: {action}")


# ─── Service command helpers ─────────────────────────────────────────────────

def _run_service_cmd(cmd: list[str]) -> None:
    try:
        run_text(cmd)
    except FileNotFoundError as exc:
        raise AgentError(f"Command not found: {cmd[0]}") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise AgentError(f"Command failed: {' '.join(cmd)}\n{stderr}") from exc


def _run_service_cmd_optional(cmd: list[str]) -> None:
    """Run a command, ignoring errors (used for cleanup steps)."""
    try:
        run_text_optional(cmd)
    except FileNotFoundError:
        pass


def _execute_agent_command(state: AgentState, command: dict[str, Any]) -> AgentCommandExecution:
    command_id = _read_command_string(command, "command_id")
    command_type = _read_command_string(command, "command_type")
    created_at = _read_command_string(command, "created_at")
    payload = command.get("payload")
    if not isinstance(payload, dict):
        return AgentCommandExecution(
            command_id=command_id,
            status="failed",
            message="Agent command payload must be an object.",
        )
    signature = command.get("signature")
    if not isinstance(signature, str) or not signature.strip():
        return AgentCommandExecution(
            command_id=command_id,
            status="failed",
            message="Agent command signature is missing.",
        )

    if not _verify_agent_command_signature(
        state=state,
        command_id=command_id,
        command_type=command_type,
        payload=payload,
        created_at=created_at,
        signature=signature,
    ):
        return AgentCommandExecution(
            command_id=command_id,
            status="failed",
            message="Agent command signature is invalid.",
        )

    try:
        if command_type == COMMAND_TYPE_FIREWALL_IP:
            return _execute_firewall_command(command_id, payload)
        if command_type == COMMAND_TYPE_SITE_ACCESS:
            return _execute_site_command(command_id, payload)
        if command_type == COMMAND_TYPE_APP_ACCESS:
            return _execute_app_command(command_id, payload)
        if command_type == COMMAND_TYPE_SPEED_LIMIT:
            return _execute_speed_command(command_id, payload)
    except (AgentError, EndpointPolicyError) as exc:
        return AgentCommandExecution(
            command_id=command_id,
            status="failed",
            message=str(exc),
        )

    return AgentCommandExecution(
        command_id=command_id,
        status="failed",
        message=f"Unsupported agent command type: {command_type}",
    )


def _execute_firewall_command(command_id: str, payload: dict[str, Any]) -> AgentCommandExecution:
    action = _read_payload_string(payload, "action")
    if action not in {"block", "unblock"}:
        raise AgentError("Endpoint firewall action must be block or unblock.")

    ip_address = _normalize_ip_address(_read_payload_string(payload, "ip_address"))
    reason = _normalize_text(_read_payload_string(payload, "reason"), "Firewall reason")
    dry_run = payload.get("dry_run")
    if dry_run is not True:
        result = apply_ip_firewall_policy(action=action, ip_address=ip_address, reason=reason)
        return AgentCommandExecution(
            command_id=command_id,
            status="completed",
            message=result.message,
        )

    return AgentCommandExecution(
        command_id=command_id,
        status="completed",
        message=f"Dry-run firewall {action} accepted for {ip_address}: {reason}",
    )


def _execute_site_command(command_id: str, payload: dict[str, Any]) -> AgentCommandExecution:
    action = _read_policy_action(payload, "Site policy action")
    domain = _normalize_domain(_read_payload_string(payload, "domain"))
    reason = _normalize_text(_read_payload_string(payload, "reason"), "Site policy reason")
    if payload.get("dry_run") is not True:
        result = apply_site_policy(action=action, domain=domain, reason=reason)
        return AgentCommandExecution(
            command_id=command_id,
            status="completed",
            message=result.message,
        )

    return AgentCommandExecution(
        command_id=command_id,
        status="completed",
        message=f"Dry-run site {action} accepted for {domain}: {reason}",
    )


def _execute_app_command(command_id: str, payload: dict[str, Any]) -> AgentCommandExecution:
    action = _read_policy_action(payload, "Application network action")
    executable = _normalize_executable(_read_payload_string(payload, "executable"))
    reason = _normalize_text(_read_payload_string(payload, "reason"), "Application network reason")
    if payload.get("dry_run") is not True:
        result = apply_app_policy(action=action, executable=executable, reason=reason)
        return AgentCommandExecution(
            command_id=command_id,
            status="completed",
            message=result.message,
        )

    return AgentCommandExecution(
        command_id=command_id,
        status="completed",
        message=f"Dry-run app {action} accepted for {executable}: {reason}",
    )


def _execute_speed_command(command_id: str, payload: dict[str, Any]) -> AgentCommandExecution:
    action = _read_payload_string(payload, "action").lower()
    reason = _normalize_text(_read_payload_string(payload, "reason"), "Speed policy reason")

    if action == "clear":
        if payload.get("dry_run") is not True:
            result = apply_speed_policy(
                action=action,
                download_kbps=None,
                upload_kbps=None,
                reason=reason,
            )
            return AgentCommandExecution(
                command_id=command_id,
                status="completed",
                message=result.message,
            )
        return AgentCommandExecution(
            command_id=command_id,
            status="completed",
            message=f"Dry-run speed limit clear accepted: {reason}",
        )

    if action != "limit":
        raise AgentError("Speed policy action must be limit or clear.")

    download_kbps = _read_optional_kbps(payload, "download_kbps", "Download speed")
    upload_kbps = _read_optional_kbps(payload, "upload_kbps", "Upload speed")
    if download_kbps is None and upload_kbps is None:
        raise AgentError("Speed limit requires download_kbps or upload_kbps.")

    if payload.get("dry_run") is not True:
        result = apply_speed_policy(
            action=action,
            download_kbps=download_kbps,
            upload_kbps=upload_kbps,
            reason=reason,
        )
        return AgentCommandExecution(
            command_id=command_id,
            status="completed",
            message=result.message,
        )

    return AgentCommandExecution(
        command_id=command_id,
        status="completed",
        message=(
            "Dry-run speed limit accepted "
            f"download={_format_optional_kbps(download_kbps)} "
            f"upload={_format_optional_kbps(upload_kbps)}: {reason}"
        ),
    )


def _verify_agent_command_signature(
    *,
    state: AgentState,
    command_id: str,
    command_type: str,
    payload: dict[str, Any],
    created_at: str,
    signature: str,
) -> bool:
    try:
        signing_key = hash_shared_secret(state.device_token, label="Device token")
    except ValueError as exc:
        raise AgentError(str(exc)) from exc

    return verify_agent_command_signature(
        signing_key=signing_key,
        agent_id=state.agent_id,
        command_id=command_id,
        command_type=command_type,
        payload=payload,
        created_at=created_at,
        signature=signature,
    )


def _post_command_result(
    client: HttpClient,
    *,
    state: AgentState,
    result: AgentCommandExecution,
    timeout: float,
) -> None:
    result_url = f"{state.controller_url}/command-result"
    try:
        response = client.post(
            result_url,
            json={
                "agent_id": state.agent_id,
                "device_token": state.device_token,
                "command_id": result.command_id,
                "status": result.status,
                "message": result.message,
            },
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise AgentError(f"Could not report agent command result: {exc}") from exc

    if response.status_code >= 400:
        raise AgentError(
            f"Controller command-result endpoint failed with HTTP {response.status_code}: {response.text}"
        )


def _write_state(state: AgentState) -> None:
    payload = {
        "controller_url": state.controller_url,
        "agent_id": state.agent_id,
        "hostname": state.hostname,
        "zone": state.zone,
        "device_token": state.device_token,
        "enrolled_at": state.enrolled_at,
    }
    try:
        state.state_path.parent.mkdir(parents=True, exist_ok=True)
        state.state_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise AgentError(f"Could not write agent state {state.state_path}: {exc}") from exc


def _install_windows_agent_sc(
    *,
    executable: str,
    args: list[str],
    service_name: str,
) -> str:
    create_cmd = build_sc_create_command(
        service_name,
        executable,
        args,
        display_name="Netorium Agent",
    )
    config_cmd = build_sc_config_command(
        service_name,
        executable,
        args,
        display_name="Netorium Agent",
    )

    try:
        _run_service_cmd(create_cmd)
    except AgentError as exc:
        if not service_output_indicates_exists(str(exc)):
            raise
        _run_service_cmd(config_cmd)

    _run_service_cmd_optional(build_sc_stop_command(service_name))
    _run_service_cmd(build_sc_start_command(service_name))
    return (
        f"[Windows/sc.exe] Agent service '{service_name}' installed and started.\n"
        f"  Status:  sc query {service_name}\n"
        f"  Remove:  netorium agent service uninstall\n"
    )


def _ensure_windows_programdata_dir() -> None:
    programdata = os.environ.get("ProgramData")
    if not programdata:
        return
    Path(programdata, "Netorium").mkdir(parents=True, exist_ok=True)


def _default_http_client() -> requests.Session:
    """Build an HTTP client that ignores OS proxy settings for LAN controllers."""
    session = requests.Session()
    session.trust_env = False
    return session


def _looks_like_connection_timeout(exc: requests.ConnectionError) -> bool:
    message = str(exc).lower()
    if "timed out" in message or "timeout" in message:
        return True

    cause = exc.__cause__
    while cause is not None:
        cause_message = str(cause).lower()
        if "timed out" in cause_message or "timeout" in cause_message:
            return True
        cause = getattr(cause, "__cause__", None)
    return False


def _format_enrollment_failure(response: HttpResponse, *, controller_url: str) -> str:
    raw_body = response.text.strip()
    controller_error = _read_controller_error_message(raw_body)
    lines = [
        f"Controller enrollment failed with HTTP {response.status_code}: {controller_error}",
    ]
    if "invalid" in controller_error.lower() and "token" in controller_error.lower():
        lines.extend(
            [
                "  Token troubleshooting:",
                "    - Create a fresh token on the controller PC: netorium controller token create",
                "    - Copy the token exactly once; it is shown only at creation time",
                "    - Make sure the controller URL points to the same controller that created the token",
                f"      Current URL: {controller_url}",
            ]
        )
        parsed = urlparse(controller_url)
        if parsed.hostname in {"127.0.0.1", "localhost"}:
            lines.append(
                "    - If this agent runs on another PC, do not use 127.0.0.1; use the controller PC's LAN IP"
            )
    return "\n".join(lines)


def _read_controller_error_message(raw_body: str) -> str:
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return raw_body or "unknown controller error"
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, str) and error.strip():
            return error.strip()
    return raw_body or "unknown controller error"


def _controller_unreachable_error(enroll_url: str, controller_url: str) -> AgentError:
    parsed = urlparse(controller_url)
    host = parsed.hostname or "CONTROLLER_IP"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    health_url = f"{controller_url}/health"
    return AgentError(
        "Could not reach controller enrollment endpoint: connection timed out.\n"
        f"  URL: {enroll_url}\n"
        "  This is a network reachability problem, not a token problem.\n"
        "  First prove this PC can reach the controller:\n"
        f"    curl {health_url}\n"
        f"    Test-NetConnection {host} -Port {port}\n"
        "  If Test-NetConnection shows TcpTestSucceeded=False or PingSucceeded=False, "
        "fix the LAN path before enrolling.\n"
        "  Check on the controller PC:\n"
        "    - controller is running (`netorium controller status`)\n"
        "    - background service is installed (`netorium controller install-service`)\n"
        "    - firewall allows inbound TCP on the controller port\n"
        f"      Windows admin fallback:\n"
        f"        netsh advfirewall firewall add rule name=\"Netorium Controller\" "
        f"dir=in action=allow protocol=TCP localport={port} profile=any enable=yes\n"
        f"        Set-NetConnectionProfile -InterfaceAlias \"Беспроводная сеть\" -NetworkCategory Private\n"
        f"      Linux: `sudo ufw allow {port}/tcp` or open the port in your firewall\n"
        "    - controller listens on 0.0.0.0, not only 127.0.0.1\n"
        "  If local controller health works but another PC cannot ping or open the port, "
        "the usual cause is guest Wi-Fi, router AP/client isolation, VPN isolation, "
        "or the wrong controller IP."
    )


def _normalize_controller_url(controller_url: str) -> str:
    clean_url = controller_url.strip().rstrip("/")
    if clean_url.lower().endswith("/enroll"):
        clean_url = clean_url[: -len("/enroll")]
    parsed = urlparse(clean_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AgentError("Controller URL must include http:// or https:// and a host.")
    return clean_url


def _normalize_text(value: str, label: str) -> str:
    clean_value = value.strip()
    if not clean_value:
        raise AgentError(f"{label} cannot be empty.")
    return clean_value


def _collect_agent_traffic_counters() -> tuple[int, int] | None:
    try:
        return collect_local_traffic_counters()
    except OSError:
        return None


def _read_json_object(response: HttpResponse) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise AgentError(f"Controller enrollment response is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise AgentError("Controller enrollment response must be a JSON object.")
    return payload


def _read_required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AgentError(f"Controller enrollment response is missing `{key}`.")
    return value.strip()


def _read_string_allow_empty(payload: dict[str, Any], key: str) -> str:
    """Read a string field that may be legitimately empty (e.g. zone)."""
    value = payload.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise AgentError(f"Controller enrollment response has invalid `{key}`.")
    return value.strip()


def _read_command_string(command: dict[str, Any], key: str) -> str:
    value = command.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AgentError(f"Controller heartbeat command is missing `{key}`.")
    return value.strip()


def _read_payload_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AgentError(f"Agent command payload is missing `{key}`.")
    return value.strip()


def _read_policy_action(payload: dict[str, Any], label: str) -> str:
    action = _read_payload_string(payload, "action").lower()
    if action not in {"block", "unblock"}:
        raise AgentError(f"{label} must be block or unblock.")
    return action


def _normalize_ip_address(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError as exc:
        raise AgentError(f"Invalid IP address: {value}") from exc


def _normalize_domain(value: str) -> str:
    raw_value = value.strip().lower()
    wildcard = raw_value.startswith("*.")
    parsed = urlparse(raw_value[2:] if wildcard and "://" not in raw_value else raw_value)
    if not parsed.netloc:
        parsed = urlparse(f"//{raw_value[2:] if wildcard else raw_value}")
    host = parsed.hostname or value.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    host = host.strip().lower().rstrip(".")
    if host.startswith("*."):
        wildcard = True
        host = host[2:]
    if not host or any(char.isspace() for char in host):
        raise AgentError(f"Invalid site domain: {value}")
    return f"*.{host}" if wildcard else host


def _normalize_executable(value: str) -> str:
    clean_value = _normalize_text(value, "Executable").strip("'\"").strip()
    if not clean_value:
        raise AgentError("Executable cannot be empty.")
    if "\x00" in clean_value or any(char in clean_value for char in "\r\n"):
        raise AgentError("Executable cannot contain control characters.")
    return clean_value


def _read_optional_kbps(
    payload: dict[str, Any],
    key: str,
    label: str,
) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, int):
        raise AgentError(f"{label} must be an integer kbps value.")
    if value < 1:
        raise AgentError(f"{label} must be at least 1 kbps.")
    return value


def _format_optional_kbps(value: int | None) -> str:
    if value is None:
        return "unlimited"
    return f"{value}kbps"


def _enforce_local_unix_policies() -> None:
    try:
        enforce_unix_app_blocklist()
    except Exception:
        # Enforcement should not break heartbeats when the local OS has no matching tools.
        pass
    try:
        enforce_unix_site_blocklist()
    except Exception:
        pass


def _read_commands(payload: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    raw_commands = payload.get("commands", [])
    if not isinstance(raw_commands, list):
        raise AgentError("Controller heartbeat response has invalid `commands`.")

    commands: list[dict[str, Any]] = []
    for raw_command in raw_commands:
        if not isinstance(raw_command, dict):
            raise AgentError("Controller heartbeat response command must be an object.")
        commands.append(raw_command)

    return tuple(commands)
