import pytest
from typer.testing import CliRunner

from netorium.cli.app import app
from netorium.cli.commands import update as update_command
from netorium.services.update_checker import (
    DownloadInstructions,
    PlatformInstallInstructions,
    UpdateCheckError,
    UpdateConfig,
    UpdateInfo,
    build_platform_install_instructions,
)

runner = CliRunner()


def test_update_check_shows_available_release(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_command, "_run_update_check", _new_release)
    monkeypatch.setattr(update_command, "build_platform_install_instructions", _linux_platform)

    result = runner.invoke(app, ["update", "check"], terminal_width=160)

    assert result.exit_code == 0
    assert "Update available: 0.2.0" in result.output
    assert "Current version: 0.1.0" in result.output
    assert "Platform: Linux" in result.output
    assert "curl -fsSL" in result.output
    assert "raw.githubusercontent.com/it31wasdrexm/netorium/main/get.sh" in result.output
    assert "netorium-linux" in result.output
    assert "-x64" in result.output
    assert "pipx upgrade netorium-cli" in result.output


def test_update_check_shows_up_to_date(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_command, "_run_update_check", _current_release)

    result = runner.invoke(app, ["update", "check"])

    assert result.exit_code == 0
    assert "Netorium CLI is up to date: 0.1.0" in result.output


def test_update_show_renders_details(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_command, "_run_update_check", _new_release)
    monkeypatch.setattr(update_command, "build_platform_install_instructions", _linux_platform)

    result = runner.invoke(app, ["update", "show"])

    assert result.exit_code == 0
    assert "Netorium Update" in result.output
    assert "Latest version" in result.output
    assert "Recommended for Linux" in result.output
    assert "Standalone for this OS" in result.output
    assert "python -m pip install --upgrade netorium-cli" in result.output
    assert "Download Options" in result.output
    assert "netorium-windows-x64.exe" in result.output
    assert "docker run --rm -it ghcr.io/it31wasdrexm/netorium:latest" in result.output


def test_update_install_prints_manual_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_command, "_run_update_check", _new_release)

    result = runner.invoke(app, ["update", "install"])

    assert result.exit_code == 0
    assert "Update Install" in result.output
    assert "curl -fsSL" in result.output
    assert "raw.githubusercontent.com/it31wasdrexm/netorium/main/get.sh" in result.output
    assert "pipx upgrade netorium-cli" in result.output
    assert "python -m pip install --upgrade netorium-cli" in result.output
    assert "Download Options" in result.output
    assert "netorium-linux-x64" in result.output


def test_update_install_still_shows_downloads_when_check_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail() -> UpdateInfo:
        raise UpdateCheckError("release not found")

    monkeypatch.setattr(update_command, "_run_update_check", fail)

    result = runner.invoke(app, ["update", "install"])

    assert result.exit_code == 0
    assert "Update check unavailable" in result.output
    assert "release not found" in result.output
    assert "Download Options" in result.output
    assert "github.com/it31wasdrexm/netorium/releases/latest" in result.output


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
    assert "Download options" in result.output


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


def _linux_platform(instructions: DownloadInstructions) -> PlatformInstallInstructions:
    return build_platform_install_instructions(
        instructions,
        system_name="Linux",
        machine="x86_64",
    )
