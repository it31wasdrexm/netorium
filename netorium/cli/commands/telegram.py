from __future__ import annotations

from pathlib import Path
from typing import Annotated

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
    help="Manage and test Telegram bot integration.",
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


@telegram_app.command("start")
def start_bot(
    token: Annotated[
        str | None,
        typer.Option("--token", "-t", help="Telegram Bot API token. Overrides configuration."),
    ] = None,
    chat_id: Annotated[
        str | None,
        typer.Option("--chat-id", "-c", help="Telegram Chat ID of the admin. Overrides configuration."),
    ] = None,
) -> None:
    """Start the Telegram bot in the foreground to listen for commands and report traffic anomalies."""
    try:
        settings = load_settings()
        bot_token = token or settings.telegram.bot_token
        admin_chat_id = chat_id or settings.telegram.chat_id
        db_path = Path(settings.app.database_path).expanduser()

        if bot_token == "CHANGE_ME" or not bot_token.strip():
            raise ConfigError("Telegram bot token is not configured. Use --token option or update config.toml.")
        if admin_chat_id == "CHANGE_ME" or not admin_chat_id.strip():
            raise ConfigError("Telegram chat_id is not configured. Use --chat-id option or update config.toml.")

        from netorium.services.telegram_bot import start_telegram_bot
        start_telegram_bot(token=bot_token, chat_id=admin_chat_id, db_path=db_path)
    except (ConfigError, TelegramError) as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc


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

