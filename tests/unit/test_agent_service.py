from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import requests

from netorium.services.command_signing import build_agent_command_signature, hash_shared_secret
from netorium.services.agent import (
    AgentError,
    enroll_agent,
    get_agent_status,
    load_agent_state,
    run_agent_once,
    service_action,
)


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: dict[str, Any],
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self.payload = payload
        self.text = text

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeClient:
    def __init__(
        self,
        response: FakeResponse | None = None,
        error: requests.RequestException | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def post(self, url: str, json: dict[str, Any], timeout: float) -> FakeResponse:
        self.requests.append((url, json))
        if self.error is not None:
            raise self.error
        if self.response is None:
            raise AssertionError("Fake response was not configured")
        return self.response


class SequenceClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def post(self, url: str, json: dict[str, Any], timeout: float) -> FakeResponse:
        self.requests.append((url, json))
        if not self.responses:
            raise AssertionError("No fake responses left")
        return self.responses.pop(0)


def test_agent_enroll_writes_local_state_without_printing_raw_enrollment_token(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "agent.json"
    client = FakeClient(
        FakeResponse(
            200,
            {
                "agent_id": "agt_123",
                "device_token": "ng_device_secret",
                "hostname": "pc-acc-01",
                "zone": "accounting",
                "enrolled_at": "2026-06-16T10:00:00+00:00",
            },
        )
    )

    state = enroll_agent(
        controller_url="http://192.168.1.10:8765/",
        token="ng_enroll_secret",
        hostname="pc-acc-01",
        state_path=state_path,
        client=client,
    )
    loaded = load_agent_state(state_path)
    status = get_agent_status(state_path)

    assert state.controller_url == "http://192.168.1.10:8765"
    assert client.requests == [
        (
            "http://192.168.1.10:8765/enroll",
            {"token": "ng_enroll_secret", "hostname": "pc-acc-01"},
        )
    ]
    assert loaded.agent_id == "agt_123"
    assert loaded.device_token == "ng_device_secret"
    assert status.enrolled is True
    assert status.agent_id == "agt_123"
    assert "ng_enroll_secret" not in state_path.read_text(encoding="utf-8")


def test_agent_status_reports_unenrolled_state(tmp_path: Path) -> None:
    status = get_agent_status(tmp_path / "missing-agent.json")

    assert status.enrolled is False
    assert status.agent_id is None


def test_agent_enroll_rejects_invalid_controller_url(tmp_path: Path) -> None:
    with pytest.raises(AgentError, match="Controller URL"):
        enroll_agent(
            controller_url="192.168.1.10:8765",
            token="ng_enroll_secret",
            state_path=tmp_path / "agent.json",
            client=FakeClient(FakeResponse(200, {})),
        )


def test_agent_enroll_reports_controller_failure(tmp_path: Path) -> None:
    client = FakeClient(FakeResponse(400, {"error": "bad"}, text="bad token"))

    with pytest.raises(AgentError, match="HTTP 400"):
        enroll_agent(
            controller_url="http://192.168.1.10:8765",
            token="ng_enroll_secret",
            state_path=tmp_path / "agent.json",
            client=client,
        )


def test_run_agent_once_requires_enrollment(tmp_path: Path) -> None:
    result = run_agent_once(tmp_path / "missing-agent.json")

    assert result.enrolled is False
    assert "not enrolled" in result.message


def test_run_agent_once_sends_heartbeat_without_printing_device_token(tmp_path: Path) -> None:
    state_path = tmp_path / "agent.json"
    enroll_agent(
        controller_url="http://192.168.1.10:8765",
        token="ng_enroll_secret",
        hostname="pc-acc-01",
        state_path=state_path,
        client=FakeClient(
            FakeResponse(
                200,
                {
                    "agent_id": "agt_123",
                    "device_token": "ng_device_secret",
                    "hostname": "pc-acc-01",
                    "zone": "accounting",
                    "enrolled_at": "2026-06-16T10:00:00+00:00",
                },
            )
        ),
    )
    heartbeat_client = FakeClient(
        FakeResponse(
            200,
            {
                "agent_id": "agt_123",
                "accepted_at": "2026-06-16T10:01:00+00:00",
                "commands": [],
            },
        )
    )

    result = run_agent_once(state_path, client=heartbeat_client)

    assert result.enrolled is True
    assert result.accepted_at == "2026-06-16T10:01:00+00:00"
    assert result.pending_commands == ()
    assert "Heartbeat accepted" in result.message
    assert heartbeat_client.requests == [
        (
            "http://192.168.1.10:8765/heartbeat",
            {"agent_id": "agt_123", "device_token": "ng_device_secret"},
        )
    ]


def test_run_agent_once_processes_dry_run_firewall_command(tmp_path: Path) -> None:
    state_path = tmp_path / "agent.json"
    enroll_agent(
        controller_url="http://192.168.1.10:8765",
        token="ng_enroll_secret",
        hostname="pc-acc-01",
        state_path=state_path,
        client=FakeClient(
            FakeResponse(
                200,
                {
                    "agent_id": "agt_123",
                    "device_token": "ng_device_secret",
                    "hostname": "pc-acc-01",
                    "zone": "accounting",
                    "enrolled_at": "2026-06-16T10:00:00+00:00",
                },
            )
        ),
    )
    client = SequenceClient(
        [
            FakeResponse(
                200,
                {
                    "agent_id": "agt_123",
                    "accepted_at": "2026-06-16T10:01:00+00:00",
                    "commands": [
                        _signed_command(
                            command_id="cmd_123",
                            command_type="firewall.ip",
                            payload={
                                "action": "block",
                                "dry_run": True,
                                "ip_address": "192.168.1.25",
                                "reason": "Policy test",
                            },
                            created_at="2026-06-16T10:00:30+00:00",
                        )
                    ],
                },
            ),
            FakeResponse(
                200,
                {
                    "agent_id": "agt_123",
                    "command_id": "cmd_123",
                    "status": "completed",
                    "completed_at": "2026-06-16T10:01:01+00:00",
                },
            ),
        ]
    )

    result = run_agent_once(state_path, client=client)

    assert result.message == "Heartbeat accepted; processed 1 endpoint command(s)."
    assert result.command_results[0].command_id == "cmd_123"
    assert result.command_results[0].status == "completed"
    assert "Dry-run firewall block accepted" in result.command_results[0].message
    assert client.requests == [
        (
            "http://192.168.1.10:8765/heartbeat",
            {"agent_id": "agt_123", "device_token": "ng_device_secret"},
        ),
        (
            "http://192.168.1.10:8765/command-result",
            {
                "agent_id": "agt_123",
                "device_token": "ng_device_secret",
                "command_id": "cmd_123",
                "status": "completed",
                "message": "Dry-run firewall block accepted for 192.168.1.25: Policy test",
            },
        ),
    ]


def test_run_agent_once_processes_site_app_and_speed_policy_commands(tmp_path: Path) -> None:
    state_path = tmp_path / "agent.json"
    enroll_agent(
        controller_url="http://192.168.1.10:8765",
        token="ng_enroll_secret",
        hostname="pc-game-01",
        state_path=state_path,
        client=FakeClient(
            FakeResponse(
                200,
                {
                    "agent_id": "agt_123",
                    "device_token": "ng_device_secret",
                    "hostname": "pc-game-01",
                    "zone": "gaming-room",
                    "enrolled_at": "2026-06-16T10:00:00+00:00",
                },
            )
        ),
    )
    client = SequenceClient(
        [
            FakeResponse(
                200,
                {
                    "agent_id": "agt_123",
                    "accepted_at": "2026-06-16T10:01:00+00:00",
                    "commands": [
                        _signed_command(
                            command_id="cmd_site",
                            command_type="network.site",
                            payload={
                                "action": "block",
                                "dry_run": True,
                                "domain": "*.youtube.com",
                                "reason": "Class policy",
                            },
                            created_at="2026-06-16T10:00:30+00:00",
                        ),
                        _signed_command(
                            command_id="cmd_app",
                            command_type="network.app",
                            payload={
                                "action": "block",
                                "dry_run": True,
                                "executable": "dota2.exe",
                                "reason": "No game traffic",
                            },
                            created_at="2026-06-16T10:00:31+00:00",
                        ),
                        _signed_command(
                            command_id="cmd_speed",
                            command_type="network.speed",
                            payload={
                                "action": "limit",
                                "download_kbps": 2048,
                                "upload_kbps": 512,
                                "dry_run": True,
                                "reason": "Temporary limit",
                            },
                            created_at="2026-06-16T10:00:32+00:00",
                        ),
                    ],
                },
            ),
            FakeResponse(200, {"status": "completed"}),
            FakeResponse(200, {"status": "completed"}),
            FakeResponse(200, {"status": "completed"}),
        ]
    )

    result = run_agent_once(state_path, client=client)

    assert result.message == "Heartbeat accepted; processed 3 endpoint command(s)."
    assert [command.status for command in result.command_results] == [
        "completed",
        "completed",
        "completed",
    ]
    assert "Dry-run site block accepted for *.youtube.com" in result.command_results[0].message
    assert "Dry-run app block accepted for dota2.exe" in result.command_results[1].message
    assert "download=2048kbps upload=512kbps" in result.command_results[2].message
    assert [request[1]["command_id"] for request in client.requests[1:]] == [
        "cmd_site",
        "cmd_app",
        "cmd_speed",
    ]


def test_run_agent_once_rejects_real_firewall_command_on_non_windows(tmp_path: Path) -> None:
    state_path = tmp_path / "agent.json"
    enroll_agent(
        controller_url="http://192.168.1.10:8765",
        token="ng_enroll_secret",
        hostname="pc-acc-01",
        state_path=state_path,
        client=FakeClient(
            FakeResponse(
                200,
                {
                    "agent_id": "agt_123",
                    "device_token": "ng_device_secret",
                    "hostname": "pc-acc-01",
                    "zone": "accounting",
                    "enrolled_at": "2026-06-16T10:00:00+00:00",
                },
            )
        ),
    )
    client = SequenceClient(
        [
            FakeResponse(
                200,
                {
                    "agent_id": "agt_123",
                    "accepted_at": "2026-06-16T10:01:00+00:00",
                    "commands": [
                        _signed_command(
                            command_id="cmd_123",
                            command_type="firewall.ip",
                            payload={
                                "action": "block",
                                "dry_run": False,
                                "ip_address": "192.168.1.25",
                                "reason": "Policy test",
                            },
                            created_at="2026-06-16T10:00:30+00:00",
                        )
                    ],
                },
            ),
            FakeResponse(200, {"status": "failed"}),
        ]
    )

    result = run_agent_once(state_path, client=client)

    assert result.command_results[0].status == "failed"
    assert result.command_results[0].message == "Real endpoint policy commands are Windows-only."


def test_run_agent_once_rejects_unsigned_or_tampered_command(tmp_path: Path) -> None:
    state_path = tmp_path / "agent.json"
    enroll_agent(
        controller_url="http://192.168.1.10:8765",
        token="ng_enroll_secret",
        hostname="pc-acc-01",
        state_path=state_path,
        client=FakeClient(
            FakeResponse(
                200,
                {
                    "agent_id": "agt_123",
                    "device_token": "ng_device_secret",
                    "hostname": "pc-acc-01",
                    "zone": "accounting",
                    "enrolled_at": "2026-06-16T10:00:00+00:00",
                },
            )
        ),
    )
    client = SequenceClient(
        [
            FakeResponse(
                200,
                {
                    "agent_id": "agt_123",
                    "accepted_at": "2026-06-16T10:01:00+00:00",
                    "commands": [
                        {
                            "command_id": "cmd_123",
                            "command_type": "firewall.ip",
                            "payload": {
                                "action": "block",
                                "dry_run": True,
                                "ip_address": "192.168.1.25",
                                "reason": "Policy test",
                            },
                            "signature": "bad-signature",
                            "created_at": "2026-06-16T10:00:30+00:00",
                        }
                    ],
                },
            ),
            FakeResponse(200, {"status": "failed"}),
        ]
    )

    result = run_agent_once(state_path, client=client)

    assert result.command_results[0].status == "failed"
    assert result.command_results[0].message == "Agent command signature is invalid."
    assert client.requests[1][1]["message"] == "Agent command signature is invalid."


def test_service_action_rejects_unknown_actions() -> None:
    with pytest.raises(AgentError, match="Unsupported"):
        service_action("restart")


def _signed_command(
    *,
    command_id: str,
    command_type: str,
    payload: dict[str, Any],
    created_at: str,
) -> dict[str, Any]:
    signing_key = hash_shared_secret("ng_device_secret", label="Device token")
    return {
        "command_id": command_id,
        "command_type": command_type,
        "payload": payload,
        "signature": build_agent_command_signature(
            signing_key=signing_key,
            agent_id="agt_123",
            command_id=command_id,
            command_type=command_type,
            payload=payload,
            created_at=created_at,
        ),
        "created_at": created_at,
    }
