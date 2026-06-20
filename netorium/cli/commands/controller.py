from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from netorium.core.database import DatabaseError
from netorium.core.settings import ConfigError, load_settings
from netorium.services.controller import (
    AgentCommandRecord,
    DEFAULT_CONTROLLER_HOST,
    DEFAULT_CONTROLLER_PORT,
    TOKEN_PURPOSE_ENROLL,
    ControllerError,
    build_enrollment_url,
    create_enrollment_token,
    enqueue_agent_app_command,
    enqueue_agent_firewall_command,
    enqueue_agent_site_command,
    enqueue_agent_speed_command,
    get_controller_status,
    init_controller,
    list_agent_commands,
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
agent_command_app = typer.Typer(
    help="Queue and inspect endpoint agent commands.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
policy_app = typer.Typer(
    help="Short commands for endpoint access policies.",
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


@agent_command_app.command("firewall")
def agent_command_firewall(
    agent_id: Annotated[str, typer.Option("--agent-id", help="Target endpoint agent ID.")],
    action: Annotated[
        str,
        typer.Option("--action", help="Endpoint firewall action: block or unblock."),
    ],
    ip_address: Annotated[
        str,
        typer.Option("--ip", help="Target IP address for the endpoint firewall command."),
    ],
    reason: Annotated[str, typer.Option("--reason", help="Required audit reason.")],
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run/--real",
            help="Queue a dry-run command or a real Windows endpoint command.",
        ),
    ] = True,
) -> None:
    """Queue an endpoint firewall command for an enrolled agent."""
    try:
        command = enqueue_agent_firewall_command(
            _database_path(),
            agent_id=agent_id,
            action=action,
            ip_address=ip_address,
            reason=reason,
            dry_run=dry_run,
        )
    except (ConfigError, DatabaseError, ControllerError) as exc:
        _fail(exc)

    _render_agent_command(command)


@agent_command_app.command("site")
def agent_command_site(
    agent_id: Annotated[str, typer.Option("--agent-id", help="Target endpoint agent ID.")],
    action: Annotated[
        str,
        typer.Option("--action", help="Site access action: block or unblock."),
    ],
    domain: Annotated[
        str,
        typer.Option("--domain", help="Domain or URL to block or unblock."),
    ],
    reason: Annotated[str, typer.Option("--reason", help="Required audit reason.")],
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run/--real",
            help="Queue a dry-run command or a real Windows endpoint command.",
        ),
    ] = True,
) -> None:
    """Queue a website access command for an enrolled agent."""
    try:
        command = enqueue_agent_site_command(
            _database_path(),
            agent_id=agent_id,
            action=action,
            domain=domain,
            reason=reason,
            dry_run=dry_run,
        )
    except (ConfigError, DatabaseError, ControllerError) as exc:
        _fail(exc)

    _render_agent_command(command)


@agent_command_app.command("binary")
@agent_command_app.command("app")
def agent_command_application(
    agent_id: Annotated[str, typer.Option("--agent-id", help="Target endpoint agent ID.")],
    action: Annotated[
        str,
        typer.Option("--action", help="Application network action: block or unblock."),
    ],
    executable: Annotated[
        str,
        typer.Option("--executable", help="Executable name or full path, for example dota2.exe."),
    ],
    reason: Annotated[str, typer.Option("--reason", help="Required audit reason.")],
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run/--real",
            help="Queue a dry-run command or a real Windows endpoint command.",
        ),
    ] = True,
) -> None:
    """Queue an application network command for an enrolled agent."""
    try:
        command = enqueue_agent_app_command(
            _database_path(),
            agent_id=agent_id,
            action=action,
            executable=executable,
            reason=reason,
            dry_run=dry_run,
        )
    except (ConfigError, DatabaseError, ControllerError) as exc:
        _fail(exc)

    _render_agent_command(command)


