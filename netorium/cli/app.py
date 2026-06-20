import platform
import shlex
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from typer.main import get_command

from netorium.cli.commands.ad import ad_app
from netorium.cli.commands.audit import audit_app
from netorium.cli.commands.config import config_app
from netorium.cli.commands.controller import controller_app, policy_app
from netorium.cli.commands.deploy import deploy_app
from netorium.cli.commands.device import device_app
from netorium.cli.commands.docs import docs_app
from netorium.cli.commands.firewall import firewall_app
from netorium.cli.commands.prtg import prtg_app
from netorium.cli.commands.telegram import telegram_app
from netorium.cli.commands.update import update_app
from netorium.cli.commands.zone import zone_app
from netorium.cli.commands.report import report_app
from netorium.core.metadata import APP_NAME, get_version
from netorium.core.settings import default_config_path
from netorium.services.update_notifications import StartupUpdateNotice, get_startup_update_notice
from netorium.services.uninstaller import (
    UninstallError,
    UninstallPlan,
    UninstallResult,
    build_uninstall_plan,
    execute_uninstall_plan,
    format_command,
)

console = Console()
error_console = Console(stderr=True)

app = typer.Typer(
    name="netorium",
    help="Netorium CLI for building-level network access control.",
    no_args_is_help=False,
    rich_markup_mode="rich",
)

app.add_typer(config_app, name="config")
app.add_typer(docs_app, name="docs")
app.add_typer(update_app, name="update")
app.add_typer(controller_app, name="controller")
app.add_typer(policy_app, name="policy")
app.add_typer(deploy_app, name="deploy")
app.add_typer(zone_app, name="zone")
app.add_typer(device_app, name="device")
app.add_typer(firewall_app, name="firewall")
app.add_typer(prtg_app, name="prtg")
app.add_typer(ad_app, name="ad")
app.add_typer(telegram_app, name="telegram")
app.add_typer(report_app, name="report")
app.add_typer(audit_app, name="audit")
app.add_typer(agent_app, name="agent")


def _parse_interactive_line(line: str) -> list[str]:
    try:
        return shlex.split(line)
    except ValueError as exc:
        console.print(f"[red]Could not parse command:[/] {exc}")
        return []


def _normalize_interactive_args(args: list[str]) -> list[str] | None:
    if args and args[0].lower() == "netorium":
        args = args[1:]

    if not args:
        return ["--help"]

    first_arg = args[0].lower()
    if first_arg in {"exit", "quit"}:
        return None
    if first_arg in {"help", "?"}:
        if len(args) == 1:
            return ["--help"]
        return [*args[1:], "--help"]

    return args


def _run_interactive_command(args: list[str]) -> None:
    click_command = get_command(app)
    try:
        click_command.main(args=args, prog_name="netorium", standalone_mode=False)
    except SystemExit:
        return
    except Exception as exc:
        if exc.__class__.__name__ == "Exit":
            return

        show = getattr(exc, "show", None)
        if callable(show):
            show()
            return

        raise


def _run_interactive_shell() -> None:
    _render_interactive_header()
    _render_startup_update_notice()

    while True:
        try:
            line = input("netorium> ")
        except (EOFError, KeyboardInterrupt):
            console.print()
            break

        args = _normalize_interactive_args(_parse_interactive_line(line))
        if args is None:
            break
        if not args:
            continue

        _run_interactive_command(args)

    console.print("Leaving Netorium.")


def _render_interactive_header() -> None:
    console.print(
        Panel.fit(
            f"[bold]{APP_NAME} {get_version()}[/]\n"
            "Netorium interactive mode. Type commands without the netorium prefix.\n"
            "[dim]Try: version, doctor, config path, update show, help, exit[/]",
            title="netorium",
            border_style="cyan",
        )
    )


def _render_startup_update_notice() -> None:
    notice = get_startup_update_notice()
    if notice is None:
        return

    console.print(_startup_update_panel(notice))


