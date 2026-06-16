from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from netorium.core.audit import list_audit_entries
from netorium.core.database import connect_database
from netorium.services.controller import (
    ControllerError,
    ControllerNotInitializedError,
    create_enrollment_token,
    enroll_agent,
    get_controller_status,
    hash_token,
    init_controller,
    list_agents,
    parse_ttl,
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
    assert status.active_tokens == 0

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
