import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from netorium.cli.app import app
from netorium.core.settings import CONFIG_TEMPLATE

runner = CliRunner()


def test_help_shows_main_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Netorium CLI for building-level network access control." in result.output
    assert "config" in result.output
    assert "docs" in result.output
    assert "update" in result.output
    assert "zone" in result.output
    assert "device" in result.output
    assert "firewall" in result.output
    assert "prtg" in result.output
    assert "ad" in result.output
    assert "telegram" in result.output
    assert "audit" in result.output
    assert "uninstall" in result.output
    assert "unistall" not in result.output
    assert "version" in result.output
    assert "doctor" in result.output


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert "Netorium CLI 0.1.0" in result.output


def test_interactive_shell_runs_commands_without_prefix() -> None:
    result = runner.invoke(app, [], input="version\nexit\n")

    assert result.exit_code == 0
    assert "Netorium interactive mode." in result.output
    assert "netorium>" in result.output
    assert "Netorium CLI 0.1.0" in result.output
    assert "Leaving Netorium." in result.output


def test_interactive_shell_accepts_prefixed_commands() -> None:
    result = runner.invoke(app, [], input="netorium version\nquit\n")

    assert result.exit_code == 0
    assert "Netorium CLI 0.1.0" in result.output


def test_interactive_shell_maps_help_to_command_help() -> None:
    result = runner.invoke(app, [], input="help config\nexit\n")

    assert result.exit_code == 0
    assert "Manage Netorium configuration." in result.output


def test_uninstall_dry_run_shows_plan(tmp_path: Path) -> None:
    env = _write_uninstall_config(tmp_path)

    result = runner.invoke(app, ["uninstall", "--package-manager", "none"], env=env)

    assert result.exit_code == 0
    assert "Netorium Uninstall" in result.output
    assert "Dry run only" in result.output
    assert "netorium-cli" in result.output
    assert (tmp_path / "config" / "netorium").exists() is True


def test_uninstall_remove_data_with_yes(tmp_path: Path) -> None:
    env = _write_uninstall_config(tmp_path)

    result = runner.invoke(
        app,
        ["uninstall", "--yes", "--remove-data", "--package-manager", "none"],
        env=env,
    )

    assert result.exit_code == 0
    assert "Netorium uninstall completed." in result.output
    assert (tmp_path / "config" / "netorium").exists() is False
    assert (tmp_path / "data" / "netorium").exists() is False
    assert (tmp_path / "cache" / "netorium").exists() is False


def test_unistall_typo_alias_works(tmp_path: Path) -> None:
    env = _write_uninstall_config(tmp_path)

    result = runner.invoke(app, ["unistall", "--package-manager", "none"], env=env)

    assert result.exit_code == 0
    assert "Netorium Uninstall" in result.output


def test_python_module_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "netorium", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Netorium CLI for building-level network access control." in result.stdout


def _write_uninstall_config(tmp_path: Path) -> dict[str, str]:
    config_dir = tmp_path / "config" / "netorium"
    data_dir = tmp_path / "data" / "netorium"
    cache_dir = tmp_path / "cache" / "netorium"
    config_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    cache_dir.mkdir(parents=True)
    database_path = data_dir / "netorium.db"
    config_text = CONFIG_TEMPLATE.replace(
        'database_path = "~/.local/share/netorium/netorium.db"',
        f'database_path = "{database_path.as_posix()}"',
    )
    (config_dir / "config.toml").write_text(config_text, encoding="utf-8")
    database_path.write_text("database", encoding="utf-8")
    (cache_dir / "cache.txt").write_text("cache", encoding="utf-8")
    return {
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
    }
