from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from netorium.cli.branding import make_kv_table, make_table

from netorium.core.database import DatabaseError
from netorium.core.settings import ConfigError, load_settings
from netorium.services.firewall import (
    FirewallError,
    FirewallPlan,
    block_ip,
    firewall_status,
    unblock_ip,
)

firewall_app = typer.Typer(
    help="Preview and apply firewall actions.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()
error_console = Console(stderr=True)


@firewall_app.command("status")
def status() -> None:
    """Show local firewall support status."""
    current = firewall_status()
    table = make_kv_table("Firewall Status")
    table.add_row("Platform", current.platform_name)
    table.add_row("Dry-run supported", _yes_no(current.dry_run_supported))
    table.add_row("Real firewall supported", _yes_no(current.real_firewall_supported))
    console.print(table)


@firewall_app.command("block")
def block(
    ip_address: Annotated[str, typer.Argument(help="IP address to block.")],
    reason: Annotated[str, typer.Option("--reason", help="Audit reason for the block.")],
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run/--real", help="Preview the action instead of applying it."),
    ] = True,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Confirm a real firewall change when using --real."),
    ] = False,
) -> None:
    """Preview or apply a Windows Firewall block."""
    try:
        plan = block_ip(
            _database_path(),
            ip_address=ip_address,
            reason=reason,
            dry_run=dry_run,
            yes=yes,
        )
    except (ConfigError, DatabaseError, FirewallError) as exc:
        _fail(exc)

    _render_plan(plan)


@firewall_app.command("unblock")
def unblock(
    ip_address: Annotated[str, typer.Argument(help="IP address to unblock.")],
    reason: Annotated[str, typer.Option("--reason", help="Audit reason for the unblock.")],
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run/--real", help="Preview the action instead of applying it."),
    ] = True,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Confirm a real firewall change when using --real."),
    ] = False,
) -> None:
    """Preview or apply a Windows Firewall unblock."""
    try:
        plan = unblock_ip(
            _database_path(),
            ip_address=ip_address,
            reason=reason,
            dry_run=dry_run,
            yes=yes,
        )
    except (ConfigError, DatabaseError, FirewallError) as exc:
        _fail(exc)

    _render_plan(plan)


def _render_plan(plan: FirewallPlan) -> None:
    table = make_kv_table(f"Firewall {plan.action}")
    table.add_row("IP", plan.ip_address)
    table.add_row("Mode", "dry-run" if plan.dry_run else "real")
    table.add_row("Reason", plan.reason)
    table.add_row("Platform", plan.platform_name)
    table.add_row("Command", plan.command)
    console.print(table)
    if plan.dry_run:
        console.print("Dry run only. No firewall rules were changed.")


def _database_path() -> Path:
    settings = load_settings()
    return Path(settings.app.database_path).expanduser()


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _fail(exc: Exception) -> None:
    error_console.print(f"[red]Error:[/red] {exc}")
    raise typer.Exit(1) from exc
