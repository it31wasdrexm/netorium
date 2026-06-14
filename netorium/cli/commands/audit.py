from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from netorium.core.audit import AuditError, list_audit_entries
from netorium.core.database import DatabaseError
from netorium.core.settings import ConfigError, load_settings

audit_app = typer.Typer(
    help="Inspect local audit log entries.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()
error_console = Console(stderr=True)


@audit_app.command("list")
def list_command(
    limit: Annotated[
        int,
        typer.Option("--limit", "-n", min=1, max=500, help="Maximum entries to show."),
    ] = 50,
) -> None:
    """List recent audit log entries."""
    try:
        entries = list_audit_entries(str(_database_path()), limit=limit)
    except (ConfigError, DatabaseError, AuditError) as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    if not entries:
        console.print("No audit entries found")
        return

    table = Table(title="Audit Log")
    table.add_column("ID")
    table.add_column("Time")
    table.add_column("Action", no_wrap=True)
    table.add_column("Entity")
    table.add_column("Details")
    for entry in entries:
        table.add_row(
            str(entry.id),
            entry.created_at,
            entry.action,
            f"{entry.entity_type}:{entry.entity_id}",
            json.dumps(entry.details, ensure_ascii=False, sort_keys=True),
        )
    console.print(table)


def _database_path() -> Path:
    settings = load_settings()
    return Path(settings.app.database_path).expanduser()
