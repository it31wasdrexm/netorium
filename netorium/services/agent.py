from __future__ import annotations

import json
import ipaddress
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urlparse

import requests

from netorium.core.platform import user_config_path
from netorium.services.command_signing import hash_shared_secret, verify_agent_command_signature

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
        raise AgentError(f"Agent is not enrolled. Run `netorium-agent enroll` first. State: {path}")

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


def service_action(action: str) -> str:
    clean_action = _normalize_text(action, "Service action")
    if clean_action not in {"install", "start", "stop"}:
        raise AgentError(f"Unsupported service action: {clean_action}")
    return (
        f"Agent service {clean_action} is not installed by this MVP yet. "
        "Use `netorium-agent run` for the foreground heartbeat skeleton."
    )


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
    except AgentError as exc:
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
        raise AgentError("Real endpoint firewall commands are not implemented yet.")

    return AgentCommandExecution(
        command_id=command_id,
        status="completed",
        message=f"Dry-run firewall {action} accepted for {ip_address}: {reason}",
    )


def _execute_site_command(command_id: str, payload: dict[str, Any]) -> AgentCommandExecution:
    action = _read_policy_action(payload, "Site policy action")
    domain = _normalize_domain(_read_payload_string(payload, "domain"))
    reason = _normalize_text(_read_payload_string(payload, "reason"), "Site policy reason")
    _require_dry_run(payload)

    return AgentCommandExecution(
        command_id=command_id,
        status="completed",
        message=f"Dry-run site {action} accepted for {domain}: {reason}",
    )


def _execute_app_command(command_id: str, payload: dict[str, Any]) -> AgentCommandExecution:
    action = _read_policy_action(payload, "Application network action")
    executable = _normalize_executable(_read_payload_string(payload, "executable"))
    reason = _normalize_text(_read_payload_string(payload, "reason"), "Application network reason")
    _require_dry_run(payload)

    return AgentCommandExecution(
        command_id=command_id,
        status="completed",
        message=f"Dry-run app {action} accepted for {executable}: {reason}",
    )


def _execute_speed_command(command_id: str, payload: dict[str, Any]) -> AgentCommandExecution:
    action = _read_payload_string(payload, "action").lower()
    reason = _normalize_text(_read_payload_string(payload, "reason"), "Speed policy reason")
    _require_dry_run(payload)

    if action == "clear":
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


def _require_dry_run(payload: dict[str, Any]) -> None:
    if payload.get("dry_run") is not True:
        raise AgentError("Real endpoint policy commands are not implemented yet.")


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
