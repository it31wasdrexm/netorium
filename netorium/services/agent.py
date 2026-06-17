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

DEFAULT_TIMEOUT_SECONDS = 10.0


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
    command_results = tuple(_execute_agent_command(command) for command in commands)
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


def _execute_agent_command(command: dict[str, Any]) -> AgentCommandExecution:
    command_id = _read_command_string(command, "command_id")
    command_type = _read_command_string(command, "command_type")
    payload = command.get("payload")
    if not isinstance(payload, dict):
        return AgentCommandExecution(
            command_id=command_id,
            status="failed",
            message="Agent command payload must be an object.",
        )

    if command_type != "firewall.ip":
        return AgentCommandExecution(
            command_id=command_id,
            status="failed",
            message=f"Unsupported agent command type: {command_type}",
        )

    try:
        return _execute_firewall_command(command_id, payload)
    except AgentError as exc:
        return AgentCommandExecution(
            command_id=command_id,
            status="failed",
            message=str(exc),
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


def _normalize_ip_address(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError as exc:
        raise AgentError(f"Invalid IP address: {value}") from exc


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
