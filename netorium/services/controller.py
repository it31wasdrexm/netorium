from __future__ import annotations

import ipaddress
import json
import re
import secrets
import socket
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from netorium.core.audit import write_audit_entry
from netorium.core.database import connect_database, initialize_database
from netorium.services.command_signing import build_agent_command_signature, hash_shared_secret

DEFAULT_CONTROLLER_HOST = "0.0.0.0"
DEFAULT_CONTROLLER_PORT = 8765
TOKEN_PURPOSE_ENROLL = "enroll"
COMMAND_TYPE_FIREWALL_IP = "firewall.ip"
COMMAND_TYPE_SITE_ACCESS = "network.site"
COMMAND_TYPE_APP_ACCESS = "network.app"
COMMAND_TYPE_SPEED_LIMIT = "network.speed"
COMMAND_STATUS_QUEUED = "queued"
COMMAND_STATUS_DELIVERED = "delivered"
COMMAND_STATUS_COMPLETED = "completed"
COMMAND_STATUS_FAILED = "failed"

_TTL_PATTERN = re.compile(r"^(?P<amount>[1-9][0-9]*)(?P<unit>[mhd])$")
_DOMAIN_LABEL_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class ControllerError(RuntimeError):
    pass


class ControllerNotInitializedError(ControllerError):
    pass


@dataclass(frozen=True)
class ControllerConfig:
    host: str
    port: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ControllerStatus:
    initialized: bool
    host: str | None
    port: int | None
    listen_url: str | None
    enrollment_url: str | None
    active_tokens: int


@dataclass(frozen=True)
class AgentRecord:
    agent_id: str
    hostname: str
    zone: str
    enrolled_at: str
    last_seen_at: str | None


@dataclass(frozen=True)
class EnrollmentToken:
    token_id: str
    token: str
    purpose: str
    zone: str
    expires_at: str
    created_at: str


@dataclass(frozen=True)
class AgentEnrollment:
    agent_id: str
    device_token: str
    hostname: str
    zone: str
    enrolled_at: str


@dataclass(frozen=True)
class AgentHeartbeat:
    agent_id: str
    accepted_at: str
    pending_commands: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class AgentCommandRecord:
    command_id: str
    agent_id: str
    command_type: str
    payload: dict[str, Any]
    signature: str
    status: str
    result_message: str | None
    created_at: str
    delivered_at: str | None
    completed_at: str | None


@dataclass(frozen=True)
class AgentCommandResult:
    command_id: str
    agent_id: str
    status: str
    message: str
    completed_at: str


