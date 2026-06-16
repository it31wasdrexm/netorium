from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

import netorium.cli.agent as agent_module
from netorium.cli.agent import app
from netorium.services.agent import AgentRunResult, AgentState, enroll_agent
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
            message="Heartbeat accepted; no endpoint commands are queued yet.",
            controller_url="http://192.168.1.10:8765",
            accepted_at="2026-06-16T10:01:00+00:00",
        )

    monkeypatch.setattr(agent_module, "run_agent_once", fake_run_agent_once)

    result = runner.invoke(app, ["run"])

    assert result.exit_code == 0
    assert "Heartbeat accepted" in result.output
    assert "2026-06-16T10:01:00+00:00" in result.output
    assert "http://192.168.1.10:8765" in result.output


def test_agent_status_and_run_before_enroll(tmp_path: Path) -> None:
    env = isolated_user_env(tmp_path)

    status_result = runner.invoke(app, ["status"], env=env)
    run_result = runner.invoke(app, ["run"], env=env)

    assert status_result.exit_code == 0
    assert "no" in status_result.output
    assert "netorium-agent enroll" in status_result.output
    assert run_result.exit_code == 1
    assert "not enrolled" in run_result.output


def test_agent_service_and_update_commands() -> None:
    service_result = runner.invoke(app, ["service", "install"])
    update_result = runner.invoke(app, ["update", "check"])

    assert service_result.exit_code == 0
    assert "foreground heartbeat skeleton" in service_result.output
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
