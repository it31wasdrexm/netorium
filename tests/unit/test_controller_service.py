from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from netorium.core.audit import list_audit_entries
from netorium.core.database import connect_database
from netorium.services.command_signing import verify_agent_command_signature
from netorium.services.controller import (
    ControllerError,
    ControllerNotInitializedError,
    enqueue_agent_app_command,
    create_enrollment_token,
    enqueue_agent_firewall_command,
    enqueue_agent_site_command,
    enqueue_agent_speed_command,
    enroll_agent,
    get_controller_status,
    hash_token,
    init_controller,
    list_agent_commands,
    list_agents,
    parse_ttl,
    record_agent_command_result,
    record_agent_heartbeat,
)


def test_controller_status_reports_uninitialized_database(tmp_path: Path) -> None:
    status = get_controller_status(tmp_path / "netorium.db")

    assert status.initialized is False
    assert status.listen_url is None
    assert status.enrollment_url is None
    assert status.active_tokens == 0


def test_controller_init_and_token_creation_store_only_token_hash(tmp_path: Path) -> None:
    database_path = tmp_path / "netorium.db"

    config = init_controller(database_path, host="0.0.0.0", port=8765)
    token = create_enrollment_token(database_path, zone="accounting", ttl="24h")
    status = get_controller_status(database_path)

    assert config.host == "0.0.0.0"
    assert config.port == 8765
    assert token.token_id.startswith("enr_")
    assert token.token.startswith("ng_enroll_")
    assert token.zone == "accounting"
    assert status.initialized is True
    assert status.active_tokens == 1
    assert status.listen_url == "http://0.0.0.0:8765"
    assert status.enrollment_url is not None
    assert status.enrollment_url.endswith(":8765/enroll")

    connection = connect_database(database_path)
    try:
        row = connection.execute(
            """
            SELECT token_id, token_hash, zone
            FROM enrollment_tokens
            WHERE token_id = ?
            """,
            (token.token_id,),
        ).fetchone()
    finally:
        connection.close()

    assert row is not None
    assert row["zone"] == "accounting"
    assert row["token_hash"] == hash_token(token.token)
    assert token.token not in str(dict(row))

    entries = list_audit_entries(str(database_path))
    assert [entry.action for entry in entries] == [
        "controller.token.create",
        "controller.init",
    ]


def test_enrollment_token_requires_initialized_controller(tmp_path: Path) -> None:
    with pytest.raises(ControllerNotInitializedError, match="controller init"):
        create_enrollment_token(tmp_path / "netorium.db", zone="accounting", ttl="24h")


def test_enroll_agent_uses_one_time_token_and_stores_device_token_hash(tmp_path: Path) -> None:
    database_path = tmp_path / "netorium.db"
    init_controller(database_path, host="192.168.1.10", port=8765)
    token = create_enrollment_token(database_path, zone="accounting", ttl="24h")

    enrollment = enroll_agent(database_path, token=token.token, hostname="pc-acc-01")
    status = get_controller_status(database_path)

    assert enrollment.agent_id.startswith("agt_")
    assert enrollment.device_token.startswith("ng_device_")
    assert enrollment.hostname == "pc-acc-01"
    assert enrollment.zone == "accounting"
    assert status.active_tokens == 1

    connection = connect_database(database_path)
    try:
        agent_row = connection.execute(
            """
            SELECT agent_id, hostname, zone, device_token_hash
            FROM agents
            WHERE agent_id = ?
            """,
            (enrollment.agent_id,),
        ).fetchone()
        token_row = connection.execute(
            """
            SELECT used_at
            FROM enrollment_tokens
            WHERE token_id = ?
            """,
            (token.token_id,),
        ).fetchone()
    finally:
        connection.close()

    assert agent_row is not None
    assert agent_row["hostname"] == "pc-acc-01"
    assert agent_row["zone"] == "accounting"
    assert agent_row["device_token_hash"] == hash_token(enrollment.device_token)
    assert token_row is not None
    assert token_row["used_at"] is not None

    with pytest.raises(ControllerError, match="invalid, expired, or already used"):
        enroll_agent(database_path, token=token.token, hostname="pc-acc-02")


def test_agent_heartbeat_updates_last_seen_and_lists_agent(tmp_path: Path) -> None:
    database_path = tmp_path / "netorium.db"
    init_controller(database_path, host="192.168.1.10", port=8765)
    token = create_enrollment_token(database_path, zone="accounting", ttl="24h")
    enrollment = enroll_agent(database_path, token=token.token, hostname="pc-acc-01")

    heartbeat = record_agent_heartbeat(
        database_path,
        agent_id=enrollment.agent_id,
        device_token=enrollment.device_token,
    )
    agents = list_agents(database_path)

    assert heartbeat.agent_id == enrollment.agent_id
    assert heartbeat.accepted_at
    assert heartbeat.pending_commands == ()
    assert len(agents) == 1
    assert agents[0].agent_id == enrollment.agent_id
    assert agents[0].hostname == "pc-acc-01"
    assert agents[0].last_seen_at == heartbeat.accepted_at


