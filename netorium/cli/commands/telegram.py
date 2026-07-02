from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from netorium.core.settings import ConfigError, load_settings, default_config_path
from netorium.services.telegram_client import TelegramError

telegram_app = typer.Typer(
    help="Manage Telegram bot integration.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()
error_console = Console(stderr=True)


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

        bot_token = token
        if not bot_token:
            bot_token = settings.telegram.bot_token
            if bot_token == "CHANGE_ME" or not bot_token.strip():
                bot_token = typer.prompt("Enter Telegram Bot Token")

        admin_chat_id = chat_id
        if not admin_chat_id:
            admin_chat_id = settings.telegram.chat_id
            if admin_chat_id == "CHANGE_ME" or not admin_chat_id.strip():
                admin_chat_id = typer.prompt("Enter Telegram Chat ID (User ID)")

        bot_token = bot_token.strip()
        admin_chat_id = admin_chat_id.strip()
        if not bot_token:
            raise ConfigError("Telegram bot token cannot be empty.")
        if not admin_chat_id:
            raise ConfigError("Telegram chat_id cannot be empty.")

        # Save to configuration if they are different from what's currently in settings
        if (bot_token != settings.telegram.bot_token or 
            admin_chat_id != settings.telegram.chat_id):

            config_path = default_config_path()
            if not config_path.exists():
                from netorium.core.settings import init_config
                init_config(config_path)

            from netorium.core.settings import read_config_data, render_toml
            config_data = read_config_data(config_path)

            if "telegram" not in config_data:
                config_data["telegram"] = {}
            config_data["telegram"]["bot_token"] = bot_token
            config_data["telegram"]["chat_id"] = admin_chat_id

            config_path.write_text(render_toml(config_data), encoding="utf-8")
            console.print("[green]Telegram settings saved successfully.[/green]")

        db_path = Path(settings.app.database_path).expanduser()

        from netorium.services.telegram_bot import start_telegram_bot
        start_telegram_bot(token=bot_token, chat_id=admin_chat_id, db_path=db_path)
    except (ConfigError, TelegramError) as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

