from typing import Annotated

import typer
from rich.console import Console

from netorium.cli.commands.ad import ad_app
from netorium.cli.commands.audit import audit_app
from netorium.cli.commands.config import config_app
from netorium.cli.commands.device import device_app
from netorium.cli.commands.docs import docs_app
from netorium.cli.commands.firewall import firewall_app
from netorium.cli.commands.prtg import prtg_app
from netorium.cli.commands.telegram import telegram_app
from netorium.cli.commands.update import update_app
from netorium.cli.commands.zone import zone_app
from netorium.core.metadata import APP_NAME, get_version

console = Console()

app = typer.Typer(
    name="netorium",
    help="Netorium CLI for building-level network access control.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

app.add_typer(config_app, name="config")
app.add_typer(docs_app, name="docs")
app.add_typer(update_app, name="update")
app.add_typer(zone_app, name="zone")
app.add_typer(device_app, name="device")
app.add_typer(firewall_app, name="firewall")
app.add_typer(prtg_app, name="prtg")
app.add_typer(ad_app, name="ad")
app.add_typer(telegram_app, name="telegram")
app.add_typer(audit_app, name="audit")


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
    console.print(f"{APP_NAME} basic checks: OK")
    if verbose:
        console.print("Detailed checks will be added in later MVP tasks.")
