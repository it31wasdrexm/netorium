from __future__ import annotations

import hashlib
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

DEFAULT_CONTROLLER_HOST = "0.0.0.0"
DEFAULT_CONTROLLER_PORT = 8765
TOKEN_PURPOSE_ENROLL = "enroll"

_TTL_PATTERN = re.compile(r"^(?P<amount>[1-9][0-9]*)(?P<unit>[mhd])$")


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
    pending_commands: tuple[dict[str, object], ...]


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
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ControllerError(f"Could not record agent heartbeat: {exc}") from exc

    return AgentHeartbeat(
        agent_id=clean_agent_id,
        accepted_at=timestamp,
        pending_commands=(),
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
    clean_token = _normalize_text(token, "Token")
    return hashlib.sha256(clean_token.encode("utf-8")).hexdigest()


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
