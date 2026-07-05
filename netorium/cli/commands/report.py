from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Annotated, Literal

import typer
from rich.console import Console
from rich.table import Table

from netorium.core.settings import ConfigError, load_settings
from netorium.services.traffic_monitor import (
    TrafficMonitorError,
    detect_traffic_anomalies,
    format_bytes,
    list_recent_traffic_usage,
)

report_app = typer.Typer(
    help="Traffic usage reports and anomaly detection.",
    no_args_is_help=True,
    rich_help_panel="Monitoring",
)

console = Console()
error_console = Console(stderr=True)


@report_app.command("traffic")
def report_traffic(
    threshold: Annotated[
        int,
        typer.Option("--threshold", help="Highlight agents above this total in MB."),
    ] = 1000,
    window: Annotated[
        int,
        typer.Option("--window", help="Lookback window in minutes."),
    ] = 15,
) -> None:
    """Show recent traffic usage for enrolled agents."""
    try:
        settings = load_settings()
        rows = list_recent_traffic_usage(
            settings.app.database_path,
            window_minutes=window,
        )
    except (ConfigError, TrafficMonitorError) as exc:
        _fail(exc)

    if not rows:
        console.print("No traffic samples yet. Agents must send heartbeats with traffic counters.")
        return

    threshold_bytes = max(threshold, 1) * 1024 * 1024
    table = Table(title=f"Traffic Usage ({window} min window)")
    table.add_column("Agent")
    table.add_column("Hostname")
    table.add_column("Download", justify="right")
    table.add_column("Upload", justify="right")
    table.add_column("Total", justify="right")
    table.add_column("Window")

    for row in rows:
        total_style = "bold red" if row.total_bytes >= threshold_bytes else ""
        table.add_row(
            row.agent_id,
            row.hostname,
            format_bytes(row.bytes_received),
            format_bytes(row.bytes_sent),
            f"[{total_style}]{format_bytes(row.total_bytes)}[/{total_style}]"
            if total_style
            else format_bytes(row.total_bytes),
            f"{row.window_start} -> {row.window_end}",
        )
    console.print(table)


@report_app.command("anomalies")
def report_anomalies(
    threshold: Annotated[
        int,
        typer.Option("--threshold", help="Anomaly threshold in megabytes."),
    ] = 1000,
    window: Annotated[
        int,
        typer.Option("--window", help="Lookback window in minutes."),
    ] = 15,
) -> None:
    """List agents whose recent traffic exceeds the configured threshold."""
    try:
        settings = load_settings()
        anomalies = detect_traffic_anomalies(
            settings.app.database_path,
            threshold_mb=threshold,
            window_minutes=window,
        )
    except (ConfigError, TrafficMonitorError) as exc:
        _fail(exc)

    if not anomalies:
        console.print(f"No anomalies detected above {threshold} MB in the last {window} minutes.")
        return

    table = Table(title="Traffic Anomalies")
    table.add_column("Agent")
    table.add_column("Hostname")
    table.add_column("Total", justify="right")
    table.add_column("Threshold", justify="right")
    table.add_column("Window")
    for anomaly in anomalies:
        table.add_row(
            anomaly.agent_id,
            anomaly.hostname,
            format_bytes(anomaly.total_bytes),
            format_bytes(anomaly.threshold_bytes),
            f"{anomaly.window_start} -> {anomaly.window_end}",
        )
    console.print(table)


@report_app.command("export")
def report_export(
    output: Annotated[Path, typer.Argument(help="Output file path.")],
    format: Annotated[
        Literal["csv", "json"],
        typer.Option("--format", help="Export format."),
    ] = "csv",
    window: Annotated[
        int,
        typer.Option("--window", help="Lookback window in minutes."),
    ] = 15,
) -> None:
    """Export recent traffic usage to CSV or JSON."""
    try:
        settings = load_settings()
        rows = list_recent_traffic_usage(
            settings.app.database_path,
            window_minutes=window,
        )
    except (ConfigError, TrafficMonitorError) as exc:
        _fail(exc)

    output.parent.mkdir(parents=True, exist_ok=True)
    if format == "json":
        payload = [
            {
                "agent_id": row.agent_id,
                "hostname": row.hostname,
                "bytes_sent": row.bytes_sent,
                "bytes_received": row.bytes_received,
                "total_bytes": row.total_bytes,
                "window_start": row.window_start,
                "window_end": row.window_end,
            }
            for row in rows
        ]
        output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    else:
        with output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "agent_id",
                    "hostname",
                    "bytes_sent",
                    "bytes_received",
                    "total_bytes",
                    "window_start",
                    "window_end",
                ]
            )
            for row in rows:
                writer.writerow(
                    [
                        row.agent_id,
                        row.hostname,
                        row.bytes_sent,
                        row.bytes_received,
                        row.total_bytes,
                        row.window_start,
                        row.window_end,
                    ]
                )

    console.print(f"Exported {len(rows)} traffic row(s) to {output}")


def _fail(exc: Exception) -> None:
    error_console.print(f"[red]Error:[/red] {exc}")
    raise typer.Exit(1) from exc
