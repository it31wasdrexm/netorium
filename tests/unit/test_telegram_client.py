from typing import Any

import pytest
import requests

from netorium.services.telegram_client import (
    TelegramConfig,
    TelegramError,
    test_telegram_connection as run_telegram_connection_test,
)


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self.payload = payload
        self.text = ""

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeClient:
    def __init__(
        self,
        response: FakeResponse | None = None,
        error: requests.RequestException | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.urls: list[str] = []

    def get(self, url: str, timeout: float) -> FakeResponse:
        self.urls.append(url)
        if self.error is not None:
            raise self.error
        if self.response is None:
            raise AssertionError("FakeClient response was not configured")
        return self.response


def test_telegram_connection_calls_get_me() -> None:
    client = FakeClient(FakeResponse(200, {"ok": True, "result": {"username": "netorium_bot"}}))

    result = run_telegram_connection_test(
        TelegramConfig(bot_token="123456:secret-token", chat_id="123456789"),
        client=client,
        timeout=3.0,
    )

    assert result.bot_username == "netorium_bot"
    assert result.message == "Bot token is valid"
    assert client.urls == ["https://api.telegram.org/bot123456:secret-token/getMe"]


def test_telegram_connection_rejects_placeholder_config_without_network_call() -> None:
    client = FakeClient(FakeResponse(200, {"ok": True, "result": {"username": "netorium_bot"}}))

    with pytest.raises(TelegramError, match="not configured"):
        run_telegram_connection_test(
            TelegramConfig(bot_token="CHANGE_ME", chat_id="CHANGE_ME"),
            client=client,
        )

    assert client.urls == []


def test_telegram_connection_handles_http_error() -> None:
    with pytest.raises(TelegramError, match="HTTP 401"):
        run_telegram_connection_test(
            TelegramConfig(bot_token="123456:secret-token", chat_id="123456789"),
            client=FakeClient(FakeResponse(401, {"ok": False})),
        )


def test_telegram_connection_handles_api_error() -> None:
    with pytest.raises(TelegramError, match="Unauthorized"):
        run_telegram_connection_test(
            TelegramConfig(bot_token="123456:secret-token", chat_id="123456789"),
            client=FakeClient(FakeResponse(200, {"ok": False, "description": "Unauthorized"})),
        )


def test_telegram_connection_handles_network_error() -> None:
    with pytest.raises(TelegramError, match="Telegram request failed"):
        run_telegram_connection_test(
            TelegramConfig(bot_token="123456:secret-token", chat_id="123456789"),
            client=FakeClient(error=requests.RequestException("boom")),
        )
