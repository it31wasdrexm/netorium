from pathlib import Path
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


@config_app.command("backup")
def backup(
    output_path: Annotated[
        Path,
        typer.Argument(help="Target backup file (e.g. netorium_backup.zip) or directory."),
    ],
) -> None:
    """Create a backup of the database and configuration."""
    from pathlib import Path
    import shutil
    import tempfile
    from netorium.core.settings import load_settings

    try:
        settings = load_settings()
        db_path = Path(settings.app.database_path).expanduser()
        cfg_path = default_config_path()

        if not db_path.exists():
            error_console.print(f"[yellow]Warning:[/yellow] Database file not found at {db_path}.")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            if db_path.exists():
                shutil.copy2(db_path, tmpdir_path / "netorium.db")
            if cfg_path.exists():
                shutil.copy2(cfg_path, tmpdir_path / "config.toml")

            archive_format = "zip"
            if output_path.is_dir() or str(output_path).endswith("/") or not output_path.suffix:
                output_path.mkdir(parents=True, exist_ok=True)
                target_base = str(output_path / "netorium_backup")
            else:
                suffix = ".zip"
                target_base = str(output_path)
                if target_base.lower().endswith(suffix):
                    target_base = target_base[:-len(suffix)]

            archive_path = shutil.make_archive(target_base, archive_format, tmpdir)
            console.print(f"Backup successfully created at: {archive_path}")
    except Exception as exc:
        error_console.print(f"[red]Error:[/red] Failed to create backup: {exc}")
        raise typer.Exit(1) from exc

