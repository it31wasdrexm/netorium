from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from netorium.core.database import DatabaseError
from netorium.core.settings import ConfigError, load_settings
from netorium.services.controller import (
    DEFAULT_CONTROLLER_HOST,
    DEFAULT_CONTROLLER_PORT,
    TOKEN_PURPOSE_ENROLL,
    ControllerError,
    build_enrollment_url,
    create_enrollment_token,
    get_controller_status,
    init_controller,
    list_agents,
    serve_controller,
)

controller_app = typer.Typer(
    help="Run the local Netorium controller for office agents.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
token_app = typer.Typer(
    help="Manage controller enrollment tokens.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
agent_app = typer.Typer(
    help="Inspect enrolled endpoint agents.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()
error_console = Console(stderr=True)


@controller_app.command("init")
def init(
    host: Annotated[
        str,
        typer.Option("--host", help="Controller listen host."),
    ] = DEFAULT_CONTROLLER_HOST,
    port: Annotated[
        int,
        typer.Option("--port", help="Controller listen port."),
    ] = DEFAULT_CONTROLLER_PORT,
) -> None:
    """Initialize local controller state in SQLite."""
    try:
        config = init_controller(_database_path(), host=host, port=port)
        status = get_controller_status(_database_path())
    except (ConfigError, DatabaseError, ControllerError) as exc:
        _fail(exc)

    console.print("Netorium Controller initialized.")
    _render_config(config.host, config.port, status.enrollment_url, status.active_tokens)


@controller_app.command("status")
def status() -> None:
    """Show local controller status."""
    try:
        controller_status = get_controller_status(_database_path())
    except (ConfigError, DatabaseError, ControllerError) as exc:
        _fail(exc)

    table = Table(title="Netorium Controller")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Initialized", "yes" if controller_status.initialized else "no")
    table.add_row("Listen URL", controller_status.listen_url or "-")
    table.add_row("Enrollment URL", controller_status.enrollment_url or "-")
    table.add_row("Active enrollment tokens", str(controller_status.active_tokens))
    console.print(table)

    if not controller_status.initialized:
        console.print("Run: netorium controller init")


@controller_app.command("start")
def start(
    host: Annotated[
        str,
        typer.Option("--host", help="Controller listen host."),
    ] = DEFAULT_CONTROLLER_HOST,
    port: Annotated[
        int,
        typer.Option("--port", help="Controller listen port."),
    ] = DEFAULT_CONTROLLER_PORT,
) -> None:
    """Start the local controller HTTP process."""
    try:
        database_path = _database_path()
    except ConfigError as exc:
        _fail(exc)

    console.print("Starting Netorium Controller.")
    console.print(f"Listen: http://{host}:{port}")
    console.print(f"Enrollment URL: {build_enrollment_url(host, port)}")
    console.print("Press Ctrl+C to stop.")

    try:
        serve_controller(database_path, host=host, port=port)
    except KeyboardInterrupt:
        console.print("Netorium Controller stopped.")
    except (DatabaseError, ControllerError) as exc:
        _fail(exc)


@token_app.command("create")
def token_create(
    zone: Annotated[str, typer.Option("--zone", help="Zone assigned during enrollment.")],
    ttl: Annotated[
        str,
        typer.Option("--ttl", help="Token lifetime, for example 30m, 24h, or 7d."),
    ] = "24h",
    purpose: Annotated[
        str,
        typer.Option("--purpose", help="Token purpose."),
    ] = TOKEN_PURPOSE_ENROLL,
) -> None:
    """Create a one-time enrollment token."""
    try:
        token = create_enrollment_token(
            _database_path(),
            zone=zone,
            ttl=ttl,
            purpose=purpose,
        )
        status = get_controller_status(_database_path())
    except (ConfigError, DatabaseError, ControllerError) as exc:
        _fail(exc)

    console.print("Enrollment token created.")
    table = Table(title="Enrollment Token")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Token ID", token.token_id)
    table.add_row("Purpose", token.purpose)
    table.add_row("Zone", token.zone)
    table.add_row("Expires", token.expires_at)
    table.add_row("Controller", status.enrollment_url or "-")
    console.print(table)
    console.print("Token (shown once):")
    console.print(token.token)


@agent_app.command("list")
def agent_list() -> None:
    """List endpoint agents enrolled with the local controller."""
    try:
        agents = list_agents(_database_path())
    except (ConfigError, DatabaseError, ControllerError) as exc:
        _fail(exc)

    if not agents:
        console.print("No agents enrolled")
        return

    table = Table(title="Netorium Agents")
    table.add_column("Agent ID")
    table.add_column("Hostname")
    table.add_column("Zone")
    table.add_column("Enrolled")
    table.add_column("Last seen")
    for agent in agents:
        table.add_row(
            agent.agent_id,
            agent.hostname,
            agent.zone,
            agent.enrolled_at,
            agent.last_seen_at or "-",
        )
    console.print(table)


controller_app.add_typer(token_app, name="token")
controller_app.add_typer(agent_app, name="agent")


def _database_path() -> Path:
    settings = load_settings()
    return Path(settings.app.database_path).expanduser()


def _render_config(
    host: str,
    port: int,
    enrollment_url: str | None,
    active_tokens: int,
) -> None:
    table = Table(title="Netorium Controller")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Listen", f"http://{host}:{port}")
    table.add_row("Enrollment URL", enrollment_url or "-")
    table.add_row("Active enrollment tokens", str(active_tokens))
    console.print(table)


def _fail(exc: Exception) -> None:
    error_console.print(f"[red]Error:[/red] {exc}")
    raise typer.Exit(1) from exc
