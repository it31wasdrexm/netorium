import typer
from rich.console import Console
from rich.table import Table

from netorium.core.settings import ConfigError, load_settings
from netorium.services.update_checker import (
    DEFAULT_PACKAGE_NAME,
    PLACEHOLDER_REPO,
    UpdateCheckError,
    UpdateConfig,
    UpdateInfo,
    build_update_config,
    check_for_update,
)

update_app = typer.Typer(
    help="Check for Netorium CLI updates.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()


@update_app.command("check")
def check() -> None:
    """Check whether a newer Netorium CLI release is available."""
    info = _run_update_check()
    if info.is_update_available:
        console.print(f"Update available: {info.latest_version}")
        console.print(f"Current version: {info.current_version}")
        console.print(f"Run: {info.install_command}")
        console.print(f"Release: {info.release_url}")
        return

    console.print(f"Netorium CLI is up to date: {info.current_version}")


@update_app.command("show")
def show() -> None:
    """Show update details and manual install commands."""
    info = _run_update_check()

    table = Table(title="Netorium Update")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Current version", info.current_version)
    table.add_row("Latest version", info.latest_version)
    table.add_row("Source", info.source)
    table.add_row("Release", info.release_url)
    table.add_row("Recommended command", info.install_command)
    table.add_row("pip command", f"python -m pip install --upgrade {DEFAULT_PACKAGE_NAME}")
    console.print(table)


@update_app.command("install")
def install() -> None:
    """Show safe manual update instructions."""
    info = _run_update_check()
    console.print("Automatic installation is not enabled yet.")
    console.print("Run one of these commands manually:")
    console.print(f"  {info.install_command}")
    console.print(f"  python -m pip install --upgrade {DEFAULT_PACKAGE_NAME}")
    console.print(f"Release: {info.release_url}")


def _run_update_check() -> UpdateInfo:
    try:
        return check_for_update(_load_update_config())
    except (ConfigError, UpdateCheckError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc


def _load_update_config() -> UpdateConfig:
    try:
        settings = load_settings()
    except ConfigError:
        return UpdateConfig(source="github", repo=PLACEHOLDER_REPO, package_name=DEFAULT_PACKAGE_NAME)

    return build_update_config(
        source=settings.updates.source,
        repo=settings.updates.repo,
        package_name=DEFAULT_PACKAGE_NAME,
    )