def init_controller(
    database_path: str | Path,
    *,
    host: str = DEFAULT_CONTROLLER_HOST,
    port: int = DEFAULT_CONTROLLER_PORT,
) -> ControllerConfig:
    clean_host = _normalize_host(host)
    clean_port = _normalize_port(port)
    timestamp = _utc_timestamp()
    path = initialize_database(database_path)

    try:
        connection = connect_database(path)
        try:
            with connection:
                row = connection.execute(
                    """
                    SELECT created_at
                    FROM controller_config
                    WHERE id = 1
                    """
                ).fetchone()
                if row is None:
                    connection.execute(
                        """
                        INSERT INTO controller_config(id, host, port, created_at, updated_at)
                        VALUES (1, ?, ?, ?, ?)
                        """,
                        (clean_host, clean_port, timestamp, timestamp),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE controller_config
                        SET host = ?, port = ?, updated_at = ?
                        WHERE id = 1
                        """,
                        (clean_host, clean_port, timestamp),
                    )

                write_audit_entry(
                    connection,
                    action="controller.init",
                    entity_type="controller",
                    entity_id="local",
                    details={"host": clean_host, "port": clean_port},
                    created_at=timestamp,
                )
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ControllerError(f"Could not initialize controller: {exc}") from exc

    return get_controller_config(path)


def get_controller_config(database_path: str | Path) -> ControllerConfig:
    path = initialize_database(database_path)
    try:
        connection = connect_database(path)
        try:
            row = connection.execute(
                """
                SELECT host, port, created_at, updated_at
                FROM controller_config
                WHERE id = 1
                """
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ControllerError(f"Could not read controller config: {exc}") from exc

    if row is None:
        raise ControllerNotInitializedError("Controller is not initialized. Run `netorium controller init`.")

    return ControllerConfig(
        host=str(row["host"]),
        port=int(row["port"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def get_controller_status(database_path: str | Path) -> ControllerStatus:
    path = initialize_database(database_path)
    active_tokens = _active_token_count(path)

    try:
        config = get_controller_config(path)
    except ControllerNotInitializedError:
        return ControllerStatus(
            initialized=False,
            host=None,
            port=None,
            listen_url=None,
            enrollment_url=None,
            active_tokens=active_tokens,
        )

    return ControllerStatus(
        initialized=True,
        host=config.host,
        port=config.port,
        listen_url=f"http://{_format_url_host(config.host)}:{config.port}",
        enrollment_url=build_enrollment_url(config.host, config.port),
        active_tokens=active_tokens,
    )


def list_agents(database_path: str | Path) -> list[AgentRecord]:
    path = initialize_database(database_path)
    try:
        connection = connect_database(path)
        try:
            rows = connection.execute(
                """
                SELECT agent_id, hostname, zone, enrolled_at, last_seen_at
                FROM agents
                ORDER BY hostname, agent_id
                """
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ControllerError(f"Could not list agents: {exc}") from exc

    return [_agent_record_from_row(row) for row in rows]


def resolve_agent_targets(
    database_path: str | Path,
    selector: str,
) -> list[AgentRecord]:
    clean_selector = selector.strip()
    if not clean_selector:
        raise ControllerError("Agent target cannot be empty.")

    agents = list_agents(database_path)
    if clean_selector.lower() in {"all", "*"}:
        if not agents:
            raise ControllerError("No agents enrolled yet.")
        return agents

    for agent in agents:
        if agent.agent_id == clean_selector:
            return [agent]

    normalized_selector = clean_selector.lower()
    hostname_matches = [
        agent for agent in agents if agent.hostname.lower() == normalized_selector
    ]
    if len(hostname_matches) == 1:
        return hostname_matches
    if len(hostname_matches) > 1:
        raise ControllerError(
            f"Multiple agents share hostname {clean_selector}. Use agent ID instead."
        )

    raise ControllerError(
        f"Agent was not found: {clean_selector}. Use agent ID, hostname, or all."
    )


@dataclass(frozen=True)
class BatchAgentCommandResult:
    targets: tuple[str, ...]
    commands: tuple[AgentCommandRecord, ...]


def enqueue_agent_firewall_commands(
    database_path: str | Path,
    *,
    agent_selector: str,
    action: str,
    ip_address: str,
    reason: str,
    dry_run: bool = True,
) -> BatchAgentCommandResult:
    targets = resolve_agent_targets(database_path, agent_selector)
    commands = tuple(
        enqueue_agent_firewall_command(
            database_path,
            agent_id=agent.agent_id,
            action=action,
            ip_address=ip_address,
            reason=reason,
            dry_run=dry_run,
        )
        for agent in targets
    )
    return BatchAgentCommandResult(
        targets=tuple(agent.agent_id for agent in targets),
        commands=commands,
    )


def enqueue_agent_site_commands(
    database_path: str | Path,
    *,
    agent_selector: str,
    action: str,
    domain: str,
    reason: str,
    dry_run: bool = True,
) -> BatchAgentCommandResult:
    targets = resolve_agent_targets(database_path, agent_selector)
    commands = tuple(
        enqueue_agent_site_command(
            database_path,
            agent_id=agent.agent_id,
            action=action,
            domain=domain,
            reason=reason,
            dry_run=dry_run,
        )
        for agent in targets
    )
    return BatchAgentCommandResult(
        targets=tuple(agent.agent_id for agent in targets),
        commands=commands,
    )


def enqueue_agent_app_commands(
    database_path: str | Path,
    *,
    agent_selector: str,
    action: str,
    executable: str,
    reason: str,
    dry_run: bool = True,
) -> BatchAgentCommandResult:
    targets = resolve_agent_targets(database_path, agent_selector)
    commands = tuple(
        enqueue_agent_app_command(
            database_path,
            agent_id=agent.agent_id,
            action=action,
            executable=executable,
            reason=reason,
            dry_run=dry_run,
        )
        for agent in targets
    )
    return BatchAgentCommandResult(
        targets=tuple(agent.agent_id for agent in targets),
        commands=commands,
    )


def enqueue_agent_speed_commands(
    database_path: str | Path,
    *,
    agent_selector: str,
    download_kbps: int | None,
    upload_kbps: int | None,
    reason: str,
    clear: bool = False,
    dry_run: bool = True,
) -> BatchAgentCommandResult:
    targets = resolve_agent_targets(database_path, agent_selector)
    commands = tuple(
        enqueue_agent_speed_command(
            database_path,
            agent_id=agent.agent_id,
            download_kbps=download_kbps,
            upload_kbps=upload_kbps,
            clear=clear,
            reason=reason,
            dry_run=dry_run,
        )
        for agent in targets
    )
    return BatchAgentCommandResult(
        targets=tuple(agent.agent_id for agent in targets),
        commands=commands,
    )


def list_agent_commands(
    database_path: str | Path,
    *,
    agent_id: str | None = None,
) -> list[AgentCommandRecord]:
    path = initialize_database(database_path)
    clean_agent_id = _normalize_text(agent_id, "Agent ID") if agent_id is not None else None

    try:
        connection = connect_database(path)
        try:
            if clean_agent_id is None:
                rows = connection.execute(
                    """
                    SELECT command_id, agent_id, command_type, payload, signature, status,
                           result_message, created_at, delivered_at, completed_at
                    FROM agent_commands
                    ORDER BY id DESC
                    """
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT command_id, agent_id, command_type, payload, signature, status,
                           result_message, created_at, delivered_at, completed_at
                    FROM agent_commands
                    WHERE agent_id = ?
                    ORDER BY id DESC
                    """,
                    (clean_agent_id,),
                ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ControllerError(f"Could not list agent commands: {exc}") from exc

    return [_agent_command_from_row(row) for row in rows]


def enqueue_agent_firewall_command(
    database_path: str | Path,
    *,
    agent_id: str,
    action: str,
    ip_address: str,
    reason: str,
    dry_run: bool = True,
) -> AgentCommandRecord:
    clean_agent_id = _normalize_text(agent_id, "Agent ID")
    clean_action = _normalize_firewall_action(action)
    clean_ip = _normalize_ip_address(ip_address)
    clean_reason = _normalize_text(reason, "Firewall reason")
    payload: dict[str, Any] = {
        "action": clean_action,
        "ip_address": clean_ip,
        "reason": clean_reason,
        "dry_run": dry_run,
    }
    return _enqueue_agent_command(
        database_path,
        agent_id=clean_agent_id,
        command_type=COMMAND_TYPE_FIREWALL_IP,
        payload=payload,
        audit_details={
            "action": clean_action,
            "ip_address": clean_ip,
            "dry_run": dry_run,
        },
    )


def enqueue_agent_site_command(
    database_path: str | Path,
    *,
    agent_id: str,
    action: str,
    domain: str,
    reason: str,
    dry_run: bool = True,
) -> AgentCommandRecord:
    clean_agent_id = _normalize_text(agent_id, "Agent ID")
    clean_action = _normalize_policy_action(action, "Site policy action")
    clean_domain = _normalize_domain(domain)
    clean_reason = _normalize_text(reason, "Site policy reason")
    payload: dict[str, Any] = {
        "action": clean_action,
        "domain": clean_domain,
        "reason": clean_reason,
        "dry_run": dry_run,
    }
    return _enqueue_agent_command(
        database_path,
        agent_id=clean_agent_id,
        command_type=COMMAND_TYPE_SITE_ACCESS,
        payload=payload,
        audit_details={
            "action": clean_action,
            "domain": clean_domain,
            "dry_run": dry_run,
        },
    )


def enqueue_agent_app_command(
    database_path: str | Path,
    *,
    agent_id: str,
    action: str,
    executable: str,
    reason: str,
    dry_run: bool = True,
) -> AgentCommandRecord:
    clean_agent_id = _normalize_text(agent_id, "Agent ID")
    clean_action = _normalize_policy_action(action, "Application network action")
    clean_executable = _normalize_executable(executable)
    clean_reason = _normalize_text(reason, "Application network reason")
    payload: dict[str, Any] = {
        "action": clean_action,
        "executable": clean_executable,
        "reason": clean_reason,
        "dry_run": dry_run,
    }
    return _enqueue_agent_command(
        database_path,
        agent_id=clean_agent_id,
        command_type=COMMAND_TYPE_APP_ACCESS,
        payload=payload,
        audit_details={
            "action": clean_action,
            "executable": clean_executable,
            "dry_run": dry_run,
        },
    )


def enqueue_agent_speed_command(
    database_path: str | Path,
    *,
    agent_id: str,
    download_kbps: int | None,
    upload_kbps: int | None,
    reason: str,
    clear: bool = False,
    dry_run: bool = True,
) -> AgentCommandRecord:
    clean_agent_id = _normalize_text(agent_id, "Agent ID")
    clean_reason = _normalize_text(reason, "Speed policy reason")
    if clear:
        payload: dict[str, Any] = {
            "action": "clear",
            "reason": clean_reason,
            "dry_run": dry_run,
        }
    else:
        clean_download = _normalize_optional_kbps(download_kbps, "Download speed")
        clean_upload = _normalize_optional_kbps(upload_kbps, "Upload speed")
        if clean_download is None and clean_upload is None:
            raise ControllerError("Speed limit requires --download-kbps, --upload-kbps, or --clear.")
        payload = {
            "action": "limit",
            "download_kbps": clean_download,
            "upload_kbps": clean_upload,
            "reason": clean_reason,
            "dry_run": dry_run,
        }

    return _enqueue_agent_command(
        database_path,
        agent_id=clean_agent_id,
        command_type=COMMAND_TYPE_SPEED_LIMIT,
        payload=payload,
        audit_details={
            "action": payload["action"],
            "download_kbps": payload.get("download_kbps"),
            "upload_kbps": payload.get("upload_kbps"),
            "dry_run": dry_run,
        },
    )


def _enqueue_agent_command(
    database_path: str | Path,
    *,
    agent_id: str,
    command_type: str,
    payload: dict[str, Any],
    audit_details: dict[str, Any],
) -> AgentCommandRecord:
    path = initialize_database(database_path)
    timestamp = _utc_timestamp()

    for _ in range(3):
        command_id = f"cmd_{secrets.token_hex(6)}"
        try:
            connection = connect_database(path)
            try:
                with connection:
                    agent_row = connection.execute(
                        """
                        SELECT agent_id, device_token_hash
                        FROM agents
                        WHERE agent_id = ?
                        """,
                        (agent_id,),
                    ).fetchone()
                    if agent_row is None:
                        raise ControllerError(f"Agent was not found: {agent_id}")

                    device_token_hash = str(agent_row["device_token_hash"])
                    signature = build_agent_command_signature(
                        signing_key=device_token_hash,
                        agent_id=agent_id,
                        command_id=command_id,
                        command_type=command_type,
                        payload=payload,
                        created_at=timestamp,
                    )
                    connection.execute(
                        """
                        INSERT INTO agent_commands(
                            command_id,
                            agent_id,
                            command_type,
                            payload,
                            signature,
                            status,
                            created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            command_id,
                            agent_id,
                            command_type,
                            json.dumps(payload, ensure_ascii=False, sort_keys=True),
                            signature,
                            COMMAND_STATUS_QUEUED,
                            timestamp,
                        ),
                    )
                    write_audit_entry(
                        connection,
                        action="controller.agent.command.enqueue",
                        entity_type="agent_command",
                        entity_id=command_id,
                        details={
                            "agent_id": agent_id,
                            "command_type": command_type,
                            **audit_details,
                        },
                        created_at=timestamp,
                    )
            finally:
                connection.close()
        except sqlite3.IntegrityError:
            continue
        except sqlite3.Error as exc:
            raise ControllerError(f"Could not queue agent command: {exc}") from exc

        return AgentCommandRecord(
            command_id=command_id,
            agent_id=agent_id,
            command_type=command_type,
            payload=payload,
            signature=signature,
            status=COMMAND_STATUS_QUEUED,
            result_message=None,
            created_at=timestamp,
            delivered_at=None,
            completed_at=None,
        )

    raise ControllerError("Could not create a unique agent command.")


def create_enrollment_token(
    database_path: str | Path,
    *,
    zone: str,
    ttl: str = "24h",
    purpose: str = TOKEN_PURPOSE_ENROLL,
) -> EnrollmentToken:
    path = initialize_database(database_path)
    get_controller_config(path)
    clean_zone = _normalize_text(zone, "Zone")
    clean_purpose = _normalize_text(purpose, "Token purpose")
    ttl_delta = parse_ttl(ttl)
    timestamp = _utc_timestamp()
    expires_at = _format_timestamp(_now_utc() + ttl_delta)

    for _ in range(3):
        token_id = f"enr_{secrets.token_hex(4)}"
        token = f"ng_enroll_{secrets.token_urlsafe(24)}"
        token_hash = hash_token(token)

        try:
            connection = connect_database(path)
            try:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO enrollment_tokens(
                            token_id,
                            token_hash,
                            purpose,
                            zone,
                            expires_at,
                            created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (token_id, token_hash, clean_purpose, clean_zone, expires_at, timestamp),
                    )
                    write_audit_entry(
                        connection,
                        action="controller.token.create",
                        entity_type="enrollment_token",
                        entity_id=token_id,
                        details={
                            "purpose": clean_purpose,
                            "zone": clean_zone,
                            "expires_at": expires_at,
                        },
                        created_at=timestamp,
                    )
            finally:
                connection.close()
        except sqlite3.IntegrityError:
            continue
        except sqlite3.Error as exc:
            raise ControllerError(f"Could not create enrollment token: {exc}") from exc

        return EnrollmentToken(
            token_id=token_id,
            token=token,
            purpose=clean_purpose,
            zone=clean_zone,
            expires_at=expires_at,
            created_at=timestamp,
        )

    raise ControllerError("Could not create a unique enrollment token.")


def enroll_agent(
    database_path: str | Path,
    *,
    token: str,
    hostname: str,
) -> AgentEnrollment:
    clean_token = _normalize_text(token, "Enrollment token")
    clean_hostname = _normalize_text(hostname, "Agent hostname")
    token_hash = hash_token(clean_token)
    timestamp = _utc_timestamp()
    path = initialize_database(database_path)

    for _ in range(3):
        agent_id = f"agt_{secrets.token_hex(6)}"
        device_token = f"ng_device_{secrets.token_urlsafe(32)}"
        device_token_hash = hash_token(device_token)

        try:
            connection = connect_database(path)
            try:
                with connection:
                    row = connection.execute(
                        """
                        SELECT token_id, purpose, zone, expires_at
                        FROM enrollment_tokens
                        WHERE token_hash = ?
                          AND used_at IS NULL
                          AND revoked_at IS NULL
                          AND expires_at > ?
                        """,
                        (token_hash, timestamp),
                    ).fetchone()
                    if row is None:
                        raise ControllerError("Enrollment token is invalid, expired, or already used.")

                    zone = str(row["zone"])
                    token_id = str(row["token_id"])
                    connection.execute(
                        """
                        INSERT INTO agents(
                            agent_id,
                            hostname,
                            zone,
                            device_token_hash,
                            enrolled_at,
                            last_seen_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            agent_id,
                            clean_hostname,
                            zone,
                            device_token_hash,
                            timestamp,
                            timestamp,
                        ),
                    )
                    connection.execute(
                        """
                        UPDATE enrollment_tokens
                        SET used_at = ?
                        WHERE token_id = ?
                        """,
                        (timestamp, token_id),
                    )
                    write_audit_entry(
                        connection,
                        action="controller.agent.enroll",
                        entity_type="agent",
                        entity_id=agent_id,
                        details={
                            "hostname": clean_hostname,
                            "zone": zone,
                            "token_id": token_id,
                        },
                        created_at=timestamp,
                    )
            finally:
                connection.close()
        except sqlite3.IntegrityError:
            continue
        except sqlite3.Error as exc:
            raise ControllerError(f"Could not enroll agent: {exc}") from exc

        return AgentEnrollment(
            agent_id=agent_id,
            device_token=device_token,
            hostname=clean_hostname,
            zone=zone,
            enrolled_at=timestamp,
        )

    raise ControllerError("Could not create a unique agent enrollment.")


def record_agent_heartbeat(
    database_path: str | Path,
    *,
    agent_id: str,
    device_token: str,
) -> AgentHeartbeat:
    clean_agent_id = _normalize_text(agent_id, "Agent ID")
    device_token_hash = hash_token(device_token)
    timestamp = _utc_timestamp()
    path = initialize_database(database_path)

    try:
        connection = connect_database(path)
        try:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE agents
                    SET last_seen_at = ?
                    WHERE agent_id = ?
                      AND device_token_hash = ?
                    """,
                    (timestamp, clean_agent_id, device_token_hash),
                )
                if cursor.rowcount != 1:
                    raise ControllerError("Agent heartbeat was rejected.")
                command_rows = connection.execute(
                    """
                    SELECT command_id, agent_id, command_type, payload, signature, status,
                           result_message, created_at, delivered_at, completed_at
                    FROM agent_commands
                    WHERE agent_id = ?
                      AND status = ?
                    ORDER BY id ASC
                    """,
                    (clean_agent_id, COMMAND_STATUS_QUEUED),
                ).fetchall()
                pending_commands: list[dict[str, Any]] = []
                for row in command_rows:
                    payload = _decode_payload(str(row["payload"]))
                    signature = str(row["signature"] or "")
                    if not signature:
                        signature = build_agent_command_signature(
                            signing_key=device_token_hash,
                            agent_id=clean_agent_id,
                            command_id=str(row["command_id"]),
                            command_type=str(row["command_type"]),
                            payload=payload,
                            created_at=str(row["created_at"]),
                        )
                        connection.execute(
                            """
                            UPDATE agent_commands
                            SET signature = ?
                            WHERE command_id = ?
                            """,
                            (signature, str(row["command_id"])),
                        )
                    connection.execute(
                        """
                        UPDATE agent_commands
                        SET status = ?, delivered_at = ?
                        WHERE command_id = ?
                          AND status = ?
                        """,
                        (
                            COMMAND_STATUS_DELIVERED,
                            timestamp,
                            str(row["command_id"]),
                            COMMAND_STATUS_QUEUED,
                        ),
                    )
                    pending_commands.append(
                        _agent_command_payload_from_row(row, payload=payload, signature=signature)
                    )
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ControllerError(f"Could not record agent heartbeat: {exc}") from exc

    return AgentHeartbeat(
        agent_id=clean_agent_id,
        accepted_at=timestamp,
        pending_commands=tuple(pending_commands),
    )


def record_agent_command_result(
    database_path: str | Path,
    *,
    agent_id: str,
    device_token: str,
    command_id: str,
    status: str,
    message: str,
) -> AgentCommandResult:
    clean_agent_id = _normalize_text(agent_id, "Agent ID")
    clean_command_id = _normalize_text(command_id, "Command ID")
    clean_status = _normalize_command_result_status(status)
    clean_message = _normalize_text(message, "Command result message")
    device_token_hash = hash_token(device_token)
    timestamp = _utc_timestamp()
    path = initialize_database(database_path)

    try:
        connection = connect_database(path)
        try:
            with connection:
                agent_row = connection.execute(
                    """
                    SELECT agent_id
                    FROM agents
                    WHERE agent_id = ?
                      AND device_token_hash = ?
                    """,
                    (clean_agent_id, device_token_hash),
                ).fetchone()
                if agent_row is None:
                    raise ControllerError("Agent command result was rejected.")

                command_row = connection.execute(
                    """
                    SELECT command_id
                    FROM agent_commands
                    WHERE command_id = ?
                      AND agent_id = ?
                    """,
                    (clean_command_id, clean_agent_id),
                ).fetchone()
                if command_row is None:
                    raise ControllerError(f"Agent command was not found: {clean_command_id}")

                connection.execute(
                    """
                    UPDATE agent_commands
                    SET status = ?, result_message = ?, completed_at = ?
                    WHERE command_id = ?
                    """,
                    (clean_status, clean_message, timestamp, clean_command_id),
                )
                write_audit_entry(
                    connection,
                    action=f"controller.agent.command.{clean_status}",
                    entity_type="agent_command",
                    entity_id=clean_command_id,
                    details={
                        "agent_id": clean_agent_id,
                        "status": clean_status,
                    },
                    created_at=timestamp,
                )
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ControllerError(f"Could not record agent command result: {exc}") from exc

    return AgentCommandResult(
        command_id=clean_command_id,
        agent_id=clean_agent_id,
        status=clean_status,
        message=clean_message,
        completed_at=timestamp,
    )


def parse_ttl(value: str) -> timedelta:
    match = _TTL_PATTERN.fullmatch(value.strip().lower())
    if match is None:
        raise ControllerError("TTL must use minutes, hours, or days, for example 30m, 24h, or 7d.")

    amount = int(match.group("amount"))
    unit = match.group("unit")
    if unit == "m":
        return timedelta(minutes=amount)
    if unit == "h":
        return timedelta(hours=amount)
    return timedelta(days=amount)


def hash_token(token: str) -> str:
    try:
        return hash_shared_secret(token, label="Token")
    except ValueError as exc:
        raise ControllerError(str(exc)) from exc


def build_enrollment_url(host: str, port: int) -> str:
    client_host = _client_host(host)
    return f"http://{_format_url_host(client_host)}:{_normalize_port(port)}/enroll"


def serve_controller(
    database_path: str | Path,
    *,
    host: str = DEFAULT_CONTROLLER_HOST,
    port: int = DEFAULT_CONTROLLER_PORT,
) -> None:
    clean_host = _normalize_host(host)
    clean_port = _normalize_port(port)
    path = initialize_database(database_path)
    init_controller(path, host=clean_host, port=clean_port)
    handler = _make_handler(path)

    try:
        server = HTTPServer((clean_host, clean_port), handler)
    except OSError as exc:
        raise ControllerError(f"Could not start controller on {clean_host}:{clean_port}: {exc}") from exc

    try:
        server.serve_forever()
    finally:
        server.server_close()


def _make_handler(database_path: Path) -> type[BaseHTTPRequestHandler]:
    class ControllerRequestHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path in {"/health", "/status"}:
                status = get_controller_status(database_path)
                self._send_json(
                    {
                        "app": "netorium",
                        "initialized": status.initialized,
                        "listen_url": status.listen_url,
                        "enrollment_url": status.enrollment_url,
                        "active_tokens": status.active_tokens,
                    }
                )
                return

            self._send_json({"error": "not found"}, status_code=404)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/enroll":
                payload = self._read_json()
                if not isinstance(payload, dict):
                    self._send_json({"error": "invalid json"}, status_code=400)
                    return

                token = payload.get("token")
                hostname = payload.get("hostname")
                if not isinstance(token, str) or not isinstance(hostname, str):
                    self._send_json(
                        {"error": "token and hostname are required"},
                        status_code=400,
                    )
                    return

                try:
                    enrollment = enroll_agent(
                        database_path,
                        token=token,
                        hostname=hostname,
                    )
                except ControllerError as exc:
                    self._send_json({"error": str(exc)}, status_code=400)
                    return

                self._send_json(
                    {
                        "agent_id": enrollment.agent_id,
                        "device_token": enrollment.device_token,
                        "hostname": enrollment.hostname,
                        "zone": enrollment.zone,
                        "enrolled_at": enrollment.enrolled_at,
                    }
                )
                return

            if parsed.path == "/heartbeat":
                payload = self._read_json()
                if not isinstance(payload, dict):
                    self._send_json({"error": "invalid json"}, status_code=400)
                    return

                agent_id = payload.get("agent_id")
                device_token = payload.get("device_token")
                if not isinstance(agent_id, str) or not isinstance(device_token, str):
                    self._send_json(
                        {"error": "agent_id and device_token are required"},
                        status_code=400,
                    )
                    return

                try:
                    heartbeat = record_agent_heartbeat(
                        database_path,
                        agent_id=agent_id,
                        device_token=device_token,
                    )
                except ControllerError as exc:
                    self._send_json({"error": str(exc)}, status_code=403)
                    return

                self._send_json(
                    {
                        "agent_id": heartbeat.agent_id,
                        "accepted_at": heartbeat.accepted_at,
                        "commands": list(heartbeat.pending_commands),
                    }
                )
                return

            if parsed.path == "/command-result":
                payload = self._read_json()
                if not isinstance(payload, dict):
                    self._send_json({"error": "invalid json"}, status_code=400)
                    return

                agent_id = payload.get("agent_id")
                device_token = payload.get("device_token")
                command_id = payload.get("command_id")
                status = payload.get("status")
                message = payload.get("message")
                if (
                    not isinstance(agent_id, str)
                    or not isinstance(device_token, str)
                    or not isinstance(command_id, str)
                    or not isinstance(status, str)
                    or not isinstance(message, str)
                ):
                    self._send_json(
                        {
                            "error": (
                                "agent_id, device_token, command_id, status, "
                                "and message are required"
                            )
                        },
                        status_code=400,
                    )
                    return

                try:
                    result = record_agent_command_result(
                        database_path,
                        agent_id=agent_id,
                        device_token=device_token,
                        command_id=command_id,
                        status=status,
                        message=message,
                    )
                except ControllerError as exc:
                    self._send_json({"error": str(exc)}, status_code=403)
                    return

                self._send_json(
                    {
                        "agent_id": result.agent_id,
                        "command_id": result.command_id,
                        "status": result.status,
                        "completed_at": result.completed_at,
                    }
                )
                return

            self._send_json({"error": "not found"}, status_code=404)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _read_json(self) -> object:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length < 1:
                return None
            raw_body = self.rfile.read(content_length)
            try:
                return json.loads(raw_body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None

        def _send_json(self, payload: dict[str, object], status_code: int = 200) -> None:
            body = json.dumps(payload, sort_keys=True).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ControllerRequestHandler


def _active_token_count(database_path: Path) -> int:
    now = _utc_timestamp()
    try:
        connection = connect_database(database_path)
        try:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM enrollment_tokens
                WHERE used_at IS NULL
                  AND revoked_at IS NULL
                  AND expires_at > ?
                """,
                (now,),
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ControllerError(f"Could not read enrollment tokens: {exc}") from exc

    if row is None:
        return 0
    return int(row["count"])


def _agent_record_from_row(row: sqlite3.Row) -> AgentRecord:
    raw_last_seen = row["last_seen_at"]
    return AgentRecord(
        agent_id=str(row["agent_id"]),
        hostname=str(row["hostname"]),
        zone=str(row["zone"]),
        enrolled_at=str(row["enrolled_at"]),
        last_seen_at=str(raw_last_seen) if raw_last_seen is not None else None,
    )


def _agent_command_from_row(row: sqlite3.Row) -> AgentCommandRecord:
    raw_result_message = row["result_message"]
    raw_delivered_at = row["delivered_at"]
    raw_completed_at = row["completed_at"]
    return AgentCommandRecord(
        command_id=str(row["command_id"]),
        agent_id=str(row["agent_id"]),
        command_type=str(row["command_type"]),
        payload=_decode_payload(str(row["payload"])),
        signature=str(row["signature"] or ""),
        status=str(row["status"]),
        result_message=str(raw_result_message) if raw_result_message is not None else None,
        created_at=str(row["created_at"]),
        delivered_at=str(raw_delivered_at) if raw_delivered_at is not None else None,
        completed_at=str(raw_completed_at) if raw_completed_at is not None else None,
    )


def _agent_command_payload_from_row(
    row: sqlite3.Row,
    *,
    payload: dict[str, Any] | None = None,
    signature: str | None = None,
) -> dict[str, Any]:
    return {
        "command_id": str(row["command_id"]),
        "command_type": str(row["command_type"]),
        "payload": payload if payload is not None else _decode_payload(str(row["payload"])),
        "signature": signature if signature is not None else str(row["signature"] or ""),
        "created_at": str(row["created_at"]),
    }


def _decode_payload(value: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _normalize_firewall_action(value: str) -> str:
    clean_value = value.strip().lower()
    if clean_value not in {"block", "unblock"}:
        raise ControllerError("Endpoint firewall action must be block or unblock.")
    return clean_value


def _normalize_policy_action(value: str, label: str) -> str:
    clean_value = value.strip().lower()
    if clean_value not in {"block", "unblock"}:
        raise ControllerError(f"{label} must be block or unblock.")
    return clean_value


def _normalize_ip_address(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError as exc:
        raise ControllerError(f"Invalid IP address: {value}") from exc


def _normalize_domain(value: str) -> str:
    raw_value = _normalize_text(value, "Site domain").lower()
    wildcard = raw_value.startswith("*.")
    if wildcard:
        raw_value = raw_value[2:]

    parsed = urlparse(raw_value if "://" in raw_value else f"//{raw_value}")
    host = parsed.hostname or raw_value.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    host = host.strip().lower().rstrip(".")
    if host.startswith("*."):
        wildcard = True
        host = host[2:]

    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ControllerError("Site policy target must be a domain name, not an IP address.")

    if not _is_valid_hostname(host):
        raise ControllerError(f"Invalid site domain: {value}")
    return f"*.{host}" if wildcard else host


def _is_valid_hostname(value: str) -> bool:
    if len(value) > 253:
        return False
    labels = value.split(".")
    return all(_DOMAIN_LABEL_PATTERN.fullmatch(label) is not None for label in labels)


def _normalize_executable(value: str) -> str:
    clean_value = _normalize_text(value, "Executable").strip("'\"").strip()
    if not clean_value:
        raise ControllerError("Executable cannot be empty.")
    if "\x00" in clean_value or any(char in clean_value for char in "\r\n"):
        raise ControllerError("Executable cannot contain control characters.")
    if len(clean_value) > 1024:
        raise ControllerError("Executable path is too long.")
    return clean_value


def _normalize_optional_kbps(value: int | None, label: str) -> int | None:
    if value is None:
        return None
    if value < 1:
        raise ControllerError(f"{label} must be at least 1 kbps.")
    if value > 10_000_000:
        raise ControllerError(f"{label} must be 10000000 kbps or less.")
    return value


def _normalize_command_result_status(value: str) -> str:
    clean_value = value.strip().lower()
    if clean_value not in {COMMAND_STATUS_COMPLETED, COMMAND_STATUS_FAILED}:
        raise ControllerError("Command result status must be completed or failed.")
    return clean_value


def _normalize_host(host: str) -> str:
    clean_host = host.strip()
    if not clean_host:
        raise ControllerError("Controller host cannot be empty.")
    return clean_host


def _normalize_port(port: int) -> int:
    if port < 1 or port > 65535:
        raise ControllerError("Controller port must be between 1 and 65535.")
    return port


def _normalize_text(value: str, label: str) -> str:
    clean_value = value.strip()
    if not clean_value:
        raise ControllerError(f"{label} cannot be empty.")
    return clean_value


def _client_host(host: str) -> str:
    if host in {"0.0.0.0", "::"}:
        return _detect_lan_host()
    return host


def _detect_lan_host() -> str:
    try:
        for result in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = str(result[4][0])
            if not address.startswith("127.") and address != "0.0.0.0":
                return address
    except socket.gaierror:
        return "127.0.0.1"

    return "127.0.0.1"


def _format_url_host(host: str) -> str:
    if ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _utc_timestamp() -> str:
    return _format_timestamp(_now_utc())


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()
