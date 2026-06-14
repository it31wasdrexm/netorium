from typing import Annotated

import typer
from rich.console import Console
from rich.syntax import Syntax

from netorium.core.settings import (
    ConfigError,
    default_config_path,
    init_config,
    masked_config_text,
    validate_settings,
)

config_app = typer.Typer(
    help="Manage Netorium configuration.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()
error_console = Console(stderr=True)


@config_app.command("path")
def show_path() -> None:
    """Show the active configuration file path."""
    typer.echo(str(default_config_path()))


@config_app.command("init")
def init(
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite an existing config file."),
    ] = False,
) -> None:
    """Create the default configuration file."""
    try:
        path = init_config(force=force)
    except ConfigError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    console.print(f"Created config: {path}")


@config_app.command("show")
def show() -> None:
    """Show the current configuration with secrets masked."""
    try:
        config_text = masked_config_text()
    except ConfigError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    console.print(Syntax(config_text, "toml", word_wrap=True))


@config_app.command("validate")
def validate() -> None:
    """Validate the current configuration file."""
    try:
        validate_settings()
    except ConfigError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    console.print("Config is valid")
