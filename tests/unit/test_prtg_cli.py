from pathlib import Path

import pytest
from typer.testing import CliRunner

from netorium.cli.app import app
from netorium.cli.commands import prtg as prtg_command
from netorium.core.settings import CONFIG_TEMPLATE
from netorium.services.prtg_client import PrtgError, PrtgTestResult
from tests.unit.path_helpers import isolated_config_dir, isolated_user_env

runner = CliRunner()


def test_prtg_test_renders_success_without_exposing_passhash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _write_config(tmp_path)

    monkeypatch.setattr(
        prtg_command,
        "test_prtg_connection",
        lambda config: PrtgTestResult(
            base_url=config.base_url,
            status_code=200,
            message="OK",
        ),
    )

    result = runner.invoke(app, ["prtg", "test"], env=env, terminal_width=120)

    assert result.exit_code == 0
    assert "PRTG Test" in result.output
    assert "PRTG connection OK" in result.output
    assert "https://prtg.local" in result.output
    assert "secret-passhash" not in result.output


def test_prtg_test_reports_placeholder_config(tmp_path: Path) -> None:
    config_dir = isolated_config_dir(tmp_path)
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text(CONFIG_TEMPLATE, encoding="utf-8")

    result = runner.invoke(app, ["prtg", "test"], env=isolated_user_env(tmp_path))

    assert result.exit_code == 1
    assert "PRTG settings are not configured" in result.output
    assert "CHANGE_ME" not in result.output


def test_prtg_test_reports_service_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _write_config(tmp_path)

    def fail(config: prtg_command.PrtgConfig) -> PrtgTestResult:
        raise PrtgError("PRTG request failed. Check network access and PRTG settings.")

    monkeypatch.setattr(prtg_command, "test_prtg_connection", fail)

    result = runner.invoke(app, ["prtg", "test"], env=env)

    assert result.exit_code == 1
    assert "PRTG request failed" in result.output


def _write_config(tmp_path: Path) -> dict[str, str]:
    database_path = tmp_path / "state" / "netorium.db"
    config_dir = isolated_config_dir(tmp_path)
    config_dir.mkdir(parents=True)
    config_text = CONFIG_TEMPLATE.replace(
        'database_path = "~/.local/share/netorium/netorium.db"',
        f'database_path = "{database_path.as_posix()}"',
    )
    config_text = config_text.replace(
        'base_url = "https://prtg.example.local"',
        'base_url = "https://prtg.local"',
    )
    config_text = config_text.replace('passhash = "CHANGE_ME"', 'passhash = "secret-passhash"')
    (config_dir / "config.toml").write_text(config_text, encoding="utf-8")
    return isolated_user_env(tmp_path)
