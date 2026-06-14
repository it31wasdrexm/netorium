from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, cast

import requests

DEFAULT_TIMEOUT_SECONDS = 10.0
PLACEHOLDER_SECRET = "CHANGE_ME"


class HttpResponse(Protocol):
    status_code: int
    text: str

    def json(self) -> Any:
        pass


class HttpClient(Protocol):
    def get(self, url: str, timeout: float) -> HttpResponse:
        pass


class TelegramError(RuntimeError):
    pass


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    chat_id: str


@dataclass(frozen=True)
class TelegramTestResult:
    bot_username: str
    message: str


def test_telegram_connection(
    config: TelegramConfig,
    client: HttpClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> TelegramTestResult:
    bot_token = _normalize_required(config.bot_token, "Telegram bot_token")
    _normalize_required(config.chat_id, "Telegram chat_id")
    _reject_placeholder_config(config)

    active_client = client or cast(HttpClient, requests.Session())
    url = f"https://api.telegram.org/bot{bot_token}/getMe"

    try:
        response = active_client.get(url, timeout=timeout)
    except requests.RequestException as exc:
        raise TelegramError("Telegram request failed. Check network access and bot settings.") from exc

    if response.status_code >= 400:
        raise TelegramError(f"Telegram test failed with HTTP {response.status_code}.")

    payload = response.json()
    if not isinstance(payload, dict):
        raise TelegramError("Telegram response is not a JSON object.")

    if payload.get("ok") is not True:
        raise TelegramError(f"Telegram test failed: {_telegram_error_message(payload)}")

    result = payload.get("result")
    username = "unknown"
    if isinstance(result, dict):
        raw_username = result.get("username")
        if isinstance(raw_username, str) and raw_username.strip():
            username = raw_username.strip()

    return TelegramTestResult(bot_username=username, message="Bot token is valid")


def _normalize_required(value: str, label: str) -> str:
    clean_value = value.strip()
    if not clean_value:
        raise TelegramError(f"{label} cannot be empty.")
    return clean_value


def _reject_placeholder_config(config: TelegramConfig) -> None:
    if config.bot_token == PLACEHOLDER_SECRET or config.chat_id == PLACEHOLDER_SECRET:
        raise TelegramError("Telegram settings are not configured. Update telegram.bot_token and chat_id.")


def _telegram_error_message(payload: dict[str, Any]) -> str:
    description = payload.get("description")
    if isinstance(description, str) and description.strip():
        return description.strip()
    error_code = payload.get("error_code")
    if error_code is not None:
        return f"error code {error_code}"
    return "API returned ok=false"
