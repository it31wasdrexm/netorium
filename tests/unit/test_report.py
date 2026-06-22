from __future__ import annotations

from pathlib import Path
from typer.testing import CliRunner

from netorium.cli.app import app
from netorium.services.traffic import get_traffic_report
from netorium.services.controller import create_enrollment_token, enroll_agent
from netorium.core.settings import CONFIG_TEMPLATE
from tests.unit.path_helpers import isolated_config_dir, isolated_user_env

runner = CliRunner()

def _write_config(tmp_path: Path) -> dict[str, str]:
    database_path = tmp_path / "state" / "netorium.db"
    config_dir = isolated_config_dir(tmp_path)
    config_dir.mkdir(parents=True)
    config_text = CONFIG_TEMPLATE.replace(
        'database_path = "~/.local/share/netorium/netorium.db"',
        f'database_path = "{database_path.as_posix()}"',
    )
    (config_dir / "config.toml").write_text(config_text, encoding="utf-8")
    env = isolated_user_env(tmp_path)
    env["COLUMNS"] = "200"
    return env

def test_traffic_report_generation_and_cli(tmp_path: Path) -> None:
    env = _write_config(tmp_path)
    database_path = tmp_path / "state" / "netorium.db"
    
    # Initialize controller to setup the database
    runner.invoke(
        app,
        ["controller", "init", "--host", "192.168.1.10", "--port", "8765"],
        env=env,
    )
    
    # Enroll some agents to produce reports
    token_one = create_enrollment_token(database_path, zone="economists", ttl="24h")
    token_two = create_enrollment_token(database_path, zone="economists", ttl="24h")
    
    enroll_agent(database_path, token=token_one.token, hostname="pc-eco-01")
    enroll_agent(database_path, token=token_two.token, hostname="pc-eco-02") # pc-eco-02 will trigger anomaly

    # 1. Verify get_traffic_report service logic
    records = get_traffic_report(database_path, threshold_mb=1000.0)
    assert len(records) == 2
    
    # Find records
    eco_01 = next(r for r in records if "pc-eco-01" in r.hostname)
    eco_02 = next(r for r in records if "pc-eco-02" in r.hostname)
    
    assert not eco_01.is_anomaly
    assert eco_02.is_anomaly
    assert eco_02.download_mb > 10000.0

    # 2. Verify report CLI commands
    traffic_result = runner.invoke(app, ["report", "traffic"], env=env)
    assert traffic_result.exit_code == 0
    assert "pc-eco-" in traffic_result.output
    assert "ANOMALY" in traffic_result.output

    anomalies_result = runner.invoke(app, ["report", "anomalies"], env=env)
    assert anomalies_result.exit_code == 0
    assert "pc-eco-" in anomalies_result.output
    assert anomalies_result.output.count("pc-eco-") == 1
    assert "High download burst" in anomalies_result.output


def test_traffic_report_export(tmp_path: Path) -> None:
    env = _write_config(tmp_path)
    database_path = tmp_path / "state" / "netorium.db"
    
    # Initialize controller to setup the database
    runner.invoke(
        app,
        ["controller", "init", "--host", "192.168.1.10", "--port", "8765"],
        env=env,
    )
    
    token_one = create_enrollment_token(database_path, zone="economists", ttl="24h")
    enroll_agent(database_path, token=token_one.token, hostname="pc-eco-01")

    # Export to CSV
    csv_file = tmp_path / "report.csv"
    export_csv_result = runner.invoke(
        app,
        ["report", "export", "--format", "csv", "--output", str(csv_file)],
        env=env,
    )
    assert export_csv_result.exit_code == 0
    assert csv_file.exists()
    csv_content = csv_file.read_text(encoding="utf-8")
    assert "ip_address,hostname,zone_name" in csv_content
    assert "pc-eco-01" in csv_content

    # Export to JSON
    json_file = tmp_path / "report.json"
    export_json_result = runner.invoke(
        app,
        ["report", "export", "--format", "json", "--output", str(json_file)],
        env=env,
    )
    assert export_json_result.exit_code == 0
    assert json_file.exists()
    json_content = json_file.read_text(encoding="utf-8")
    assert "download_mb" in json_content
    assert "pc-eco-01" in json_content

