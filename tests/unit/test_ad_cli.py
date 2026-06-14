from pathlib import Path

import pytest
from typer.testing import CliRunner

from netorium.cli.app import app
from netorium.cli.commands import ad as ad_command
from netorium.core.settings import CONFIG_TEMPLATE
from netorium.services.ad_client import ActiveDirectoryError, ActiveDirectoryTestResult

runner = CliRunner()


def test_ad_test_renders_success_without_exposing_password(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _write_config(tmp_path)

    monkeypatch.setattr(
        ad_command,
        "test_active_directory_connection",
        lambda config: ActiveDirectoryTestResult(
            server=config.server,
            domain=config.domain,
            bind_user=config.bind_user,
            message="Bind successful",
        ),
    )

    result = runner.invoke(app, ["ad", "test"], env=env)

    assert result.exit_code == 0
    assert "Active Directory Test" in result.output
    assert "Active Directory connection OK" in result.output
    assert "ldap://dc01.corp.local" in result.output
    assert "secret-password" not in result.output


def test_ad_test_reports_placeholder_config(tmp_path: Path) -> None:
    config_home = tmp_path / "config"
    config_dir = config_home / "netorium"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text(CONFIG_TEMPLATE, encoding="utf-8")

    result = runner.invoke(app, ["ad", "test"], env={"XDG_CONFIG_HOME": str(config_home)})

    assert result.exit_code == 1
    assert "AD settings are not configured" in result.output
    assert "CHANGE_ME" not in result.output


def test_ad_test_reports_service_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _write_config(tmp_path)

    def fail(config: ad_command.ActiveDirectoryConfig) -> ActiveDirectoryTestResult:
        raise ActiveDirectoryError("AD connection failed. Check network access and AD settings.")

    monkeypatch.setattr(ad_command, "test_active_directory_connection", fail)

    result = runner.invoke(app, ["ad", "test"], env=env)

    assert result.exit_code == 1
    assert "AD connection failed" in result.output


def _write_config(tmp_path: Path) -> dict[str, str]:
    config_home = tmp_path / "config"
    database_path = tmp_path / "state" / "netorium.db"
    config_dir = config_home / "netorium"
    config_dir.mkdir(parents=True)
    config_text = CONFIG_TEMPLATE.replace(
        'database_path = "~/.local/share/netorium/netorium.db"',
        f'database_path = "{database_path.as_posix()}"',
    )
    config_text = config_text.replace(
        'server = "ldap://ad.example.local"',
        'server = "ldap://dc01.corp.local"',
    )
    config_text = config_text.replace('domain = "example.local"', 'domain = "corp.local"')
    config_text = config_text.replace(
        'bind_user = "CN=Netorium,CN=Users,DC=example,DC=local"',
        'bind_user = "CN=Netorium,CN=Users,DC=corp,DC=local"',
    )
    config_text = config_text.replace(
        'bind_password = "CHANGE_ME"',
        'bind_password = "secret-password"',
    )
    (config_dir / "config.toml").write_text(config_text, encoding="utf-8")
    return {"XDG_CONFIG_HOME": str(config_home)}
