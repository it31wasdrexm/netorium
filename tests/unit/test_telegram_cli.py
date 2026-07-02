from pathlib import Path

import pytest
import tomllib
from typer.testing import CliRunner

from netorium.cli.app import app
from netorium.core.settings import CONFIG_TEMPLATE
from tests.unit.path_helpers import isolated_config_dir, isolated_config_path, isolated_user_env

runner = CliRunner()


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


def test_telegram_start_bot_overrides_and_saves(
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
    assert "Telegram settings saved successfully." in result.output

    # Verify that it is written to the config file
    config_file = isolated_config_path(tmp_path)
    config_data = tomllib.loads(config_file.read_text(encoding="utf-8"))
    assert config_data["telegram"]["bot_token"] == "999:new-token"
    assert config_data["telegram"]["chat_id"] == "98765"


def test_telegram_start_bot_prompts_and_saves(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_dir = isolated_config_dir(tmp_path)
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text(CONFIG_TEMPLATE, encoding="utf-8")
    env = isolated_user_env(tmp_path)

    called_args = {}
    def mock_start(token: str, chat_id: str, db_path: Path) -> None:
        called_args["token"] = token
        called_args["chat_id"] = chat_id
        called_args["db_path"] = db_path

    import netorium.services.telegram_bot
    monkeypatch.setattr(netorium.services.telegram_bot, "start_telegram_bot", mock_start)

    # Typer prompts for token and chat_id sequentially because they are "CHANGE_ME"
    result = runner.invoke(
        app,
        ["telegram", "start"],
        input="my-mocked-token\nmy-mocked-chat-id\n",
        env=env,
    )

    assert result.exit_code == 0
    assert "Enter Telegram Bot Token" in result.output
    assert "Enter Telegram Chat ID (User ID)" in result.output
    assert "Telegram settings saved successfully." in result.output
    assert called_args["token"] == "my-mocked-token"
    assert called_args["chat_id"] == "my-mocked-chat-id"

    # Verify that it is written to the config file
    config_file = isolated_config_path(tmp_path)
    config_data = tomllib.loads(config_file.read_text(encoding="utf-8"))
    assert config_data["telegram"]["bot_token"] == "my-mocked-token"
    assert config_data["telegram"]["chat_id"] == "my-mocked-chat-id"


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

