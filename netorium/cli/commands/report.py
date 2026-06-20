from __future__ import annotations

from typing import Annotated
from pathlib import Path
import typer
from rich.console import Console
from rich.table import Table

from netorium.core.settings import load_settings
from netorium.services.traffic import (
    export_traffic_csv,
    export_traffic_json,
    get_traffic_report,
)

report_app = typer.Typer(
    help="Analyze traffic reports and detect network anomalies.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()
error_console = Console(stderr=True)

def _database_path() -> Path:
    settings = load_settings()
    return Path(settings.app.database_path).expanduser()

@report_app.command("traffic")
def report_traffic(
    threshold: Annotated[
        float,
        typer.Option("--threshold", "-t", help="Anomaly threshold in Megabytes (MB)."),
    ] = 1000.0,
) -> None:
    """Show traffic usage report for all devices."""
    try:
        records = get_traffic_report(_database_path(), threshold_mb=threshold)
    except Exception as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    if not records:
        console.print("No devices or agents found to report traffic.")
        return

    table = Table(title=f"Traffic Report (Threshold: {threshold} MB)")
    table.add_column("IP Address")
    table.add_column("Hostname")
    table.add_column("Zone")
    table.add_column("Download (MB)", justify="right")
    table.add_column("Upload (MB)", justify="right")
    table.add_column("Total (MB)", justify="right")
    table.add_column("Status")

    for r in records:
        status = "[red]ANOMALY[/red]" if r.is_anomaly else "[green]OK[/green]"
        table.add_row(
            r.ip_address,
            r.hostname,
            r.zone_name,
            f"{r.download_mb:.2f}",
            f"{r.upload_mb:.2f}",
            f"{r.total_mb:.2f}",
            status,
        )
    console.print(table)


@report_app.command("anomalies")
def report_anomalies(
    threshold: Annotated[
        float,
        typer.Option("--threshold", "-t", help="Anomaly threshold in Megabytes (MB)."),
    ] = 1000.0,
) -> None:
    """Show only devices with anomalous traffic levels."""
    try:
        records = get_traffic_report(_database_path(), threshold_mb=threshold)
    except Exception as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    anomalies = [r for r in records if r.is_anomaly]
    if not anomalies:
        console.print(f"[green]No traffic anomalies detected[/green] (Threshold: {threshold} MB).")
        return

    table = Table(title=f"Traffic Anomalies (Threshold: {threshold} MB)", border_style="red")
    table.add_column("IP Address")
    table.add_column("Hostname")
    table.add_column("Zone")
    table.add_column("Total (MB)", justify="right")
    table.add_column("Reason")

    for r in anomalies:
        table.add_row(
            r.ip_address,
            r.hostname,
            r.zone_name,
            f"{r.total_mb:.2f}",
            r.anomaly_reason,
        )
    console.print(table)


@report_app.command("export")
def report_export(
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Output file path."),
    ],
    format: Annotated[
        str,
        typer.Option("--format", "-f", help="Export format: csv or json."),
    ] = "csv",
    threshold: Annotated[
        float,
        typer.Option("--threshold", "-t", help="Anomaly threshold in Megabytes (MB)."),
    ] = 1000.0,
) -> None:
    """Export traffic report to a file (CSV or JSON)."""
    fmt = format.lower()
    if fmt not in ("csv", "json"):
        error_console.print("[red]Error:[/red] Format must be 'csv' or 'json'.")
        raise typer.Exit(1)

    try:
        records = get_traffic_report(_database_path(), threshold_mb=threshold)
    except Exception as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    if not records:
        console.print("No devices or agents found to export.")
        return

    if fmt == "csv":
        content = export_traffic_csv(records)
    else:
        content = export_traffic_json(records)

    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
    except OSError as exc:
        error_console.print(f"[red]Error:[/red] Could not write to {output}: {exc}")
        raise typer.Exit(1) from exc

    console.print(f"Report exported to {output} ({fmt.upper()}, {len(records)} records).")

