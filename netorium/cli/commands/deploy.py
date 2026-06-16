from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from netorium.core.database import DatabaseError
from netorium.core.settings import ConfigError, load_settings
from netorium.services.deploy import (
    DEFAULT_TOKEN_PLACEHOLDER,
    DeployError,
    build_deploy_instructions,
    create_deploy_token,
    write_agent_script,
)
from netorium.services.update_checker import DEFAULT_GITHUB_REPO

deploy_app = typer.Typer(
    help="Generate office deployment commands and agent install scripts.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
token_app = typer.Typer(
    help="Create deployment enrollment tokens.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
script_app = typer.Typer(
    help="Write agent deployment scripts.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()
error_console = Console(stderr=True)


@deploy_app.command("instructions")
def instructions(
    repo: Annotated[
        str,
        typer.Option("--repo", help="GitHub owner/repo used for public install-agent scripts."),
    ] = DEFAULT_GITHUB_REPO,
) -> None:
    """Print copy-paste deployment commands for the local controller."""
    try:
        deploy_instructions = build_deploy_instructions(_database_path(), repo=repo)
    except (ConfigError, DatabaseError, DeployError) as exc:
        _fail(exc)

    table = Table(title="Netorium Deployment")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Controller", deploy_instructions.controller_url)
    table.add_row("Create token", deploy_instructions.token_create_command)
    console.print(table)
    console.print(Panel.fit(deploy_instructions.windows_install, title="Windows install"))
    console.print(Panel.fit(deploy_instructions.linux_install, title="Linux install"))


@token_app.command("create")
def token_create(
    zone: Annotated[str, typer.Option("--zone", help="Zone assigned during enrollment.")],
    ttl: Annotated[
        str,
        typer.Option("--ttl", help="Token lifetime, for example 30m, 24h, or 7d."),
    ] = "24h",
    repo: Annotated[
        str,
        typer.Option("--repo", help="GitHub owner/repo used for public install-agent scripts."),
    ] = DEFAULT_GITHUB_REPO,
) -> None:
    """Create an enrollment token and print install commands."""
    try:
        result = create_deploy_token(_database_path(), zone=zone, ttl=ttl, repo=repo)
    except (ConfigError, DatabaseError, DeployError) as exc:
        _fail(exc)

    console.print("Enrollment token created.")
    table = Table(title="Deployment Token")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Token ID", result.token.token_id)
    table.add_row("Zone", result.token.zone)
    table.add_row("Expires", result.token.expires_at)
    table.add_row("Controller", result.controller_url)
    console.print(table)
    console.print("Token (shown once):")
    console.print(result.token.token)
    console.print(Panel.fit(result.windows_install, title="Windows install"))
    console.print(Panel.fit(result.linux_install, title="Linux install"))


@script_app.command("windows")
def script_windows(
    output: Annotated[Path, typer.Option("--output", help="Path for the generated script.")],
    token: Annotated[
        str,
        typer.Option("--token", help="Enrollment token to embed in the script."),
    ] = DEFAULT_TOKEN_PLACEHOLDER,
    repo: Annotated[
        str,
        typer.Option("--repo", help="GitHub owner/repo used for public install-agent scripts."),
    ] = DEFAULT_GITHUB_REPO,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite the output file if it already exists."),
    ] = False,
) -> None:
    """Write a Windows PowerShell agent deployment script."""
    _write_script("windows", output=output, token=token, repo=repo, force=force)


@script_app.command("linux")
def script_linux(
    output: Annotated[Path, typer.Option("--output", help="Path for the generated script.")],
    token: Annotated[
        str,
        typer.Option("--token", help="Enrollment token to embed in the script."),
    ] = DEFAULT_TOKEN_PLACEHOLDER,
    repo: Annotated[
        str,
        typer.Option("--repo", help="GitHub owner/repo used for public install-agent scripts."),
    ] = DEFAULT_GITHUB_REPO,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite the output file if it already exists."),
    ] = False,
) -> None:
    """Write a Linux shell agent deployment script."""
    _write_script("linux", output=output, token=token, repo=repo, force=force)


deploy_app.add_typer(token_app, name="token")
deploy_app.add_typer(script_app, name="script")


def _write_script(
    platform_name: str,
    *,
    output: Path,
    token: str,
    repo: str,
    force: bool,
) -> None:
    try:
        instructions = build_deploy_instructions(_database_path(), repo=repo, token=token)
        path = write_agent_script(
            output,
            platform_name=platform_name,
            controller_url=instructions.controller_url,
            token=token,
            repo=repo,
            force=force,
        )
    except (ConfigError, DatabaseError, DeployError) as exc:
        _fail(exc)

    console.print(f"Wrote {platform_name} deploy script: {path}")


def _database_path() -> Path:
    settings = load_settings()
    return Path(settings.app.database_path).expanduser()


def _fail(exc: Exception) -> None:
    error_console.print(f"[red]Error:[/red] {exc}")
    raise typer.Exit(1) from exc
