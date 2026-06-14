import pytest
from typer.testing import CliRunner

from netorium.cli.app import app
from netorium.cli.commands import update as update_command
from netorium.services.update_checker import UpdateCheckError, UpdateInfo, UpdateConfig

runner = CliRunner()


def test_update_check_shows_available_release(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_command, "_run_update_check", _new_release)

    result = runner.invoke(app, ["update", "check"])

    assert result.exit_code == 0
    assert "Update available: 0.2.0" in result.output
    assert "Current version: 0.1.0" in result.output
    assert "pipx upgrade netorium-cli" in result.output


def test_update_check_shows_up_to_date(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_command, "_run_update_check", _current_release)

    result = runner.invoke(app, ["update", "check"])

    assert result.exit_code == 0
    assert "Netorium CLI is up to date: 0.1.0" in result.output


def test_update_show_renders_details(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_command, "_run_update_check", _new_release)

    result = runner.invoke(app, ["update", "show"])

    assert result.exit_code == 0
    assert "Netorium Update" in result.output
    assert "Latest version" in result.output
    assert "python -m pip install --upgrade netorium-cli" in result.output


def test_update_install_prints_manual_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_command, "_run_update_check", _new_release)

    result = runner.invoke(app, ["update", "install"])

    assert result.exit_code == 0
    assert "Automatic installation is not enabled yet." in result.output
    assert "pipx upgrade netorium-cli" in result.output
    assert "python -m pip install --upgrade netorium-cli" in result.output


def test_update_check_reports_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(config: UpdateConfig) -> UpdateInfo:
        raise UpdateCheckError("network is unavailable")

    monkeypatch.setattr(
        update_command,
        "_load_update_config",
        lambda: UpdateConfig(source="github", repo="example/netorium"),
    )
    monkeypatch.setattr(update_command, "check_for_update", fail)

    result = runner.invoke(app, ["update", "check"])

    assert result.exit_code == 1
    assert "network is unavailable" in result.output


def _new_release() -> UpdateInfo:
    return UpdateInfo(
        current_version="0.1.0",
        latest_version="0.2.0",
        release_url="https://github.com/example/netorium/releases/tag/v0.2.0",
        source="github",
        install_command="pipx upgrade netorium-cli",
    )


def _current_release() -> UpdateInfo:
    return UpdateInfo(
        current_version="0.1.0",
        latest_version="0.1.0",
        release_url="https://github.com/example/netorium/releases/tag/v0.1.0",
        source="github",
        install_command="pipx upgrade netorium-cli",
    )
