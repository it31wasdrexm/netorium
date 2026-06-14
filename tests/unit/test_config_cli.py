from pathlib import Path

from typer.testing import CliRunner

from netorium.cli.app import app

runner = CliRunner()


def test_config_path_uses_os_config_directory(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["config", "path"],
        env={"XDG_CONFIG_HOME": str(tmp_path)},
    )

    assert result.exit_code == 0
    assert str(tmp_path / "netorium" / "config.toml") in result.output


def test_config_init_show_and_validate(tmp_path: Path) -> None:
    env = {"XDG_CONFIG_HOME": str(tmp_path)}

    init_result = runner.invoke(app, ["config", "init"], env=env)
    show_result = runner.invoke(app, ["config", "show"], env=env)
    validate_result = runner.invoke(app, ["config", "validate"], env=env)

    assert init_result.exit_code == 0
    assert (tmp_path / "netorium" / "config.toml").exists()
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
        env={"XDG_CONFIG_HOME": str(tmp_path)},
    )

    assert result.exit_code == 1
    assert "Config file not found" in result.output
