from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from netorium.core.settings import ConfigError, load_settings
from netorium.services.ad_client import (
    ActiveDirectoryConfig,
    ActiveDirectoryError,
    ActiveDirectoryTestResult,
    test_active_directory_connection,
)

ad_app = typer.Typer(
    help="Test Active Directory integration.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()
error_console = Console(stderr=True)


@ad_app.command("test")
def test_connection() -> None:
    """Test the configured Active Directory bind."""
    try:
        result = test_active_directory_connection(_load_ad_config())
    except (ConfigError, ActiveDirectoryError) as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    _render_result(result)


def _load_ad_config() -> ActiveDirectoryConfig:
    settings = load_settings()
    return ActiveDirectoryConfig(
        server=settings.active_directory.server,
        domain=settings.active_directory.domain,
        bind_user=settings.active_directory.bind_user,
        bind_password=settings.active_directory.bind_password,
    )


def _render_result(result: ActiveDirectoryTestResult) -> None:
    table = Table(title="Active Directory Test")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Server", result.server)
    table.add_row("Domain", result.domain)
    table.add_row("Bind user", result.bind_user)
    table.add_row("Message", result.message)
    console.print(table)
    console.print("Active Directory connection OK")
