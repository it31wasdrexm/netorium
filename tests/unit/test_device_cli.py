from pathlib import Path

from typer.testing import CliRunner

from netorium.cli.app import app
from netorium.core.settings import CONFIG_TEMPLATE
from tests.unit.path_helpers import isolated_config_dir, isolated_user_env

runner = CliRunner()


def test_device_add_list_show_move_delete_and_audit(tmp_path: Path) -> None:
    env = _write_config(tmp_path)

    accounting_result = runner.invoke(app, ["zone", "add", "accounting"], env=env)
    reception_result = runner.invoke(app, ["zone", "add", "reception"], env=env)
    add_result = runner.invoke(
        app,
        [
            "device",
            "add",
            "192.168.1.25",
            "--zone",
            "accounting",
            "--hostname",
            "pc-acc-01",
        ],
        env=env,
    )
    list_result = runner.invoke(app, ["device", "list"], env=env)
    show_result = runner.invoke(app, ["device", "show", "192.168.1.25"], env=env)
    move_result = runner.invoke(
        app,
        ["device", "move", "192.168.1.25", "--zone", "reception"],
        env=env,
    )
    audit_result = runner.invoke(app, ["audit", "list"], env=env)
    delete_result = runner.invoke(app, ["device", "delete", "192.168.1.25"], env=env)
    empty_list_result = runner.invoke(app, ["device", "list"], env=env)

    assert accounting_result.exit_code == 0
    assert reception_result.exit_code == 0
    assert add_result.exit_code == 0
    assert "Added device: 192.168.1.25" in add_result.output
    assert list_result.exit_code == 0
    assert "192.168.1.25" in list_result.output
    assert "accounting" in list_result.output
    assert show_result.exit_code == 0
    assert "pc-acc-01" in show_result.output
    assert move_result.exit_code == 0
    assert "Moved device 192.168.1.25 to zone: reception" in move_result.output
    assert audit_result.exit_code == 0
    assert "device.move" in audit_result.output
    assert delete_result.exit_code == 0
    assert "Deleted device: 192.168.1.25" in delete_result.output
    assert empty_list_result.exit_code == 0
    assert "No devices found" in empty_list_result.output


def test_device_add_reports_invalid_ip(tmp_path: Path) -> None:
    env = _write_config(tmp_path)
    runner.invoke(app, ["zone", "add", "accounting"], env=env)

    result = runner.invoke(
        app,
        ["device", "add", "not-an-ip", "--zone", "accounting"],
        env=env,
    )

    assert result.exit_code == 1
    assert "Invalid IP address" in result.output


def _write_config(tmp_path: Path) -> dict[str, str]:
    database_path = tmp_path / "state" / "netorium.db"
    config_dir = isolated_config_dir(tmp_path)
    config_dir.mkdir(parents=True)
    config_text = CONFIG_TEMPLATE.replace(
        'database_path = "~/.local/share/netorium/netorium.db"',
        f'database_path = "{database_path.as_posix()}"',
    )
    (config_dir / "config.toml").write_text(config_text, encoding="utf-8")
    return isolated_user_env(tmp_path)
