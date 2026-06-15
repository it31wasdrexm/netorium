import typer
from rich.console import Console
from rich.table import Table

from netorium.core.metadata import get_version
from netorium.core.settings import ConfigError, load_settings
from netorium.services.update_checker import (
    DEFAULT_PACKAGE_NAME,
    DEFAULT_GITHUB_REPO,
    DownloadInstructions,
    UpdateCheckError,
    UpdateConfig,
    UpdateInfo,
    build_download_instructions,
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
    try:
        info = _run_update_check()
    except (ConfigError, UpdateCheckError) as exc:
        _render_update_error(exc)
        raise typer.Exit(1) from exc

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
    info, error = _try_update_check()

    table = Table(title="Netorium Update")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Current version", info.current_version if info else get_version())
    table.add_row("Latest version", info.latest_version if info else "unknown")
    table.add_row("Source", info.source if info else "github")
    table.add_row("Release", info.release_url if info else _download_instructions().release_url)
    table.add_row(
        "Recommended command",
        info.install_command if info else f"pipx install --force {DEFAULT_PACKAGE_NAME}",
    )
    table.add_row("pip command", f"python -m pip install --upgrade {DEFAULT_PACKAGE_NAME}")
    console.print(table)
    if error is not None:
        console.print(f"[yellow]Update check unavailable:[/] {error}")
    _render_download_instructions(_download_instructions())


@update_app.command("install")
def install() -> None:
    """Show safe manual update instructions."""
    info, error = _try_update_check()
    console.print("Automatic installation is not enabled yet.")
    if error is not None:
        console.print(f"[yellow]Update check unavailable:[/] {error}")
    elif info is not None and info.is_update_available:
        console.print(f"Latest version: {info.latest_version}")
        console.print(f"Release: {info.release_url}")

    console.print("Run one of these commands manually:")
    if info is not None:
        console.print(f"  {info.install_command}")
    console.print(f"  python -m pip install --upgrade {DEFAULT_PACKAGE_NAME}")
    _render_download_instructions(_download_instructions())


def _run_update_check() -> UpdateInfo:
    return check_for_update(_load_update_config())


def _try_update_check() -> tuple[UpdateInfo | None, str | None]:
    try:
        return _run_update_check(), None
    except (ConfigError, UpdateCheckError) as exc:
        return None, str(exc)


def _load_update_config() -> UpdateConfig:
    try:
        settings = load_settings()
    except ConfigError:
        return UpdateConfig(
            source="github",
            repo=DEFAULT_GITHUB_REPO,
            package_name=DEFAULT_PACKAGE_NAME,
        )

    return build_update_config(
        source=settings.updates.source,
        repo=settings.updates.repo,
        package_name=DEFAULT_PACKAGE_NAME,
    )


def _download_instructions() -> DownloadInstructions:
    try:
        settings = load_settings()
        repo = settings.updates.repo
    except ConfigError:
        repo = DEFAULT_GITHUB_REPO

    return build_download_instructions(repo=repo, package_name=DEFAULT_PACKAGE_NAME)


def _render_update_error(exc: Exception) -> None:
    typer.echo(f"Error: {exc}", err=True)
    instructions = _download_instructions()
    typer.echo("Download options:", err=True)
    typer.echo(f"  Release: {instructions.release_url}", err=True)
    typer.echo(f"  Linux/macOS: {instructions.linux_macos_installer}", err=True)
    typer.echo(f"  Windows PowerShell: {instructions.windows_installer}", err=True)


def _render_download_instructions(instructions: DownloadInstructions) -> None:
    table = Table(title="Download Options")
    table.add_column("Option")
    table.add_column("Command or file")
    table.add_row("GitHub releases", instructions.release_url)
    table.add_row("Linux/macOS installer", instructions.linux_macos_installer)
    table.add_row("Windows PowerShell", instructions.windows_installer)
    table.add_row("PyPI/pipx", instructions.pypi_install)
    table.add_row("Docker run", instructions.docker_run)
    table.add_row("Docker local build", instructions.docker_build)
    table.add_row("Standalone Windows", instructions.standalone_assets[0])
    table.add_row("Standalone Linux", instructions.standalone_assets[1])
    table.add_row(
        "Standalone macOS",
        f"{instructions.standalone_assets[2]} / {instructions.standalone_assets[3]}",
    )
    console.print(table)
    console.print("Copy-paste downloads:")
    console.print(f"  Release: {instructions.release_url}", soft_wrap=True)
    console.print(f"  Linux/macOS: {instructions.linux_macos_installer}", soft_wrap=True)
    console.print(f"  Windows PowerShell: {instructions.windows_installer}", soft_wrap=True)
    console.print(f"  Docker: {instructions.docker_run}", soft_wrap=True)
