import platform
import shlex
import subprocess
import sys
from typing import Annotated

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from typer.main import get_command

from netorium.cli.agent import app as endpoint_agent_app
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
from netorium.services.controller_service import (
    ControllerServiceError,
    resolve_netorium_executable,
    uninstall_services_silently,
    reexec_windows_admin_if_needed,
)
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

_HELP_EPILOG = (
    "Quick start: netorium | netorium controller install-service | "
    "netorium uninstall. Shell commands: help, controller status, exit."
)
_UNINSTALL_CONTEXT_SETTINGS = {"allow_extra_args": True, "ignore_unknown_options": True}

app = typer.Typer(
    name="netorium",
    help=(
        "[bold]Netorium[/] CLI for building-level network access control. "
        "Local controller, endpoint agents, policies, reports, and integrations."
    ),
    epilog=_HELP_EPILOG,
    context_settings={"help_option_names": ["-h", "--help"]},
    no_args_is_help=False,
    rich_markup_mode="rich",
)

app.add_typer(config_app, name="config", rich_help_panel="Setup")
app.add_typer(docs_app, name="docs", rich_help_panel="Setup")
app.add_typer(update_app, name="update", rich_help_panel="Setup")
app.add_typer(controller_app, name="controller", rich_help_panel="Controller")
app.add_typer(policy_app, name="policy", rich_help_panel="Controller")
app.add_typer(deploy_app, name="deploy", rich_help_panel="Controller")
app.add_typer(endpoint_agent_app, name="agent", rich_help_panel="Controller")
app.add_typer(zone_app, name="zone", rich_help_panel="Inventory")
app.add_typer(device_app, name="device", rich_help_panel="Inventory")
app.add_typer(firewall_app, name="firewall", rich_help_panel="Policy")
app.add_typer(report_app, name="report", rich_help_panel="Policy")
app.add_typer(audit_app, name="audit", rich_help_panel="Policy")
app.add_typer(prtg_app, name="prtg", rich_help_panel="Integrations")
app.add_typer(ad_app, name="ad", rich_help_panel="Integrations")
app.add_typer(telegram_app, name="telegram", rich_help_panel="Integrations")


def _parse_interactive_line(line: str) -> list[str]:
    try:
        return [_normalize_dash_arg(arg) for arg in shlex.split(line)]
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

        if args[0].lower() == "sudo":
            _run_interactive_sudo(args)
            continue

        _run_interactive_command(args)

    console.print("Leaving Netorium.")


def _run_interactive_sudo(args: list[str]) -> None:
    if len(args) < 2:
        console.print("[red]Usage:[/] sudo <command> ...")
        return

    resolved = list(args)
    if resolved[1].lower() == "netorium":
        try:
            resolved[1] = resolve_netorium_executable()
        except ControllerServiceError as exc:
            error_console.print(f"[red]Error:[/red] {exc}")
            return

    try:
        result = subprocess.run(resolved)
    except FileNotFoundError:
        error_console.print(f"[red]Command not found:[/] {resolved[0]}")
        return

    if result.returncode != 0:
        error_console.print(f"[red]sudo exited with code {result.returncode}[/]")


def _render_interactive_header() -> None:
    console.print(
        Panel.fit(
            f"[bold]{APP_NAME} {get_version()}[/]\n"
            "Interactive command center for the local controller and endpoint policies.",
            title="Netorium Command Center",
            border_style="cyan",
        )
    )
    shortcuts = Table(title="Common Commands", box=box.SIMPLE, show_header=True)
    shortcuts.add_column("Task", style="cyan")
    shortcuts.add_column("Command")
    shortcuts.add_row("Controller", "controller status | controller install-service")
    shortcuts.add_row("Updates", "update check | update install")
    shortcuts.add_row("Cleanup", "uninstall | uninstall --remove-data")
    shortcuts.add_row("Help", "help | help controller | exit")
    console.print(shortcuts)


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


@app.command(rich_help_panel="Essentials")
def version() -> None:
    """Show the installed Netorium CLI version."""
    console.print(f"{APP_NAME} {get_version()}")


@app.command(rich_help_panel="Essentials")
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


