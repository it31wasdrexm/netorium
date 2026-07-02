from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from netorium.core.metadata import APP_NAME, get_version
from netorium.services.agent import (
    AgentError,
    enroll_agent,
    get_agent_status,
    run_agent_loop,
    run_agent_once,
    try_provision_agent_background_service,
)

app = typer.Typer(
    name="netorium-agent",
    help="Netorium endpoint agent for local controller enrollment.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
service_app = typer.Typer(
    help="Manage the local endpoint agent service.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
update_app = typer.Typer(
    help="Check endpoint agent updates.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()
error_console = Console(stderr=True)


@app.command()
def version() -> None:
    """Show the installed Netorium Agent version."""
    console.print(f"{APP_NAME} Agent {get_version()}")


@app.command()
def enroll(
    controller: Annotated[str, typer.Option("--controller", help="Controller base URL.")],
    token: Annotated[
        str,
        typer.Option("--token", help="One-time enrollment token."),
    ],
    hostname: Annotated[
        str | None,
        typer.Option("--hostname", help="Override the detected endpoint hostname."),
    ] = None,
) -> None:
    """Enroll this endpoint with the local controller."""
    try:
        state = enroll_agent(controller_url=controller, token=token, hostname=hostname)
    except AgentError as exc:
        _fail(exc)

    console.print("Netorium Agent enrolled.")
    table = Table(title="Netorium Agent")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Controller", state.controller_url)
    table.add_row("Agent ID", state.agent_id)
    table.add_row("Hostname", state.hostname)
    table.add_row("Zone", state.zone)
    table.add_row("State", str(state.state_path))
    console.print(table)

    background_message = try_provision_agent_background_service()
    if background_message is not None:
        console.print(background_message)
    else:
        console.print(
            "Background service was not installed automatically. "
            "Make sure you have administrator/root privileges."
        )


@app.command()
def status() -> None:
    """Show local agent enrollment status."""
    agent_status = get_agent_status()
    table = Table(title="Netorium Agent")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Enrolled", "yes" if agent_status.enrolled else "no")
    table.add_row("State", str(agent_status.state_path))

    if agent_status.enrolled:
        table.add_row("Controller", agent_status.controller_url or "-")
        table.add_row("Agent ID", agent_status.agent_id or "-")
        table.add_row("Hostname", agent_status.hostname or "-")
        table.add_row("Zone", agent_status.zone or "-")
        table.add_row("Enrolled at", agent_status.enrolled_at or "-")

    console.print(table)
    if not agent_status.enrolled:
        console.print("Run: netorium agent enroll --controller URL --token TOKEN")


@app.command("run", hidden=True)
def run() -> None:
    """Run the endpoint agent in the foreground (one heartbeat)."""
    try:
        result = run_agent_once()
    except AgentError as exc:
        _fail(exc)

    if not result.enrolled:
        error_console.print(f"[red]Error:[/red] {result.message}")
        raise typer.Exit(1)

    console.print(result.message)
    if result.accepted_at is not None:
        console.print(f"Heartbeat: {result.accepted_at}")
    if result.controller_url is not None:
        console.print(f"Controller: {result.controller_url}")
    for command_result in result.command_results:
        console.print(f"{command_result.command_id}: {command_result.status} - {command_result.message}")


@app.command("run-loop", hidden=True)
def run_loop(
    interval: Annotated[
        float,
        typer.Option("--interval", help="Heartbeat interval in seconds."),
    ] = 5.0,
) -> None:
    """Run the agent heartbeat loop continuously (used by background service)."""
    try:
        run_agent_loop(interval_seconds=interval)
    except AgentError as exc:
        _fail(exc)


@update_app.command("check")
def update_check() -> None:
    """Show agent update guidance."""
    console.print(f"Netorium Agent {get_version()}")
    console.print("Use `netorium update show` for current release and installer guidance.")


app.add_typer(update_app, name="update")


def _fail(exc: Exception) -> None:
    error_console.print(f"[red]Error:[/red] {exc}")
    raise typer.Exit(1) from exc
