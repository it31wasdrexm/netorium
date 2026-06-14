from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from netorium.core.settings import ConfigError, load_settings
from netorium.services.prtg_client import PrtgConfig, PrtgError, PrtgTestResult, test_prtg_connection

prtg_app = typer.Typer(
    help="Test PRTG API integration.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()
error_console = Console(stderr=True)


@prtg_app.command("test")
def test_connection() -> None:
    """Test the configured PRTG API connection."""
    try:
        result = test_prtg_connection(_load_prtg_config())
    except (ConfigError, PrtgError) as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    _render_result(result)


def _load_prtg_config() -> PrtgConfig:
    settings = load_settings()
    return PrtgConfig(
        base_url=settings.prtg.base_url,
        username=settings.prtg.username,
        passhash=settings.prtg.passhash,
    )


def _render_result(result: PrtgTestResult) -> None:
    table = Table(title="PRTG Test")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Base URL", result.base_url)
    table.add_row("Status", str(result.status_code))
    table.add_row("Message", result.message)
    console.print(table)
    console.print("PRTG connection OK")
