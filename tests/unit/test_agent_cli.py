from __future__ import annotations

from pathlib import Path

import requests
from typer.testing import CliRunner

import netorium.cli.agent as agent_module
import netorium.services.agent as agent_service
from netorium.cli.agent import app
from netorium.services.agent import AgentCommandExecution, AgentRunResult, AgentState, enroll_agent
from tests.unit.path_helpers import isolated_user_env

runner = CliRunner()


def test_agent_help_shows_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Netorium endpoint agent" in result.output
    assert "enroll" in result.output
    assert "status" in result.output
    assert "run" in result.output
    assert "service" in result.output
    assert "update" in result.output


def test_agent_enroll_does_not_print_tokens(
    monkeypatch,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "agent.json"

    def fake_enroll_agent(
        *,
        controller_url: str,
        token: str,
        hostname: str | None = None,
    ) -> AgentState:
        return AgentState(
            controller_url=controller_url,
            agent_id="agt_123",
            hostname=hostname or "pc-acc-01",
            zone="accounting",
            device_token="ng_device_secret",
            enrolled_at="2026-06-16T10:00:00+00:00",
            state_path=state_path,
        )

    monkeypatch.setattr(agent_module, "enroll_agent", fake_enroll_agent)
    monkeypatch.setattr(
        agent_module,
        "try_provision_agent_background_service",
        lambda: None,
    )

    result = runner.invoke(
        app,
        [
            "enroll",
            "--controller",
            "http://192.168.1.10:8765",
            "--token",
            "ng_enroll_secret",
            "--hostname",
            "pc-acc-01",
        ],
    )

    assert result.exit_code == 0
    assert "Netorium Agent enrolled." in result.output
    assert "agt_123" in result.output
    assert "pc-acc-01" in result.output
    assert "ng_enroll_secret" not in result.output
    assert "ng_device_secret" not in result.output


def test_agent_status_and_run_after_enroll(tmp_path: Path) -> None:
    _write_agent_state(tmp_path)
    env = isolated_user_env(tmp_path)

    status_result = runner.invoke(app, ["status"], env=env)

    assert status_result.exit_code == 0
    assert "Enrolled" in status_result.output
    assert "yes" in status_result.output
    assert "agt_123" in status_result.output
    assert "State" in status_result.output
    assert "ng_device_secret" not in status_result.output


def test_agent_run_sends_heartbeat(monkeypatch) -> None:
    def fake_run_agent_once():
        return AgentRunResult(
            enrolled=True,
            message="Heartbeat accepted; processed 1 endpoint command(s).",
            controller_url="http://192.168.1.10:8765",
            accepted_at="2026-06-16T10:01:00+00:00",
            command_results=(
                AgentCommandExecution(
                    command_id="cmd_123",
                    status="completed",
                    message="Dry-run firewall block accepted for 192.168.1.25: Policy test",
                ),
            ),
        )

    monkeypatch.setattr(agent_module, "run_agent_once", fake_run_agent_once)

    result = runner.invoke(app, ["run"])

    assert result.exit_code == 0
    assert "Heartbeat accepted" in result.output
    assert "2026-06-16T10:01:00+00:00" in result.output
    assert "http://192.168.1.10:8765" in result.output
    assert "cmd_123: completed" in result.output
    assert "192.168.1.25" in result.output


def test_agent_status_and_run_before_enroll(tmp_path: Path) -> None:
    env = isolated_user_env(tmp_path)

    status_result = runner.invoke(app, ["status"], env=env)
    run_result = runner.invoke(app, ["run"], env=env)

    assert status_result.exit_code == 0
    assert "no" in status_result.output
    assert "netorium agent enroll" in status_result.output
    assert run_result.exit_code == 1
    assert "not enrolled" in run_result.output


def test_agent_enroll_timeout_explains_lan_diagnostics(monkeypatch) -> None:
    class TimeoutClient:
        def post(self, url: str, json: dict[str, str], timeout: float):
            raise requests.Timeout("connection timed out")

    monkeypatch.setattr(agent_service, "_default_http_client", lambda: TimeoutClient())

    result = runner.invoke(
        app,
        [
            "enroll",
            "--controller",
            "http://10.202.185.108:8765",
            "--token",
            "ng_enroll_secret",
        ],
    )

    assert result.exit_code == 1
    assert "not a token problem" in result.output
    assert "curl http://10.202.185.108:8765/health" in result.output
    assert "Test-NetConnection 10.202.185.108 -Port 8765" in result.output
    assert "client isolation" in result.output


def test_agent_service_and_update_commands(monkeypatch) -> None:
    import netorium.cli.agent as agent_cli_module

    monkeypatch.setattr(agent_cli_module, "service_action", lambda action: f"Service {action} OK")

    service_result = runner.invoke(app, ["service", "install"])
    update_result = runner.invoke(app, ["update", "check"])

    assert service_result.exit_code == 0
    assert "Service install OK" in service_result.output
    assert update_result.exit_code == 0
    assert "Netorium Agent" in update_result.output
    assert "netorium update show" in update_result.output


def _write_agent_state(tmp_path: Path) -> Path:
    state_path = tmp_path / "config" / "netorium" / "agent.json"
    state = enroll_agent(
        controller_url="http://192.168.1.10:8765",
        token="ng_enroll_secret",
        hostname="pc-acc-01",
        state_path=state_path,
        client=_FakeClient(),
    )
    return state.state_path


class _FakeResponse:
    status_code = 200
    text = ""

    def json(self) -> dict[str, str]:
        return {
            "agent_id": "agt_123",
            "device_token": "ng_device_secret",
            "hostname": "pc-acc-01",
            "zone": "accounting",
            "enrolled_at": "2026-06-16T10:00:00+00:00",
        }


class _FakeClient:
    def post(self, url: str, json: dict[str, str], timeout: float) -> _FakeResponse:
        return _FakeResponse()
