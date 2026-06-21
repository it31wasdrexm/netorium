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
from netorium.services.command_signing import hash_shared_secret, verify_agent_command_signature
from netorium.services.endpoint_policy import (
    EndpointPolicyError,
    apply_app_policy,
    apply_ip_firewall_policy,
    apply_site_policy,
    apply_speed_policy,
)
from netorium.services.windows_service import build_sc_create_command
from netorium.services.controller_service import reexec_windows_admin_if_needed

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
    active_client: HttpClient = client or cast(HttpClient, requests.Session())
    enroll_url = f"{clean_controller_url}/enroll"

    try:
        response = active_client.post(
            enroll_url,
            json={"token": clean_token, "hostname": clean_hostname},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise AgentError(f"Could not reach controller enrollment endpoint: {exc}") from exc

    if response.status_code >= 400:
        raise AgentError(f"Controller enrollment failed with HTTP {response.status_code}: {response.text}")

    payload = _read_json_object(response)
    agent_id = _read_required_string(payload, "agent_id")
    device_token = _read_required_string(payload, "device_token")
    zone = _read_required_string(payload, "zone")
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
        zone=_read_required_string(data, "zone"),
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
    try:
        state = load_agent_state(state_path)
    except AgentError as exc:
        return AgentRunResult(enrolled=False, message=str(exc))

    active_client: HttpClient = client or cast(HttpClient, requests.Session())
    heartbeat_url = f"{state.controller_url}/heartbeat"
    try:
        response = active_client.post(
            heartbeat_url,
            json={
                "agent_id": state.agent_id,
                "device_token": state.device_token,
            },
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
    interval_seconds: float = 15.0,
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


def try_provision_agent_background_service() -> str | None:
    """Install and start the agent background service when enrollment succeeded."""
    try:
        return service_action("install")
    except AgentError:
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Service management
# ──────────────────────────────────────────────────────────────────────────────

_SYSTEMD_SERVICE_NAME = "netorium-agent"
_SYSTEMD_USER_DIR = Path("~/.config/systemd/user").expanduser()
_LAUNCHD_LABEL = "com.netorium.agent"
_LAUNCHD_PLIST_DIR = Path("~/Library/LaunchAgents").expanduser()
_WINDOWS_SERVICE_NAME = "NetoriumAgent"


def service_action(action: str) -> str:
    """Install, start, stop, or uninstall the agent background service."""
    clean_action = _normalize_text(action, "Service action")
    if clean_action not in {"install", "start", "stop", "uninstall"}:
        raise AgentError(f"Unsupported service action: {clean_action}")

    platform = sys.platform
    if platform.startswith("linux"):
        return _systemd_action(clean_action)
    if platform == "darwin":
        return _launchd_action(clean_action)
    if platform.startswith("win"):
        return _windows_service_action(clean_action)
    raise AgentError(
        f"Unsupported platform for service management: {platform}. "
        "Supported: Linux (systemd), macOS (launchd), Windows (sc.exe/NSSM)."
    )


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

def _systemd_unit_content(executable: str) -> str:
    return textwrap.dedent(f"""\
        [Unit]
        Description=Netorium Agent
        After=network.target

        [Service]
        Type=simple
        ExecStart={executable} agent run-loop
        Restart=always
        RestartSec=15

        [Install]
        WantedBy=default.target
    """)


def _systemd_action(action: str) -> str:
    executable = _find_netorium_executable()
    unit_dir = _SYSTEMD_USER_DIR
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_file = unit_dir / f"{_SYSTEMD_SERVICE_NAME}.service"

    if action == "install":
        unit_file.write_text(_systemd_unit_content(executable), encoding="utf-8")
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
            f"  Remove:  netorium agent service uninstall"
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
            f"  Logs:    tail -f /tmp/netorium-agent.log\n"
            f"  Remove:  netorium agent service uninstall"
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
    nssm = shutil.which("nssm")

    if action == "install":
        if nssm:
            _run_service_cmd([nssm, "install", svc, executable, "agent", "run-loop"])
            _run_service_cmd([nssm, "set", svc, "Start", "SERVICE_AUTO_START"])
            _run_service_cmd([nssm, "set", svc, "AppStdout",
                              r"C:\ProgramData\Netorium\agent.log"])
            _run_service_cmd([nssm, "set", svc, "AppStderr",
                              r"C:\ProgramData\Netorium\agent.err"])
            _run_service_cmd([nssm, "start", svc])
            return (
                f"[Windows/NSSM] Agent service '{svc}' installed and started.\n"
                f"  Status:  sc query {svc}\n"
                f"  Logs:    C:\\ProgramData\\Netorium\\agent.log\n"
                f"  Remove:  netorium agent service uninstall"
            )
        else:
            _run_service_cmd(
                build_sc_create_command(
                    svc,
                    executable,
                    ["agent", "run-loop"],
                    display_name="Netorium Agent",
                )
            )
            _run_service_cmd(["sc", "start", svc])
            return (
                f"[Windows/sc.exe] Agent service '{svc}' installed and started.\n"
                f"  Status:  sc query {svc}\n"
                f"  Remove:  netorium agent service uninstall\n"
                "  Tip: Install NSSM (https://nssm.cc) for better log capture."
            )

    if action == "start":
        if nssm:
            _run_service_cmd([nssm, "start", svc])
        else:
            _run_service_cmd(["sc", "start", svc])
        return f"[Windows] Agent service '{svc}' started."

    if action == "stop":
        if nssm:
            _run_service_cmd([nssm, "stop", svc])
        else:
            _run_service_cmd(["sc", "stop", svc])
        return f"[Windows] Agent service '{svc}' stopped."

    if action == "uninstall":
        if nssm:
            _run_service_cmd_optional([nssm, "stop", svc])
            _run_service_cmd_optional([nssm, "remove", svc, "confirm"])
        else:
            _run_service_cmd_optional(["sc", "stop", svc])
            _run_service_cmd_optional(["sc", "delete", svc])
        return f"[Windows] Agent service '{svc}' removed."

    raise AgentError(f"Unknown service action: {action}")


# ─── Service command helpers ─────────────────────────────────────────────────

def _run_service_cmd(cmd: list[str]) -> None:
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise AgentError(f"Command not found: {cmd[0]}") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise AgentError(f"Command failed: {' '.join(cmd)}\n{stderr}") from exc


def _run_service_cmd_optional(cmd: list[str]) -> None:
    """Run a command, ignoring errors (used for cleanup steps)."""
    try:
        subprocess.run(cmd, check=False, capture_output=True, text=True)
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


def _normalize_controller_url(controller_url: str) -> str:
    clean_url = controller_url.strip().rstrip("/")
    parsed = urlparse(clean_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AgentError("Controller URL must include http:// or https:// and a host.")
    return clean_url


def _normalize_text(value: str, label: str) -> str:
    clean_value = value.strip()
    if not clean_value:
        raise AgentError(f"{label} cannot be empty.")
    return clean_value


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