def _startup_update_panel(notice: StartupUpdateNotice) -> Panel:
    platform = notice.platform
    body = (
        f"[bold yellow]Update available:[/] {notice.info.latest_version}\n"
        f"Current version: {notice.info.current_version}\n"
        f"Platform: {platform.platform_name}\n"
        f"Run: [bold]{platform.install_command}[/]\n"
        f"Standalone: {platform.standalone_command}\n"
        f"Release: {notice.info.release_url}"
    )
    return Panel.fit(body, title="Netorium Update", border_style="yellow")


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Start the interactive shell when no command is provided."""
    if ctx.invoked_subcommand is None:
        _run_interactive_shell()


@app.command()
def version() -> None:
    """Show the installed Netorium CLI version."""
    console.print(f"{APP_NAME} {get_version()}")


@app.command()
def doctor(
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show additional environment details."),
    ] = False,
) -> None:
    """Run basic local environment checks."""
    config_path = default_config_path()
    table = Table(title="Netorium Doctor")
    table.add_column("Check")
    table.add_column("Result")
    table.add_row("CLI", "OK")
    table.add_row("Version", get_version())
    table.add_row("Platform", platform.system() or "unknown")
    table.add_row("Config path", str(config_path))
    table.add_row("Config file", "found" if config_path.exists() else "missing")
    console.print(table)
    if verbose:
        console.print("Run `netorium config validate` to validate the active configuration.")


@app.command("unistall", hidden=True)
@app.command("uninstall")
def uninstall(
    remove_data: Annotated[
        bool,
        typer.Option(
            "--remove-data/--keep-data",
            help="Remove Netorium user config, data, and cache directories.",
        ),
    ] = False,
    package_manager: Annotated[
        str,
        typer.Option(
            "--package-manager",
            help="Package uninstall method: auto, pipx, pip, or none.",
        ),
    ] = "auto",
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Actually uninstall. Without this, only a dry-run is shown."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Force preview mode even when --yes is provided."),
    ] = False,
) -> None:
    """Preview or run a local Netorium CLI uninstall."""
    try:
        plan = build_uninstall_plan(
            remove_data=remove_data,
            package_manager=package_manager,
        )
    except UninstallError as exc:
        _fail(exc)

    is_dry_run = dry_run or not yes
    _render_uninstall_plan(plan, dry_run=is_dry_run)

    if is_dry_run:
        console.print("Dry run only. No package or user data was removed.")
        console.print("Run with --yes to uninstall the package.")
        if not remove_data:
            console.print("Add --remove-data with --yes to remove Netorium config and local data too.")
        return

    try:
        result = execute_uninstall_plan(plan)
    except UninstallError as exc:
        _fail(exc)

    _render_uninstall_result(result)


def _render_uninstall_plan(plan: UninstallPlan, *, dry_run: bool) -> None:
    table = Table(title="Netorium Uninstall")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Mode", "dry-run" if dry_run else "real")
    table.add_row("Package", plan.package_name)
    table.add_row("Package manager", plan.package_manager)
    table.add_row(
        "Package command",
        format_command(plan.package_command) if plan.package_command is not None else "none",
    )
    table.add_row("Remove data", "yes" if plan.remove_data else "no")
    console.print(table)

    if plan.path_targets:
        targets_table = Table(title="Data Targets")
        targets_table.add_column("Target")
        targets_table.add_column("Path")
        targets_table.add_column("Exists")
        for target in plan.path_targets:
            targets_table.add_row(
                target.label,
                str(target.path),
                "yes" if target.path.exists() or target.path.is_symlink() else "no",
            )
        console.print(targets_table)

    if plan.external_database_path is not None:
        console.print(
            "[yellow]Configured database path is outside the Netorium data directory and "
            f"will not be removed automatically:[/] {plan.external_database_path}"
        )


def _render_uninstall_result(result: UninstallResult) -> None:
    if result.package_command_ran:
        console.print("Package uninstall command completed.")
    else:
        console.print("Package uninstall was skipped.")

    for path in result.removed_paths:
        console.print(f"Removed: {path}")

    for path in result.skipped_paths:
        console.print(f"Skipped missing path: {path}")

    console.print("Netorium uninstall completed.")


def _fail(exc: Exception) -> None:
    error_console.print(f"[red]Error:[/red] {exc}")
    raise typer.Exit(1) from exc
