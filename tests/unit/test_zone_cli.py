from pathlib import Path

from typer.testing import CliRunner

from netorium.cli.app import app
from netorium.core.settings import CONFIG_TEMPLATE

runner = CliRunner()


def test_zone_add_list_show_delete_and_audit(tmp_path: Path) -> None:
    env = _write_config(tmp_path)

    add_result = runner.invoke(
        app,
        [
            "zone",
            "add",
            "accounting",
            "--floor",
            "3",
            "--department",
            "Accounting",
            "--description",
            "Third floor",
        ],
        env=env,
    )
    list_result = runner.invoke(app, ["zone", "list"], env=env)
    show_result = runner.invoke(app, ["zone", "show", "accounting"], env=env)
    audit_result = runner.invoke(app, ["audit", "list"], env=env)
    delete_result = runner.invoke(app, ["zone", "delete", "accounting"], env=env)
    empty_list_result = runner.invoke(app, ["zone", "list"], env=env)

    assert add_result.exit_code == 0
    assert "Added zone: accounting" in add_result.output
    assert list_result.exit_code == 0
    assert "accounting" in list_result.output
    assert "Accounting" in list_result.output
    assert show_result.exit_code == 0
    assert "Third floor" in show_result.output
    assert audit_result.exit_code == 0
    assert "zone.add" in audit_result.output
    assert delete_result.exit_code == 0
    assert "Deleted zone: accounting" in delete_result.output
    assert empty_list_result.exit_code == 0
    assert "No zones found" in empty_list_result.output


def test_zone_command_reports_missing_config(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["zone", "list"],
        env={"XDG_CONFIG_HOME": str(tmp_path / "missing-config")},
    )

    assert result.exit_code == 1
    assert "Config file not found" in result.output


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
