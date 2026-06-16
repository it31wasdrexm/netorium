from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from netorium.cli.app import app
from netorium.core.settings import CONFIG_TEMPLATE
from netorium.services.controller import create_enrollment_token, enroll_agent
from tests.unit.path_helpers import isolated_config_dir, isolated_user_env

runner = CliRunner()


def test_controller_status_before_init(tmp_path: Path) -> None:
    env = _write_config(tmp_path)

    result = runner.invoke(app, ["controller", "status"], env=env)

    assert result.exit_code == 0
    assert "Netorium Controller" in result.output
    assert "Initialized" in result.output
    assert "no" in result.output
    assert "netorium controller init" in result.output


def test_controller_init_status_and_token_create(tmp_path: Path) -> None:
    env = _write_config(tmp_path)

    init_result = runner.invoke(
        app,
        ["controller", "init", "--host", "0.0.0.0", "--port", "8765"],
        env=env,
    )
    status_result = runner.invoke(app, ["controller", "status"], env=env)
    token_result = runner.invoke(
        app,
        ["controller", "token", "create", "--zone", "accounting", "--ttl", "24h"],
        env=env,
    )
    audit_result = runner.invoke(app, ["audit", "list"], env=env)

    assert init_result.exit_code == 0
    assert "Netorium Controller initialized." in init_result.output
    assert "Enrollment URL" in init_result.output
    assert status_result.exit_code == 0
    assert "Initialized" in status_result.output
    assert "yes" in status_result.output
    assert "http://0.0.0.0:8765" in status_result.output
    assert token_result.exit_code == 0
    assert "Enrollment token created." in token_result.output
    assert "accounting" in token_result.output
    assert "Token (shown once):" in token_result.output
    assert "ng_enroll_" in token_result.output
    assert audit_result.exit_code == 0
    assert "controller.token.create" in audit_result.output


def test_controller_token_requires_init(tmp_path: Path) -> None:
    env = _write_config(tmp_path)

    result = runner.invoke(
        app,
        ["controller", "token", "create", "--zone", "accounting"],
        env=env,
    )

    assert result.exit_code == 1
    assert "Controller is not initialized" in result.output


def test_controller_agent_list_shows_enrolled_agents(tmp_path: Path) -> None:
    env = _write_config(tmp_path)
    database_path = tmp_path / "state" / "netorium.db"
    runner.invoke(
        app,
        ["controller", "init", "--host", "192.168.1.10", "--port", "8765"],
        env=env,
    )
    token = create_enrollment_token(database_path, zone="accounting", ttl="24h")
    enrollment = enroll_agent(database_path, token=token.token, hostname="pc-acc-01")

    result = runner.invoke(app, ["controller", "agent", "list"], env=env)

    assert result.exit_code == 0
    assert "Netorium Agents" in result.output
    assert enrollment.agent_id.startswith("agt_")
    assert "agt_" in result.output
    assert "pc-acc-01" in result.output
    assert "accounting" in result.output


def _write_config(tmp_path: Path) -> dict[str, str]:
    database_path = tmp_path / "state" / "netorium.db"
    config_dir = isolated_config_dir(tmp_path)
    config_dir.mkdir(parents=True)
    config_text = CONFIG_TEMPLATE.replace(
        'database_path = "~/.local/share/netorium/netorium.db"',
        f'database_path = "{database_path.as_posix()}"',
    )
    (config_dir / "config.toml").write_text(config_text, encoding="utf-8")
    return isolated_user_env(tmp_path)