def test_agent_command_queue_delivers_and_records_result(tmp_path: Path) -> None:
    database_path = tmp_path / "netorium.db"
    init_controller(database_path, host="192.168.1.10", port=8765)
    token = create_enrollment_token(database_path, zone="accounting", ttl="24h")
    enrollment = enroll_agent(database_path, token=token.token, hostname="pc-acc-01")

    command = enqueue_agent_firewall_command(
        database_path,
        agent_id=enrollment.agent_id,
        action="block",
        ip_address="192.168.1.25",
        reason="Policy test",
    )
    heartbeat = record_agent_heartbeat(
        database_path,
        agent_id=enrollment.agent_id,
        device_token=enrollment.device_token,
    )
    delivered = list_agent_commands(database_path, agent_id=enrollment.agent_id)
    result = record_agent_command_result(
        database_path,
        agent_id=enrollment.agent_id,
        device_token=enrollment.device_token,
        command_id=command.command_id,
        status="completed",
        message="Dry-run firewall block accepted.",
    )
    completed = list_agent_commands(database_path, agent_id=enrollment.agent_id)

    assert heartbeat.pending_commands == (
        {
            "command_id": command.command_id,
            "command_type": "firewall.ip",
            "payload": {
                "action": "block",
                "dry_run": True,
                "ip_address": "192.168.1.25",
                "reason": "Policy test",
            },
            "signature": command.signature,
            "created_at": command.created_at,
        },
    )
    assert len(command.signature) == 64
    assert verify_agent_command_signature(
        signing_key=hash_token(enrollment.device_token),
        agent_id=enrollment.agent_id,
        command_id=command.command_id,
        command_type=command.command_type,
        payload=command.payload,
        created_at=command.created_at,
        signature=command.signature,
    )
    assert delivered[0].status == "delivered"
    assert delivered[0].signature == command.signature
    assert result.status == "completed"
    assert completed[0].status == "completed"
    assert completed[0].result_message == "Dry-run firewall block accepted."

    entries = list_audit_entries(str(database_path))
    assert "controller.agent.command.completed" in [entry.action for entry in entries]
    assert "controller.agent.command.enqueue" in [entry.action for entry in entries]


def test_agent_policy_commands_queue_site_app_and_speed_limits(tmp_path: Path) -> None:
    database_path = tmp_path / "netorium.db"
    init_controller(database_path, host="192.168.1.10", port=8765)
    token = create_enrollment_token(database_path, zone="gaming-room", ttl="24h")
    enrollment = enroll_agent(database_path, token=token.token, hostname="pc-game-01")

    site = enqueue_agent_site_command(
        database_path,
        agent_id=enrollment.agent_id,
        action="block",
        domain="https://YouTube.com/watch?v=abc",
        reason="Class policy",
    )
    app = enqueue_agent_app_command(
        database_path,
        agent_id=enrollment.agent_id,
        action="block",
        executable="dota2.exe",
        reason="No game traffic",
    )
    speed = enqueue_agent_speed_command(
        database_path,
        agent_id=enrollment.agent_id,
        download_kbps=2048,
        upload_kbps=512,
        reason="Temporary limit",
    )
    heartbeat = record_agent_heartbeat(
        database_path,
        agent_id=enrollment.agent_id,
        device_token=enrollment.device_token,
    )

    assert site.command_type == "network.site"
    assert site.payload["domain"] == "youtube.com"
    assert app.command_type == "network.app"
    assert app.payload["executable"] == "dota2.exe"
    assert speed.command_type == "network.speed"
    assert speed.payload["download_kbps"] == 2048
    assert speed.payload["upload_kbps"] == 512
    assert [command["command_type"] for command in heartbeat.pending_commands] == [
        "network.site",
        "network.app",
        "network.speed",
    ]
    assert all(command["signature"] for command in heartbeat.pending_commands)

    commands = list_agent_commands(database_path, agent_id=enrollment.agent_id)
    assert {command.status for command in commands} == {"delivered"}
    assert {command.command_type for command in commands} == {
        "network.site",
        "network.app",
        "network.speed",
    }


def test_agent_policy_commands_validate_targets_and_limits(tmp_path: Path) -> None:
    database_path = tmp_path / "netorium.db"
    init_controller(database_path, host="192.168.1.10", port=8765)
    token = create_enrollment_token(database_path, zone="gaming-room", ttl="24h")
    enrollment = enroll_agent(database_path, token=token.token, hostname="pc-game-01")

    with pytest.raises(ControllerError, match="domain name"):
        enqueue_agent_site_command(
            database_path,
            agent_id=enrollment.agent_id,
            action="block",
            domain="192.168.1.25",
            reason="Wrong target",
        )

    with pytest.raises(ControllerError, match="Executable cannot be empty"):
        enqueue_agent_app_command(
            database_path,
            agent_id=enrollment.agent_id,
            action="block",
            executable='""',
            reason="Wrong target",
        )

    with pytest.raises(ControllerError, match="requires --download-kbps"):
        enqueue_agent_speed_command(
            database_path,
            agent_id=enrollment.agent_id,
            download_kbps=None,
            upload_kbps=None,
            reason="Missing limit",
        )


