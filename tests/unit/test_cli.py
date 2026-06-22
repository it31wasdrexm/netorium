import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

import netorium.cli.app as app_module
from netorium.cli.app import app
from netorium.core.metadata import APP_NAME, get_version
from netorium.core.settings import CONFIG_TEMPLATE
from netorium.services.update_checker import PlatformInstallInstructions, UpdateInfo
from netorium.services.update_notifications import StartupUpdateNotice
from tests.unit.path_helpers import (
    isolated_cache_dir,
    isolated_config_dir,
    isolated_data_dir,
    isolated_user_env,
)

runner = CliRunner()


def test_help_shows_main_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Netorium CLI for building-level network access control." in result.output
    assert "Quick start" in result.output
    assert "Controller" in result.output
    assert "Integrations" in result.output
    assert "config" in result.output
    assert "docs" in result.output
    assert "update" in result.output
    assert "controller" in result.output
    assert "deploy" in result.output
    assert "zone" in result.output
    assert "device" in result.output
    assert "firewall" in result.output
    assert "prtg" in result.output
    assert "ad" in result.output
    assert "telegram" in result.output
    assert "report" in result.output
    assert "audit" in result.output
    assert "agent" in result.output
    assert "uninstall" in result.output
    assert "unistall" not in result.output
    assert "version" in result.output
    assert "doctor" in result.output


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert f"{APP_NAME} {get_version()}" in result.output


def test_doctor_renders_status_table() -> None:
    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "Netorium Doctor" in result.output
    assert "Version" in result.output
    assert get_version() in result.output
    assert "Config path" in result.output


def test_interactive_shell_runs_commands_without_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "get_startup_update_notice", lambda: None)

    result = runner.invoke(app, [], input="version\nexit\n")

    assert result.exit_code == 0
    assert "Netorium Command Center" in result.output
    assert "Common Commands" in result.output
    assert "install-service" in result.output
    assert "update check" in result.output
    assert "netorium>" in result.output
    assert f"{APP_NAME} {get_version()}" in result.output
    assert "Leaving Netorium." in result.output


def test_interactive_shell_accepts_prefixed_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "get_startup_update_notice", lambda: None)

    result = runner.invoke(app, [], input="netorium version\nquit\n")

    assert result.exit_code == 0
    assert f"{APP_NAME} {get_version()}" in result.output


def test_interactive_shell_maps_help_to_command_help(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "get_startup_update_notice", lambda: None)

    result = runner.invoke(app, [], input="help config\nexit\n")

    assert result.exit_code == 0
    assert "Manage Netorium configuration." in result.output


def test_interactive_shell_shows_startup_update_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        app_module,
        "get_startup_update_notice",
        lambda: StartupUpdateNotice(
            info=UpdateInfo(
                current_version="0.1.0",
                latest_version="0.2.0",
                release_url="https://github.com/example/netorium/releases/tag/v0.2.0",
                source="github",
                install_command="pipx upgrade netorium-cli",
            ),
            platform=PlatformInstallInstructions(
                platform_name="Linux",
                install_command="curl -fsSL https://example.test/install.sh | bash",
                standalone_command="curl -fL -o ~/.local/bin/netorium https://example.test/netorium-linux-x64",
                standalone_asset="netorium-linux-x64",
            ),
        ),
    )

    result = runner.invoke(app, [], input="exit\n")

    assert result.exit_code == 0
    assert "Netorium Update Available" in result.output
    assert "0.1.0 ->" in result.output
    assert "0.2.0" in result.output
    assert "curl -fsSL https://example.test/install.sh | bash" in result.output


def test_interactive_shell_exits_after_uninstall(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "get_startup_update_notice", lambda: None)
    env = _write_uninstall_config(tmp_path)

    result = runner.invoke(
        app,
        [],
        env=env,
        input="uninstall --package-manager none --yes --remove-data\n",
    )

    assert result.exit_code == 0
    assert "Netorium uninstall completed." in result.output
    assert "Exiting Netorium." in result.output
    assert "Leaving Netorium." not in result.output


def test_uninstall_dry_run_shows_plan(tmp_path: Path) -> None:
    env = _write_uninstall_config(tmp_path)

    result = runner.invoke(app, ["uninstall", "--dry-run", "--package-manager", "none"], env=env)

    assert result.exit_code == 0
    assert "Netorium Uninstall" in result.output
    assert "Preview only" in result.output
    assert "netorium-cli" in result.output
    assert isolated_config_dir(tmp_path).exists() is True


def test_uninstall_guided_cancel_keeps_package_and_data(tmp_path: Path) -> None:
    env = _write_uninstall_config(tmp_path)

    result = runner.invoke(app, ["uninstall", "--package-manager", "none"], env=env, input="n\n")

    assert result.exit_code == 0
    assert "Uninstall Netorium now?" in result.output
    assert "Cancelled" in result.output
    assert isolated_config_dir(tmp_path).exists() is True


def test_uninstall_guided_remove_data(tmp_path: Path) -> None:
    env = _write_uninstall_config(tmp_path)

    result = runner.invoke(
        app,
        ["uninstall", "--package-manager", "none"],
        env=env,
        input="y\ny\n",
    )

    assert result.exit_code == 0
    assert "Remove Netorium config, database, and cache too?" in result.output
    assert "Netorium uninstall completed." in result.output
    assert isolated_config_dir(tmp_path).exists() is False
    assert isolated_data_dir(tmp_path).exists() is False
    assert isolated_cache_dir(tmp_path).exists() is False


def test_uninstall_remove_data_with_yes(tmp_path: Path) -> None:
    env = _write_uninstall_config(tmp_path)

    result = runner.invoke(
        app,
        ["uninstall", "--yes", "--remove-data", "--package-manager", "none"],
        env=env,
    )

    assert result.exit_code == 0
    assert "Netorium uninstall completed." in result.output
    assert isolated_config_dir(tmp_path).exists() is False
    assert isolated_data_dir(tmp_path).exists() is False
    assert isolated_cache_dir(tmp_path).exists() is False


def test_unistall_typo_alias_works(tmp_path: Path) -> None:
    env = _write_uninstall_config(tmp_path)

    result = runner.invoke(app, ["unistall", "--dry-run", "--package-manager", "none"], env=env)

    assert result.exit_code == 0
    assert "Netorium Uninstall" in result.output


def test_uninstall_accepts_unicode_dash_yes(tmp_path: Path) -> None:
    env = _write_uninstall_config(tmp_path)

    result = runner.invoke(app, ["uninstall", "—yes", "--package-manager", "none"], env=env)

    assert result.exit_code == 0
    assert "Uninstall Netorium now?" not in result.output
    assert "Netorium uninstall completed." in result.output


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
    config_dir = isolated_config_dir(tmp_path)
    data_dir = isolated_data_dir(tmp_path)
    cache_dir = isolated_cache_dir(tmp_path)
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
    return isolated_user_env(tmp_path)
