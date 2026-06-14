import typer
from rich.console import Console
from rich.markdown import Markdown

from netorium.core.docs import DocumentationError, load_doc_page

docs_app = typer.Typer(
    help="Read built-in Netorium documentation.",
    invoke_without_command=True,
    no_args_is_help=False,
    rich_markup_mode="rich",
)

console = Console()
error_console = Console(stderr=True)


@docs_app.callback()
def docs(ctx: typer.Context) -> None:
    """Show built-in documentation."""
    if ctx.invoked_subcommand is None:
        render_doc_page("index")


@docs_app.command("commands")
def commands() -> None:
    """Show command reference."""
    render_doc_page("commands")


@docs_app.command("examples")
def examples() -> None:
    """Show common usage examples."""
    render_doc_page("examples")


@docs_app.command("install")
def install() -> None:
    """Show installation instructions."""
    render_doc_page("install")


@docs_app.command("troubleshooting")
def troubleshooting() -> None:
    """Show troubleshooting notes."""
    render_doc_page("troubleshooting")


def render_doc_page(page: str) -> None:
    try:
        markdown = load_doc_page(page)
    except DocumentationError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    console.print(Markdown(markdown))
