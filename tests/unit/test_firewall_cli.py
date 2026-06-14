from pathlib import Path

from typer.testing import CliRunner

from netorium.cli.app import app
from netorium.core.settings import CONFIG_TEMPLATE

runner = CliRunner()


def test_firewall_status() -> None:
    result = runner.invoke(app, ["firewall", "status"])

    assert result.exit_code == 0
    assert "Firewall Status" in result.output
    assert "Dry-run supported" in result.output


def test_firewall_block_dry_run_and_audit(tmp_path: Path) -> None:
    env = _write_config(tmp_path)

    block_result = runner.invoke(
        app,
        [
            "firewall",
            "block",
            "192.168.1.25",
            "--reason",
            "Policy violation",
            "--dry-run",
        ],
        env=env,
    )
    audit_result = runner.invoke(app, ["audit", "list"], env=env)

    assert block_result.exit_code == 0
    assert "Firewall block" in block_result.output
    assert "Dry run only" in block_result.output
    assert "New-NetFirewallRule" in block_result.output
    assert audit_result.exit_code == 0
    assert "firewall.block.dry_run" in audit_result.output


def test_firewall_unblock_dry_run(tmp_path: Path) -> None:
    env = _write_config(tmp_path)

    result = runner.invoke(
        app,
        [
            "firewall",
            "unblock",
            "192.168.1.25",
            "--reason",
            "Access restored",
            "--dry-run",
        ],
        env=env,
    )

    assert result.exit_code == 0
    assert "Firewall unblock" in result.output
    assert "Remove-NetFirewallRule" in result.output


def test_firewall_block_requires_reason(tmp_path: Path) -> None:
    env = _write_config(tmp_path)

    result = runner.invoke(app, ["firewall", "block", "192.168.1.25"], env=env)

    assert result.exit_code != 0
    assert "--reason" in result.output


def test_firewall_real_mode_fails_safely_on_non_windows(tmp_path: Path) -> None:
    env = _write_config(tmp_path)

    result = runner.invoke(
        app,
        [
            "firewall",
            "block",
            "192.168.1.25",
            "--reason",
            "Policy violation",
            "--real",
            "--yes",
        ],
        env=env,
    )

    assert result.exit_code == 1
    assert "Windows-only" in result.output or "not implemented yet" in result.output


def _write_config(tmp_path: Path) -> dict[str, str]:
    config_home = tmp_path / "config"
    database_path = tmp_path / "state" / "netorium.db"
    config_dir = config_home / "netorium"
    config_dir.mkdir(parents=True)
    config_text = CONFIG_TEMPLATE.replace(
        'database_path = "~/.local/share/netorium/netorium.db"',
        f'database_path = "{database_path.as_posix()}"',
    )
    (config_dir / "config.toml").write_text(config_text, encoding="utf-8")
    return {"XDG_CONFIG_HOME": str(config_home)}