def test_agent_firewall_command_requires_existing_agent_and_allows_real_queue(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "netorium.db"
    init_controller(database_path, host="192.168.1.10", port=8765)

    with pytest.raises(ControllerError, match="Agent was not found"):
        enqueue_agent_firewall_command(
            database_path,
            agent_id="agt_missing",
            action="block",
            ip_address="192.168.1.25",
            reason="Policy test",
        )

    token = create_enrollment_token(database_path, zone="accounting", ttl="24h")
    enrollment = enroll_agent(database_path, token=token.token, hostname="pc-acc-01")

    command = enqueue_agent_firewall_command(
        database_path,
        agent_id=enrollment.agent_id,
        action="block",
        ip_address="192.168.1.25",
        reason="Policy test",
        dry_run=False,
    )

    assert command.payload["dry_run"] is False


def test_agent_heartbeat_rejects_invalid_device_token(tmp_path: Path) -> None:
    database_path = tmp_path / "netorium.db"
    init_controller(database_path, host="192.168.1.10", port=8765)
    token = create_enrollment_token(database_path, zone="accounting", ttl="24h")
    enrollment = enroll_agent(database_path, token=token.token, hostname="pc-acc-01")

    with pytest.raises(ControllerError, match="rejected"):
        record_agent_heartbeat(
            database_path,
            agent_id=enrollment.agent_id,
            device_token="wrong",
        )


def test_parse_ttl_accepts_minutes_hours_and_days() -> None:
    assert parse_ttl("30m") == timedelta(minutes=30)
    assert parse_ttl("24h") == timedelta(hours=24)
    assert parse_ttl("7d") == timedelta(days=7)


def test_parse_ttl_rejects_invalid_values() -> None:
    with pytest.raises(ControllerError, match="TTL must use"):
        parse_ttl("0h")

    with pytest.raises(ControllerError, match="TTL must use"):
        parse_ttl("24x")


def test_controller_rejects_invalid_port(tmp_path: Path) -> None:
    with pytest.raises(ControllerError, match="between 1 and 65535"):
        init_controller(tmp_path / "netorium.db", port=0)


def test_controller_schema_tables_exist(tmp_path: Path) -> None:
    database_path = tmp_path / "netorium.db"
    init_controller(database_path)

    connection = connect_database(database_path)
    try:
        tables = {
            str(row["name"])
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            ).fetchall()
        }
    finally:
        connection.close()

    assert "controller_config" in tables
    assert "enrollment_tokens" in tables
    assert "agents" in tables
    assert "agent_commands" in tables


def test_controller_migrates_existing_agent_command_signature_column(tmp_path: Path) -> None:
    database_path = tmp_path / "netorium.db"
    connection = connect_database(database_path)
    try:
        with connection:
            connection.execute(
                """
                CREATE TABLE agent_commands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    command_id TEXT NOT NULL UNIQUE,
                    agent_id TEXT NOT NULL,
                    command_type TEXT NOT NULL,
                    payload TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL,
                    result_message TEXT,
                    created_at TEXT NOT NULL,
                    delivered_at TEXT,
                    completed_at TEXT
                )
                """
            )
    finally:
        connection.close()

    get_controller_status(database_path)

    connection = connect_database(database_path)
    try:
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(agent_commands)").fetchall()
        }
    finally:
        connection.close()

    assert "signature" in columns


def test_resolve_agent_targets_supports_id_hostname_and_all(tmp_path: Path) -> None:
    from netorium.services.controller import enqueue_agent_site_commands, resolve_agent_targets

    database_path = tmp_path / "netorium.db"
    init_controller(database_path, host="192.168.1.10", port=8765)
    token_one = create_enrollment_token(database_path, zone="gaming-room", ttl="24h")
    token_two = create_enrollment_token(database_path, zone="gaming-room", ttl="24h")
    first = enroll_agent(database_path, token=token_one.token, hostname="pc-game-01")
    second = enroll_agent(database_path, token=token_two.token, hostname="pc-game-02")

    by_id = resolve_agent_targets(database_path, first.agent_id)
    by_hostname = resolve_agent_targets(database_path, "pc-game-02")
    all_agents = resolve_agent_targets(database_path, "all")

    assert [agent.agent_id for agent in by_id] == [first.agent_id]
    assert [agent.agent_id for agent in by_hostname] == [second.agent_id]
    assert {agent.agent_id for agent in all_agents} == {first.agent_id, second.agent_id}

    batch = enqueue_agent_site_commands(
        database_path,
        agent_selector="all",
        action="block",
        domain="youtube.com",
        reason="Class policy",
    )

    assert len(batch.commands) == 2
    assert batch.commands[0].command_type == "network.site"
