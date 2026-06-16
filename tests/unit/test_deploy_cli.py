from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from netorium.cli.app import app
from netorium.core.settings import CONFIG_TEMPLATE
from tests.unit.path_helpers import isolated_config_dir, isolated_user_env

runner = CliRunner()


def test_deploy_instructions_require_controller_init(tmp_path: Path) -> None:
    env = _write_config(tmp_path)

    result = runner.invoke(app, ["deploy", "instructions"], env=env)

    assert result.exit_code == 1
    assert "Controller is not initialized" in result.output


def test_deploy_instructions_and_token_create(tmp_path: Path) -> None:
    env = _write_config(tmp_path)
    init_result = runner.invoke(
        app,
        ["controller", "init", "--host", "192.168.1.10", "--port", "8765"],
        env=env,
    )

    instructions_result = runner.invoke(app, ["deploy", "instructions"], env=env)
    token_result = runner.invoke(
        app,
        ["deploy", "token", "create", "--zone", "accounting", "--ttl", "24h"],
        env=env,
    )

    assert init_result.exit_code == 0
    assert instructions_result.exit_code == 0
    assert "Netorium Deployment" in instructions_result.output
    assert "http://192.168.1.10:8765" in instructions_result.output
    assert "netorium deploy token create --zone accounting --ttl 24h" in (
        instructions_result.output
    )
    assert "ENROLL_TOKEN" in instructions_result.output
    assert token_result.exit_code == 0
    assert "Enrollment token created." in token_result.output
    assert "Token (shown once):" in token_result.output
    assert "ng_enroll_" in token_result.output
    assert "netorium-agent enroll" in token_result.output


def test_deploy_script_commands_write_files(tmp_path: Path) -> None:
    env = _write_config(tmp_path)
    runner.invoke(
        app,
        ["controller", "init", "--host", "192.168.1.10", "--port", "8765"],
        env=env,
    )
    windows_output = tmp_path / "scripts" / "install-agent.ps1"
    linux_output = tmp_path / "scripts" / "install-agent.sh"

    windows_result = runner.invoke(
        app,
        [
            "deploy",
            "script",
            "windows",
            "--output",
            str(windows_output),
            "--token",
            "ng_enroll_test",
        ],
        env=env,
    )
    linux_result = runner.invoke(
        app,
        [
            "deploy",
            "script",
            "linux",
            "--output",
            str(linux_output),
            "--token",
            "ng_enroll_test",
        ],
        env=env,
    )

    assert windows_result.exit_code == 0
    assert "Wrote windows deploy script" in windows_result.output
    assert linux_result.exit_code == 0
    assert "Wrote linux deploy script" in linux_result.output
    assert "$Controller = 'http://192.168.1.10:8765'" in windows_output.read_text(
        encoding="utf-8"
    )
    assert "ng_enroll_test" in linux_output.read_text(encoding="utf-8")


def test_deploy_script_refuses_existing_output_without_force(tmp_path: Path) -> None:
    env = _write_config(tmp_path)
    runner.invoke(
        app,
        ["controller", "init", "--host", "192.168.1.10", "--port", "8765"],
        env=env,
    )
    output = tmp_path / "install-agent.ps1"
    output.write_text("existing", encoding="utf-8")

    result = runner.invoke(
        app,
        ["deploy", "script", "windows", "--output", str(output)],
        env=env,
    )

    assert result.exit_code == 1
    assert "already exists" in result.output


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
