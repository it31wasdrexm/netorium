from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from netorium.cli.branding import make_kv_table, make_table

from netorium.core.database import DatabaseError
from netorium.core.settings import ConfigError, load_settings
from netorium.services.zones import (
    ZoneError,
    ZoneNotFoundError,
    add_zone,
    delete_zone,
    get_zone,
    list_zones,
)

zone_app = typer.Typer(
    help="Manage building zones.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()
error_console = Console(stderr=True)


@zone_app.command("add")
def add(
    name: Annotated[str, typer.Argument(help="Unique zone name.")],
    floor: Annotated[int | None, typer.Option("--floor", help="Building floor.")] = None,
    department: Annotated[
        str | None,
        typer.Option("--department", help="Department or owner for this zone."),
    ] = None,
    description: Annotated[
        str,
        typer.Option("--description", help="Human-readable zone description."),
    ] = "",
) -> None:
    """Add a zone to the local database."""
    try:
        zone = add_zone(
            _database_path(),
            name=name,
            floor=floor,
            department=department,
            description=description,
        )
    except (ConfigError, DatabaseError, ZoneError) as exc:
        _fail(exc)

    console.print(f"Added zone: {zone.name}")


@zone_app.command("list")
def list_command() -> None:
    """List configured zones."""
    try:
        zones = list_zones(_database_path())
    except (ConfigError, DatabaseError, ZoneError) as exc:
        _fail(exc)

    if not zones:
        console.print("No zones found")
        return

    table = make_table("Zones", columns=("Name", "Floor", "Department", "Description"))
    for zone in zones:
        table.add_row(
            zone.name,
            _format_optional(zone.floor),
            _format_optional(zone.department),
            zone.description or "-",
        )
    console.print(table)


@zone_app.command("show")
def show(name: Annotated[str, typer.Argument(help="Zone name.")]) -> None:
    """Show details for one zone."""
    try:
        zone = get_zone(_database_path(), name)
    except (ConfigError, DatabaseError, ZoneError) as exc:
        _fail(exc)

    table = make_kv_table(f"Zone: {zone.name}")
    table.add_row("Name", zone.name)
    table.add_row("Floor", _format_optional(zone.floor))
    table.add_row("Department", _format_optional(zone.department))
    table.add_row("Description", zone.description or "-")
    table.add_row("Created", zone.created_at)
    table.add_row("Updated", zone.updated_at)
    console.print(table)


@zone_app.command("delete")
def delete(name: Annotated[str, typer.Argument(help="Zone name.")]) -> None:
    """Delete a zone and write an audit entry."""
    try:
        zone = delete_zone(_database_path(), name)
    except (ConfigError, DatabaseError, ZoneNotFoundError, ZoneError) as exc:
        _fail(exc)

    console.print(f"Deleted zone: {zone.name}")


def _database_path() -> Path:
    settings = load_settings()
    return Path(settings.app.database_path).expanduser()


def _format_optional(value: object) -> str:
    if value is None:
        return "-"
    return str(value)


def _fail(exc: Exception) -> None:
    error_console.print(f"[red]Error:[/red] {exc}")
    raise typer.Exit(1) from exc