@app.command("unistall", hidden=True, context_settings=_UNINSTALL_CONTEXT_SETTINGS)
@app.command(
    "uninstall",
    context_settings=_UNINSTALL_CONTEXT_SETTINGS,
    rich_help_panel="Lifecycle",
)
def uninstall(
    ctx: typer.Context,
    remove_data: Annotated[
        bool | None,
        typer.Option(
            "--remove-data/--keep-data",
            help="Remove Netorium user config, data, and cache directories too.",
            show_default=False,
        ),
    ] = None,
    package_manager: Annotated[
        str,
        typer.Option(
            "--package-manager",
            help="Package uninstall method: auto, pipx, pip, standalone, or none.",
        ),
    ] = "auto",
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Skip prompts and uninstall the package."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview the uninstall plan without removing anything."),
    ] = False,
) -> None:
    """Uninstall Netorium gracefully and completely."""
    if sys.platform.startswith("win"):
        reexec_windows_admin_if_needed(sys.argv[1:])

    yes, dry_run, remove_data, package_manager = _apply_uninstall_extra_args(
        ctx.args,
        yes=yes,
        dry_run=dry_run,
        remove_data=remove_data,
        package_manager=package_manager,
    )

    if dry_run:
        _preview_uninstall(remove_data=bool(remove_data), package_manager=package_manager)
        return

    if not yes:
        console.print(
            Panel.fit(
                "This will remove the installed Netorium command.\n"
                "You can keep or remove local config, database, and cache in the next step.",
                title="Netorium Uninstall",
                border_style="yellow",
            )
        )
        if not typer.confirm("Uninstall Netorium now?", default=False):
            console.print("Cancelled. No package or user data was removed.")
            return

        if remove_data is None:
            remove_data = typer.confirm(
                "Remove Netorium config, database, and cache too?",
                default=False,
            )

    # Clean up services completely on both Windows and Linux before actual deletion
    uninstall_services_silently()
    _execute_uninstall(remove_data=bool(remove_data), package_manager=package_manager)


def _preview_uninstall(*, remove_data: bool, package_manager: str) -> None:
    try:
        plan = build_uninstall_plan(
            remove_data=remove_data,
            package_manager=package_manager,
        )
    except UninstallError as exc:
        _fail(exc)

    _render_uninstall_plan(plan, dry_run=True)
    console.print("Preview only. No package or user data was removed.")
    console.print("Run `netorium uninstall` for guided removal, or add `--yes` for automation.")
    if not remove_data:
        console.print("Add `--remove-data` to preview config, database, and cache removal too.")


def _execute_uninstall(*, remove_data: bool, package_manager: str) -> None:
    try:
        plan = build_uninstall_plan(
            remove_data=remove_data,
            package_manager=package_manager,
        )
    except UninstallError as exc:
        _fail(exc)

    _render_uninstall_plan(plan, dry_run=False)
    try:
        result = execute_uninstall_plan(plan)
    except UninstallError as exc:
        _fail(exc)

    _render_uninstall_result(result)


def _render_uninstall_plan(plan: UninstallPlan, *, dry_run: bool) -> None:
    table = Table(title="Netorium Uninstall", box=box.SIMPLE_HEAVY)
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Mode", "preview" if dry_run else "confirmed")
    table.add_row("Package", plan.package_name)
    table.add_row("Package manager", plan.package_manager)
    table.add_row(
        "Package command",
        format_command(plan.package_command) if plan.package_command is not None else "none",
    )
    table.add_row("Command timing", "after Netorium exits" if plan.package_command_detached else "now")
    table.add_row("Remove data", "yes" if plan.remove_data else "no")
    console.print(table)

    if plan.path_targets:
        targets_table = Table(title="Data Targets", box=box.SIMPLE)
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

    if plan.deferred_path_targets:
        deferred_table = Table(title="Scheduled Cleanup Targets", box=box.SIMPLE)
        deferred_table.add_column("Target")
        deferred_table.add_column("Path")
        deferred_table.add_column("Timing")
        for target in plan.deferred_path_targets:
            deferred_table.add_row(target.label, str(target.path), "after exit")
        console.print(deferred_table)

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

    for path in result.deferred_paths:
        console.print(f"Scheduled after exit: {path}")

    console.print("Netorium uninstall completed.")


def _normalize_dash_arg(arg: str) -> str:
    if arg.startswith(("—", "–", "−")):
        return "--" + arg[1:]
    return arg


def _apply_uninstall_extra_args(
    extra_args: list[str],
    *,
    yes: bool,
    dry_run: bool,
    remove_data: bool | None,
    package_manager: str,
) -> tuple[bool, bool, bool | None, str]:
    args = [_normalize_dash_arg(arg) for arg in extra_args]
    index = 0
    unknown_args: list[str] = []
    while index < len(args):
        arg = args[index]
        if arg == "--yes":
            yes = True
        elif arg == "--dry-run":
            dry_run = True
        elif arg == "--remove-data":
            remove_data = True
        elif arg == "--keep-data":
            remove_data = False
        elif arg == "--package-manager":
            index += 1
            if index >= len(args):
                error_console.print("[red]Error:[/red] --package-manager needs a value.")
                raise typer.Exit(2)
            package_manager = args[index]
        elif arg.startswith("--package-manager="):
            package_manager = arg.split("=", 1)[1]
        else:
            unknown_args.append(arg)
        index += 1

    if unknown_args:
        error_console.print(
            "[red]Error:[/red] Unknown uninstall argument(s): " + ", ".join(unknown_args)
        )
        raise typer.Exit(2)

    return yes, dry_run, remove_data, package_manager


def _fail(exc: Exception) -> None:
    error_console.print(f"[red]Error:[/red] {exc}")
    raise typer.Exit(1) from exc
