from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from netorium.cli.branding import make_kv_table, make_table

from netorium.core.database import DatabaseError
from netorium.core.settings import ConfigError, load_settings
from netorium.services.devices import (
    DeviceError,
    DeviceNotFoundError,
    DeviceZoneNotFoundError,
    add_device,
    delete_device,
    get_device,
    list_devices,
    move_device,
)

device_app = typer.Typer(
    help="Manage devices assigned to zones.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()
error_console = Console(stderr=True)


@device_app.command("add")
def add(
    ip_address: Annotated[str, typer.Argument(help="Device IP address.")],
    zone: Annotated[str, typer.Option("--zone", help="Existing zone name.")],
    hostname: Annotated[
        str | None,
        typer.Option("--hostname", help="Optional device hostname."),
    ] = None,
) -> None:
    """Add a device to a zone."""
    try:
        device = add_device(_database_path(), ip_address=ip_address, zone_name=zone, hostname=hostname)
    except (ConfigError, DatabaseError, DeviceZoneNotFoundError, DeviceError) as exc:
        _fail(exc)

    console.print(f"Added device: {device.ip_address}")


@device_app.command("list")
def list_command() -> None:
    """List configured devices."""
    try:
        devices = list_devices(_database_path())
    except (ConfigError, DatabaseError, DeviceError) as exc:
        _fail(exc)

    if not devices:
        console.print("No devices found")
        return

    table = make_table("Devices", columns=("IP", "Zone", "Hostname"))
    for device in devices:
        table.add_row(device.ip_address, device.zone_name, _format_optional(device.hostname))
    console.print(table)


@device_app.command("show")
def show(ip_address: Annotated[str, typer.Argument(help="Device IP address.")]) -> None:
    """Show details for one device."""
    try:
        device = get_device(_database_path(), ip_address)
    except (ConfigError, DatabaseError, DeviceNotFoundError, DeviceError) as exc:
        _fail(exc)

    table = make_kv_table(f"Device: {device.ip_address}")
    table.add_row("IP", device.ip_address)
    table.add_row("Zone", device.zone_name)
    table.add_row("Hostname", _format_optional(device.hostname))
    table.add_row("Created", device.created_at)
    table.add_row("Updated", device.updated_at)
    console.print(table)


@device_app.command("move")
def move(
    ip_address: Annotated[str, typer.Argument(help="Device IP address.")],
    zone: Annotated[str, typer.Option("--zone", help="Target zone name.")],
) -> None:
    """Move a device to another zone."""
    try:
        device = move_device(_database_path(), ip_address, zone_name=zone)
    except (ConfigError, DatabaseError, DeviceNotFoundError, DeviceZoneNotFoundError, DeviceError) as exc:
        _fail(exc)

    console.print(f"Moved device {device.ip_address} to zone: {device.zone_name}")


@device_app.command("delete")
def delete(ip_address: Annotated[str, typer.Argument(help="Device IP address.")]) -> None:
    """Delete a device and write an audit entry."""
    try:
        device = delete_device(_database_path(), ip_address)
    except (ConfigError, DatabaseError, DeviceNotFoundError, DeviceError) as exc:
        _fail(exc)

    console.print(f"Deleted device: {device.ip_address}")


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
