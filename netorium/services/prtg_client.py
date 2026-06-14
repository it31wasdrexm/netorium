from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, cast
from urllib.parse import urlparse

import requests

DEFAULT_TIMEOUT_SECONDS = 10.0
PLACEHOLDER_BASE_URL = "https://prtg.example.local"
PLACEHOLDER_SECRET = "CHANGE_ME"


class HttpResponse(Protocol):
    status_code: int
    text: str


class HttpClient(Protocol):
    def get(self, url: str, params: Mapping[str, str], timeout: float) -> HttpResponse:
        pass


class PrtgError(RuntimeError):
    pass


@dataclass(frozen=True)
class PrtgConfig:
    base_url: str
    username: str
    passhash: str


@dataclass(frozen=True)
class PrtgTestResult:
    base_url: str
    status_code: int
    message: str


def test_prtg_connection(
    config: PrtgConfig,
    client: HttpClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> PrtgTestResult:
    base_url = _normalize_base_url(config.base_url)
    username = _normalize_required(config.username, "PRTG username")
    passhash = _normalize_required(config.passhash, "PRTG passhash")
    _reject_placeholder_config(base_url, username, passhash)

    active_client = client or cast(HttpClient, requests.Session())
    endpoint = f"{base_url}/api/getstatus.htm"

    try:
        response = active_client.get(
            endpoint,
            params={"username": username, "passhash": passhash},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise PrtgError("PRTG request failed. Check network access and PRTG settings.") from exc

    if response.status_code >= 400:
        raise PrtgError(f"PRTG test failed with HTTP {response.status_code}.")

    return PrtgTestResult(
        base_url=base_url,
        status_code=response.status_code,
        message=_response_message(response),
    )


def _normalize_base_url(value: str) -> str:
    base_url = value.strip().rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise PrtgError("PRTG base_url must be an http or https URL.")
    return base_url


def _normalize_required(value: str, label: str) -> str:
    clean_value = value.strip()
    if not clean_value:
        raise PrtgError(f"{label} cannot be empty.")
    return clean_value


def _reject_placeholder_config(base_url: str, username: str, passhash: str) -> None:
    if base_url == PLACEHOLDER_BASE_URL or username == PLACEHOLDER_SECRET or passhash == PLACEHOLDER_SECRET:
        raise PrtgError(
            "PRTG settings are not configured. Update prtg.base_url, username, and passhash."
        )


def _response_message(response: HttpResponse) -> str:
    text = response.text.strip()
    if not text:
        return "HTTP response received"

    first_line = text.splitlines()[0].strip()
    if len(first_line) > 120:
        return f"{first_line[:117]}..."
    return first_line
