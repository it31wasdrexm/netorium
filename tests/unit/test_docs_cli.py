import pytest
from typer.testing import CliRunner

from netorium.cli.app import app
from netorium.core import docs as docs_core

runner = CliRunner()


def test_docs_shows_index_page() -> None:
    result = runner.invoke(app, ["docs"])

    assert result.exit_code == 0
    assert "Netorium CLI" in result.output
    assert "Documentation Pages" in result.output


def test_docs_commands_page() -> None:
    result = runner.invoke(app, ["docs", "commands"])

    assert result.exit_code == 0
    assert "Commands" in result.output
    assert "Configuration" in result.output
    assert "interactive mode" in result.output
    assert "uninstall --yes --remove-data" in result.output
    assert "controller token create" in result.output
    assert "deploy script windows" in result.output
    assert "netorium-agent enroll" in result.output
    assert "sends a heartbeat" in result.output
    assert "shown only once" in result.output


def test_docs_examples_page() -> None:
    result = runner.invoke(app, ["docs", "examples"])

    assert result.exit_code == 0
    assert "Examples" in result.output
    assert "config validate" in result.output
    assert "netorium> version" in result.output
    assert "netorium uninstall" in result.output
    assert "netorium controller init" in result.output
    assert "netorium deploy instructions" in result.output
    assert "netorium-agent status" in result.output


def test_docs_install_page() -> None:
    result = runner.invoke(app, ["docs", "install"])

    assert result.exit_code == 0
    assert "Installation" in result.output
    assert "NETORIUM_GITHUB_REPO" in result.output
    assert "No-Python Options" in result.output
    assert "netorium-windows-x64.exe" in result.output
    assert "Docker" in result.output
    assert "Local Standalone Build" in result.output
    assert "Windows EXE on Windows" in result.output
    assert "RemoteSigned" in result.output
    assert "netorium version" in result.output
    assert "-NoInstallUser" in result.output
    assert "%LOCALAPPDATA%\\Netorium\\bin\\netorium.exe" in result.output
    assert "netorium deploy instructions" in result.output
    assert "netorium-agent enroll" in result.output
    assert "heartbeat checks" in result.output
    assert "build-windows.cmd" not in result.output
    assert ".venv-win" in result.output


def test_docs_troubleshooting_page() -> None:
    result = runner.invoke(app, ["docs", "troubleshooting"])

    assert result.exit_code == 0
    assert "Troubleshooting" in result.output
    assert "Config File Not Found" in result.output
    assert "Update Release Not Found" in result.output
    assert "Local Release Venv Fails" in result.output
    assert "Windows EXE Build" in result.output
    assert "Command Not Recognized" in result.output
    assert "RemoteSigned" in result.output
    assert "netorium version" in result.output
    assert "build-windows.cmd" not in result.output


def test_docs_missing_page_fails_gracefully(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(docs_core.DOC_PAGES, "index", "missing.md")

    result = runner.invoke(app, ["docs"])

    assert result.exit_code == 1
    assert "Documentation page is missing" in result.output
