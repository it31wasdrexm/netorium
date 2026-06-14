import subprocess
import sys

from typer.testing import CliRunner

from netorium.cli.app import app

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
    assert "version" in result.output
    assert "doctor" in result.output


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert "Netorium CLI 0.1.0" in result.output


def test_python_module_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "netorium", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Netorium CLI for building-level network access control." in result.stdout
