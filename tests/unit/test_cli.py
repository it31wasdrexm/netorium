import subprocess
import sys

from typer.testing import CliRunner

from netgate.cli.app import app

runner = CliRunner()


def test_help_shows_main_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "NetGate CLI for building-level network access control." in result.output
    assert "version" in result.output
    assert "doctor" in result.output


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert "NetGate CLI 0.1.0" in result.output


def test_python_module_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "netgate", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "NetGate CLI for building-level network access control." in result.stdout
