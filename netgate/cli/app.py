from typing import Annotated

import typer
from rich.console import Console

from netgate.core.metadata import APP_NAME, get_version

console = Console()

app = typer.Typer(
    name="netgate",
    help="NetGate CLI for building-level network access control.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


@app.command()
def version() -> None:
    """Show the installed NetGate CLI version."""
    console.print(f"{APP_NAME} {get_version()}")


@app.command()
def doctor(
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show additional environment details."),
    ] = False,
) -> None:
    """Run basic local environment checks."""
    console.print(f"{APP_NAME} basic checks: OK")
    if verbose:
        console.print("Detailed checks will be added in later MVP tasks.")
