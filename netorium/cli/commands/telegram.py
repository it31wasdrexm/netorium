from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from netorium.core.settings import ConfigError, load_settings
from netorium.services.telegram_client import (
    TelegramConfig,
    TelegramError,
    TelegramTestResult,
    test_telegram_connection,
)

telegram_app = typer.Typer(
    help="Test Telegram bot integration.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()
error_console = Console(stderr=True)


@telegram_app.command("test")
def test_connection() -> None:
    """Test the configured Telegram bot token."""
    try:
        result = test_telegram_connection(_load_telegram_config())
    except (ConfigError, TelegramError) as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    _render_result(result)


def _load_telegram_config() -> TelegramConfig:
    settings = load_settings()
    return TelegramConfig(
        bot_token=settings.telegram.bot_token,
        chat_id=settings.telegram.chat_id,
    )


def _render_result(result: TelegramTestResult) -> None:
    table = Table(title="Telegram Test")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Bot username", result.bot_username)
    table.add_row("Message", result.message)
    console.print(table)
    console.print("Telegram connection OK")