@agent_command_app.command("speed")
def agent_command_speed(
    agent_id: Annotated[str, typer.Option("--agent-id", help="Target endpoint agent ID.")],
    reason: Annotated[str, typer.Option("--reason", help="Required audit reason.")],
    download_kbps: Annotated[
        int | None,
        typer.Option("--download-kbps", help="Download limit in kilobits per second."),
    ] = None,
    upload_kbps: Annotated[
        int | None,
        typer.Option("--upload-kbps", help="Upload limit in kilobits per second."),
    ] = None,
    clear: Annotated[
        bool,
        typer.Option("--clear", help="Clear the endpoint speed limit."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run/--real",
            help="Queue a dry-run command or a real Windows endpoint command.",
        ),
    ] = True,
) -> None:
    """Queue a speed limit command for an enrolled agent."""
    try:
        command = enqueue_agent_speed_command(
            _database_path(),
            agent_id=agent_id,
            download_kbps=download_kbps,
            upload_kbps=upload_kbps,
            clear=clear,
            reason=reason,
            dry_run=dry_run,
        )
    except (ConfigError, DatabaseError, ControllerError) as exc:
        _fail(exc)

    _render_agent_command(command)


@agent_command_app.command("list")
def agent_command_list(
    agent_id: Annotated[
        str | None,
        typer.Option("--agent-id", help="Only show commands for this endpoint agent."),
    ] = None,
) -> None:
    """List queued and completed endpoint agent commands."""
    try:
        commands = list_agent_commands(_database_path(), agent_id=agent_id)
    except (ConfigError, DatabaseError, ControllerError) as exc:
        _fail(exc)

    if not commands:
        console.print("No agent commands")
        return

    table = Table(title="Agent Commands")
    table.add_column("Command ID")
    table.add_column("Agent ID")
    table.add_column("Type")
    table.add_column("Status")
    table.add_column("Payload")
    table.add_column("Result")
    for command in commands:
        table.add_row(
            command.command_id,
            command.agent_id,
            command.command_type,
            command.status,
            _payload_summary(command.payload),
            command.result_message or "-",
        )
    console.print(table)


@policy_app.command("agents")
def policy_agents() -> None:
    """List connected endpoint agents."""
    agent_list()


@policy_app.command("list")
def policy_list(
    agent_id: Annotated[
        str | None,
        typer.Argument(help="Optional endpoint agent ID."),
    ] = None,
) -> None:
    """List queued and completed endpoint policy commands."""
    agent_command_list(agent_id=agent_id)


@policy_app.command("ip")
def policy_ip(
    agent_id: Annotated[str, typer.Argument(help="Endpoint agent ID.")],
    ip_address: Annotated[str, typer.Argument(help="Target IP address.")],
    reason: Annotated[str, typer.Option("--reason", "-r", help="Required audit reason.")],
    unblock: Annotated[
        bool,
        typer.Option("--unblock", help="Remove the block instead of adding it."),
    ] = False,
    real: Annotated[
        bool,
        typer.Option("--real", help="Apply on the Windows endpoint. Default is dry-run."),
    ] = False,
) -> None:
    """Block or unblock an IP on an endpoint."""
    try:
        command = enqueue_agent_firewall_command(
            _database_path(),
            agent_id=agent_id,
            action=_policy_action(unblock),
            ip_address=ip_address,
            reason=reason,
            dry_run=not real,
        )
    except (ConfigError, DatabaseError, ControllerError) as exc:
        _fail(exc)

    _render_agent_command(command)


@policy_app.command("site")
def policy_site(
    agent_id: Annotated[str, typer.Argument(help="Endpoint agent ID.")],
    domain: Annotated[str, typer.Argument(help="Domain or URL.")],
    reason: Annotated[str, typer.Option("--reason", "-r", help="Required audit reason.")],
    unblock: Annotated[
        bool,
        typer.Option("--unblock", help="Remove the block instead of adding it."),
    ] = False,
    real: Annotated[
        bool,
        typer.Option("--real", help="Apply on the Windows endpoint. Default is dry-run."),
    ] = False,
) -> None:
    """Block or unblock a website on an endpoint."""
    try:
        command = enqueue_agent_site_command(
            _database_path(),
            agent_id=agent_id,
            action=_policy_action(unblock),
            domain=domain,
            reason=reason,
            dry_run=not real,
        )
    except (ConfigError, DatabaseError, ControllerError) as exc:
        _fail(exc)

    _render_agent_command(command)


