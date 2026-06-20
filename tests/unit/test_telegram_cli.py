from pathlib import Path

import pytest
from typer.testing import CliRunner

from netorium.cli.app import app
from netorium.cli.commands import telegram as telegram_command
from netorium.core.settings import CONFIG_TEMPLATE
from netorium.services.telegram_client import TelegramError, TelegramTestResult
from tests.unit.path_helpers import isolated_config_dir, isolated_user_env

runner = CliRunner()


def test_telegram_test_renders_success_without_exposing_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _write_config(tmp_path)

    monkeypatch.setattr(
        telegram_command,
        "test_telegram_connection",
        lambda config: TelegramTestResult(
            bot_username="netorium_bot",
            message="Bot token is valid",
        ),
    )

    result = runner.invoke(app, ["telegram", "test"], env=env)

    assert result.exit_code == 0
    assert "Telegram Test" in result.output
    assert "Telegram connection OK" in result.output
    assert "netorium_bot" in result.output
    assert "secret-token" not in result.output
    assert "123456789" not in result.output


def test_telegram_test_reports_placeholder_config(tmp_path: Path) -> None:
    config_dir = isolated_config_dir(tmp_path)
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text(CONFIG_TEMPLATE, encoding="utf-8")

    result = runner.invoke(app, ["telegram", "test"], env=isolated_user_env(tmp_path))

    assert result.exit_code == 1
    assert "Telegram settings are not configured" in result.output
    assert "CHANGE_ME" not in result.output


def test_telegram_test_reports_service_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _write_config(tmp_path)

    def fail(config: telegram_command.TelegramConfig) -> TelegramTestResult:
        raise TelegramError("Telegram request failed. Check network access and bot settings.")

    monkeypatch.setattr(telegram_command, "test_telegram_connection", fail)

    result = runner.invoke(app, ["telegram", "test"], env=env)

    assert result.exit_code == 1
    assert "Telegram request failed" in result.output


def test_telegram_start_bot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _write_config(tmp_path)
    
    called_args = {}
    def mock_start(token: str, chat_id: str, db_path: Path) -> None:
        called_args["token"] = token
        called_args["chat_id"] = chat_id
        called_args["db_path"] = db_path

    import netorium.services.telegram_bot
    monkeypatch.setattr(netorium.services.telegram_bot, "start_telegram_bot", mock_start)

    result = runner.invoke(app, ["telegram", "start"], env=env)
    
    assert result.exit_code == 0
    assert called_args["token"] == "123456:secret-token"
    assert called_args["chat_id"] == "123456789"
    assert "netorium.db" in str(called_args["db_path"])


def test_telegram_start_bot_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _write_config(tmp_path)
    
    called_args = {}
    def mock_start(token: str, chat_id: str, db_path: Path) -> None:
        called_args["token"] = token
        called_args["chat_id"] = chat_id
        called_args["db_path"] = db_path

    import netorium.services.telegram_bot
    monkeypatch.setattr(netorium.services.telegram_bot, "start_telegram_bot", mock_start)

    result = runner.invoke(
        app,
        ["telegram", "start", "--token", "999:new-token", "--chat-id", "98765"],
        env=env,
    )
    
    assert result.exit_code == 0
    assert called_args["token"] == "999:new-token"
    assert called_args["chat_id"] == "98765"



def _write_config(tmp_path: Path) -> dict[str, str]:
    database_path = tmp_path / "state" / "netorium.db"
    config_dir = isolated_config_dir(tmp_path)
    config_dir.mkdir(parents=True)
    config_text = CONFIG_TEMPLATE.replace(
        'database_path = "~/.local/share/netorium/netorium.db"',
        f'database_path = "{database_path.as_posix()}"',
    )
    config_text = config_text.replace('bot_token = "CHANGE_ME"', 'bot_token = "123456:secret-token"')
    config_text = config_text.replace('chat_id = "CHANGE_ME"', 'chat_id = "123456789"')
    (config_dir / "config.toml").write_text(config_text, encoding="utf-8")
    return isolated_user_env(tmp_path)

