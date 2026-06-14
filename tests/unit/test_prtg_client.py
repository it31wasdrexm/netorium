from typing import Mapping

import pytest
import requests

from netorium.services.prtg_client import (
    PrtgConfig,
    PrtgError,
    test_prtg_connection as run_prtg_connection_test,
)


class FakeResponse:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class FakeClient:
    def __init__(
        self,
        response: FakeResponse | None = None,
        error: requests.RequestException | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.calls: list[tuple[str, Mapping[str, str], float]] = []

    def get(self, url: str, params: Mapping[str, str], timeout: float) -> FakeResponse:
        self.calls.append((url, params, timeout))
        if self.error is not None:
            raise self.error
        if self.response is None:
            raise AssertionError("FakeClient response was not configured")
        return self.response


def test_prtg_connection_uses_status_endpoint_and_credentials() -> None:
    client = FakeClient(FakeResponse(200, "OK"))

    result = run_prtg_connection_test(
        PrtgConfig(
            base_url="https://prtg.local/",
            username="admin",
            passhash="secret-passhash",
        ),
        client=client,
        timeout=3.0,
    )

    assert result.base_url == "https://prtg.local"
    assert result.status_code == 200
    assert result.message == "OK"
    assert client.calls == [
        (
            "https://prtg.local/api/getstatus.htm",
            {"username": "admin", "passhash": "secret-passhash"},
            3.0,
        )
    ]


def test_prtg_connection_rejects_placeholder_config_without_network_call() -> None:
    client = FakeClient(FakeResponse(200, "OK"))

    with pytest.raises(PrtgError, match="not configured"):
        run_prtg_connection_test(
            PrtgConfig(
                base_url="https://prtg.example.local",
                username="admin",
                passhash="CHANGE_ME",
            ),
            client=client,
        )

    assert client.calls == []


def test_prtg_connection_rejects_invalid_base_url() -> None:
    with pytest.raises(PrtgError, match="http or https URL"):
        run_prtg_connection_test(
            PrtgConfig(base_url="prtg.local", username="admin", passhash="secret"),
            client=FakeClient(FakeResponse(200, "OK")),
        )


def test_prtg_connection_handles_http_error() -> None:
    with pytest.raises(PrtgError, match="HTTP 401"):
        run_prtg_connection_test(
            PrtgConfig(base_url="https://prtg.local", username="admin", passhash="secret"),
            client=FakeClient(FakeResponse(401, "Unauthorized")),
        )


def test_prtg_connection_handles_network_error() -> None:
    with pytest.raises(PrtgError, match="PRTG request failed"):
        run_prtg_connection_test(
            PrtgConfig(base_url="https://prtg.local", username="admin", passhash="secret"),
            client=FakeClient(error=requests.RequestException("boom")),
        )