@policy_app.command("app")
@policy_app.command("game")
def policy_app_command(
    agent_id: Annotated[str, typer.Argument(help="Endpoint agent ID.")],
    executable: Annotated[str, typer.Argument(help="Executable name or full path.")],
    reason: Annotated[str, typer.Option("--reason", "-r", help="Required audit reason.")],
    unblock: Annotated[
        bool,
        typer.Option("--unblock", help="Remove the block instead of adding it."),
    ] = False,
    real: Annotated[
        bool,
        typer.Option("--real", help="Apply on the Windows endpoint. Default is dry-run."),
    ] = False,
) -> None:
    """Block or unblock an application/game on an endpoint."""
    try:
        command = enqueue_agent_app_command(
            _database_path(),
            agent_id=agent_id,
            action=_policy_action(unblock),
            executable=executable,
            reason=reason,
            dry_run=not real,
        )
    except (ConfigError, DatabaseError, ControllerError) as exc:
        _fail(exc)

    _render_agent_command(command)


@policy_app.command("speed")
def policy_speed(
    agent_id: Annotated[str, typer.Argument(help="Endpoint agent ID.")],
    reason: Annotated[str, typer.Option("--reason", "-r", help="Required audit reason.")],
    download_kbps: Annotated[
        int | None,
        typer.Option("--down", help="Download limit in kilobits per second."),
    ] = None,
    upload_kbps: Annotated[
        int | None,
        typer.Option("--up", help="Upload limit in kilobits per second."),
    ] = None,
    real: Annotated[
        bool,
        typer.Option("--real", help="Apply on the Windows endpoint. Default is dry-run."),
    ] = False,
) -> None:
    """Set an endpoint speed limit."""
    try:
        command = enqueue_agent_speed_command(
            _database_path(),
            agent_id=agent_id,
            download_kbps=download_kbps,
            upload_kbps=upload_kbps,
            clear=False,
            reason=reason,
            dry_run=not real,
        )
    except (ConfigError, DatabaseError, ControllerError) as exc:
        _fail(exc)

    _render_agent_command(command)


@policy_app.command("clear-speed")
def policy_clear_speed(
    agent_id: Annotated[str, typer.Argument(help="Endpoint agent ID.")],
    reason: Annotated[str, typer.Option("--reason", "-r", help="Required audit reason.")],
    real: Annotated[
        bool,
        typer.Option("--real", help="Apply on the Windows endpoint. Default is dry-run."),
    ] = False,
) -> None:
    """Clear an endpoint speed limit."""
    try:
        command = enqueue_agent_speed_command(
            _database_path(),
            agent_id=agent_id,
            download_kbps=None,
            upload_kbps=None,
            clear=True,
            reason=reason,
            dry_run=not real,
        )
    except (ConfigError, DatabaseError, ControllerError) as exc:
        _fail(exc)

    _render_agent_command(command)


agent_app.add_typer(agent_command_app, name="command")
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


def _payload_summary(payload: dict[str, object]) -> str:
    action = str(payload.get("action", "-"))
    dry_run = payload.get("dry_run", "-")
    if "ip_address" in payload:
        return f"{action} {payload.get('ip_address', '-')} dry-run={dry_run}"
    if "domain" in payload:
        return f"{action} site {payload.get('domain', '-')} dry-run={dry_run}"
    if "executable" in payload:
        return f"{action} app {payload.get('executable', '-')} dry-run={dry_run}"
    if action == "clear":
        return f"clear speed dry-run={dry_run}"
    if "download_kbps" in payload or "upload_kbps" in payload:
        return (
            f"limit speed down={payload.get('download_kbps', '-')} "
            f"up={payload.get('upload_kbps', '-')} dry-run={dry_run}"
        )
    return f"{action} dry-run={dry_run}"


def _policy_action(unblock: bool) -> str:
    return "unblock" if unblock else "block"


def _render_agent_command(command: AgentCommandRecord) -> None:
    console.print("Endpoint command queued.")
    table = Table(title="Agent Command")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Command ID", command.command_id)
    table.add_row("Agent ID", command.agent_id)
    table.add_row("Type", command.command_type)
    table.add_row("Status", command.status)
    table.add_row("Payload", _payload_summary(command.payload))
    console.print(table)


def _fail(exc: Exception) -> None:
    error_console.print(f"[red]Error:[/red] {exc}")
    raise typer.Exit(1) from exc
