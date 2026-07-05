from __future__ import annotations

import platform
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from netorium.core.audit import write_audit_entry
from netorium.core.database import connect_database, initialize_database
from netorium.core.subprocess_utils import run_text_optional


class TrafficMonitorError(RuntimeError):
    pass


@dataclass(frozen=True)
class TrafficSnapshot:
    agent_id: str
    hostname: str
    bytes_sent: int
    bytes_received: int
    recorded_at: str


@dataclass(frozen=True)
class TrafficUsageRow:
    agent_id: str
    hostname: str
    bytes_sent: int
    bytes_received: int
    total_bytes: int
    window_start: str
    window_end: str


@dataclass(frozen=True)
class TrafficAnomaly:
    agent_id: str
    hostname: str
    total_bytes: int
    threshold_bytes: int
    window_start: str
    window_end: str


def collect_local_traffic_counters(*, platform_name: str | None = None) -> tuple[int, int] | None:
    active_platform = (platform_name or platform.system()).lower()
    if active_platform.startswith("win"):
        return _collect_windows_traffic_counters()
    if active_platform == "linux":
        return _collect_linux_traffic_counters()
    return None


def record_agent_traffic_sample(
    database_path: str | Path,
    *,
    agent_id: str,
    bytes_sent: int,
    bytes_received: int,
    recorded_at: str,
) -> None:
    if bytes_sent < 0 or bytes_received < 0:
        raise TrafficMonitorError("Traffic counters must be non-negative.")

    path = initialize_database(database_path)
    try:
        connection = connect_database(path)
        try:
            with connection:
                connection.execute(
                    """
                    INSERT INTO agent_traffic_samples(
                        agent_id, bytes_sent, bytes_received, recorded_at
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (agent_id, bytes_sent, bytes_received, recorded_at),
                )
                write_audit_entry(
                    connection,
                    action="agent.traffic.sample",
                    entity_type="agent",
                    entity_id=agent_id,
                    details={
                        "bytes_sent": bytes_sent,
                        "bytes_received": bytes_received,
                    },
                    created_at=recorded_at,
                )
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise TrafficMonitorError(f"Could not store traffic sample: {exc}") from exc


def list_recent_traffic_usage(
    database_path: str | Path,
    *,
    window_minutes: int = 15,
) -> list[TrafficUsageRow]:
    path = initialize_database(database_path)
    try:
        connection = connect_database(path)
        try:
            rows = connection.execute(
                """
                WITH ranked AS (
                    SELECT
                        s.agent_id,
                        a.hostname,
                        s.bytes_sent,
                        s.bytes_received,
                        s.recorded_at,
                        ROW_NUMBER() OVER (
                            PARTITION BY s.agent_id
                            ORDER BY s.recorded_at ASC
                        ) AS sample_rank,
                        COUNT(*) OVER (PARTITION BY s.agent_id) AS sample_count
                    FROM agent_traffic_samples s
                    JOIN agents a ON a.agent_id = s.agent_id
                    WHERE s.recorded_at >= datetime('now', ?)
                ),
                bounds AS (
                    SELECT
                        agent_id,
                        hostname,
                        MIN(recorded_at) AS window_start,
                        MAX(recorded_at) AS window_end,
                        MAX(CASE WHEN sample_rank = 1 THEN bytes_sent END) AS start_sent,
                        MAX(CASE WHEN sample_rank = 1 THEN bytes_received END) AS start_received,
                        MAX(CASE WHEN sample_rank = sample_count THEN bytes_sent END) AS end_sent,
                        MAX(CASE WHEN sample_rank = sample_count THEN bytes_received END) AS end_received
                    FROM ranked
                    GROUP BY agent_id, hostname
                )
                SELECT
                    agent_id,
                    hostname,
                    MAX(end_sent - start_sent, 0) AS bytes_sent,
                    MAX(end_received - start_received, 0) AS bytes_received,
                    MAX(end_sent - start_sent, 0) + MAX(end_received - start_received, 0) AS total_bytes,
                    window_start,
                    window_end
                FROM bounds
                ORDER BY total_bytes DESC, hostname ASC
                """,
                (f"-{window_minutes} minutes",),
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise TrafficMonitorError(f"Could not read traffic usage: {exc}") from exc

    return [
        TrafficUsageRow(
            agent_id=str(row["agent_id"]),
            hostname=str(row["hostname"]),
            bytes_sent=int(row["bytes_sent"]),
            bytes_received=int(row["bytes_received"]),
            total_bytes=int(row["total_bytes"]),
            window_start=str(row["window_start"]),
            window_end=str(row["window_end"]),
        )
        for row in rows
    ]


def detect_traffic_anomalies(
    database_path: str | Path,
    *,
    threshold_mb: int = 1000,
    window_minutes: int = 15,
) -> list[TrafficAnomaly]:
    threshold_bytes = max(threshold_mb, 1) * 1024 * 1024
    usage_rows = list_recent_traffic_usage(database_path, window_minutes=window_minutes)
    return [
        TrafficAnomaly(
            agent_id=row.agent_id,
            hostname=row.hostname,
            total_bytes=row.total_bytes,
            threshold_bytes=threshold_bytes,
            window_start=row.window_start,
            window_end=row.window_end,
        )
        for row in usage_rows
        if row.total_bytes >= threshold_bytes
    ]


def format_bytes(value: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    amount = float(max(value, 0))
    unit_index = 0
    while amount >= 1024 and unit_index < len(units) - 1:
        amount /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{int(amount)} {units[unit_index]}"
    return f"{amount:.1f} {units[unit_index]}"


def _collect_windows_traffic_counters() -> tuple[int, int] | None:
    script = (
        "$stats = Get-NetAdapterStatistics -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Name -notmatch 'Loopback|isatap|Teredo|vEthernet' }; "
        "if (-not $stats) { exit 2 }; "
        "$sent = ($stats | Measure-Object -Property SentBytes -Sum).Sum; "
        "$received = ($stats | Measure-Object -Property ReceivedBytes -Sum).Sum; "
        "Write-Output (\"{0} {1}\" -f [int64]$sent, [int64]$received)"
    )
    completed = run_text_optional(
        (
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-WindowStyle",
            "Hidden",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        )
    )
    if completed.returncode != 0:
        return None
    parts = completed.stdout.strip().split()
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def _collect_linux_traffic_counters() -> tuple[int, int] | None:
    proc_path = Path("/proc/net/dev")
    if not proc_path.exists():
        return None

    sent_total = 0
    received_total = 0
    for line in proc_path.read_text(encoding="utf-8").splitlines()[2:]:
        if ":" not in line:
            continue
        interface_name, counters = line.split(":", 1)
        if interface_name.strip() == "lo":
            continue
        fields = counters.split()
        if len(fields) < 9:
            continue
        received_total += int(fields[0])
        sent_total += int(fields[8])
    return sent_total, received_total
