from typing import Any

import pytest
import requests

from netorium.services.update_checker import (
    PLACEHOLDER_REPO,
    UpdateCheckError,
    UpdateConfig,
    check_for_update,
    compare_versions,
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


def test_compare_versions_handles_v_prefix_and_padding() -> None:
    assert compare_versions("v0.2.0", "0.1.9") == 1
    assert compare_versions("0.1", "0.1.0") == 0
    assert compare_versions("0.1.0", "0.2.0") == -1


def test_github_update_check_reports_new_release() -> None:
    client = FakeClient(
        FakeResponse(
            200,
            {
                "tag_name": "v0.2.0",
                "html_url": "https://github.com/example/netorium/releases/tag/v0.2.0",
            },
        )
    )

    info = check_for_update(
        UpdateConfig(source="github", repo="example/netorium"),
        current_version="0.1.0",
        client=client,
    )

    assert info.is_update_available is True
    assert info.latest_version == "0.2.0"
    assert info.release_url == "https://github.com/example/netorium/releases/tag/v0.2.0"
    assert info.install_command == "pipx upgrade netorium-cli"
    assert client.urls == ["https://api.github.com/repos/example/netorium/releases/latest"]


def test_github_update_check_reports_up_to_date_release() -> None:
    client = FakeClient(FakeResponse(200, {"tag_name": "v0.1.0"}))

    info = check_for_update(
        UpdateConfig(source="github", repo="example/netorium"),
        current_version="0.1.0",
        client=client,
    )

    assert info.is_update_available is False
    assert info.release_url == "https://github.com/example/netorium/releases/latest"


def test_github_update_check_rejects_placeholder_repo() -> None:
    with pytest.raises(UpdateCheckError, match="repository is not configured"):
        check_for_update(
            UpdateConfig(source="github", repo=PLACEHOLDER_REPO),
            current_version="0.1.0",
            client=FakeClient(FakeResponse(200, {"tag_name": "v0.2.0"})),
        )


def test_update_check_handles_network_failure() -> None:
    client = FakeClient(error=requests.RequestException("connection failed"))

    with pytest.raises(UpdateCheckError, match="connection failed"):
        check_for_update(
            UpdateConfig(source="github", repo="example/netorium"),
            current_version="0.1.0",
            client=client,
        )


def test_update_check_handles_http_error() -> None:
    client = FakeClient(FakeResponse(500, {}))

    with pytest.raises(UpdateCheckError, match="HTTP 500"):
        check_for_update(
            UpdateConfig(source="github", repo="example/netorium"),
            current_version="0.1.0",
            client=client,
        )


def test_pypi_update_check_reports_new_release() -> None:
    client = FakeClient(FakeResponse(200, {"info": {"version": "0.3.0"}}))

    info = check_for_update(
        UpdateConfig(source="pypi", repo="", package_name="netorium-cli"),
        current_version="0.2.0",
        client=client,
    )

    assert info.is_update_available is True
    assert info.release_url == "https://pypi.org/project/netorium-cli/0.3.0/"
    assert client.urls == ["https://pypi.org/pypi/netorium-cli/json"]
