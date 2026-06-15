from pathlib import Path

from typer.testing import CliRunner

from netorium.cli.app import app
from tests.unit.path_helpers import isolated_config_path, isolated_user_env

runner = CliRunner()


def test_config_path_uses_os_config_directory(tmp_path: Path) -> None:
    env = isolated_user_env(tmp_path)

    result = runner.invoke(
        app,
        ["config", "path"],
        env=env,
    )

    assert result.exit_code == 0
    assert str(isolated_config_path(tmp_path)) in result.output


def test_config_init_show_and_validate(tmp_path: Path) -> None:
    env = isolated_user_env(tmp_path)

    init_result = runner.invoke(app, ["config", "init"], env=env)
    show_result = runner.invoke(app, ["config", "show"], env=env)
    validate_result = runner.invoke(app, ["config", "validate"], env=env)

    assert init_result.exit_code == 0
    assert isolated_config_path(tmp_path).exists()
    assert show_result.exit_code == 0
    assert "bot_token" in show_result.output
    assert "********" in show_result.output
    assert "CHANGE_ME" not in show_result.output
    assert validate_result.exit_code == 0
    assert "Config is valid" in validate_result.output


def test_config_validate_reports_missing_config(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["config", "validate"],
        env=isolated_user_env(tmp_path),
    )

    assert result.exit_code == 1
    assert "Config file not found" in result.output
