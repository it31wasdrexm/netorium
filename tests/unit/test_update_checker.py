from typing import Any

import pytest
import requests

from netorium.services.update_checker import (
    DEFAULT_GITHUB_REPO,
    PLACEHOLDER_REPO,
    UpdateCheckError,
    UpdateConfig,
    build_download_instructions,
    build_platform_install_instructions,
    build_update_config,
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


def test_build_update_config_uses_real_default_for_placeholder_repo() -> None:
    config = build_update_config("github", PLACEHOLDER_REPO)

    assert config.repo == DEFAULT_GITHUB_REPO


def test_download_instructions_include_release_assets_and_docker() -> None:
    instructions = build_download_instructions(repo=PLACEHOLDER_REPO)

    assert instructions.release_url == "https://github.com/it31wasdrexm/netorium/releases/latest"
    assert "get.sh" in instructions.linux_macos_installer
    assert "get.ps1" in instructions.windows_installer
    assert "docker run --rm -it ghcr.io/it31wasdrexm/netorium:latest" == instructions.docker_run
    assert "netorium-windows-x64.exe" in instructions.standalone_assets


def test_platform_install_instructions_select_linux_commands() -> None:
    instructions = build_download_instructions(repo=PLACEHOLDER_REPO)

    platform_instructions = build_platform_install_instructions(
        instructions,
        system_name="Linux",
    )

    assert platform_instructions.platform_name == "Linux"
    assert platform_instructions.install_command == instructions.linux_macos_installer
    assert "netorium-linux-x64" in platform_instructions.standalone_command
    assert platform_instructions.standalone_asset == "netorium-linux-x64"


def test_platform_install_instructions_select_windows_commands() -> None:
    instructions = build_download_instructions(repo=PLACEHOLDER_REPO)

    platform_instructions = build_platform_install_instructions(
        instructions,
        system_name="Windows",
    )

    assert platform_instructions.platform_name == "Windows"
    assert platform_instructions.install_command == instructions.windows_installer
    assert "Invoke-WebRequest" in platform_instructions.standalone_command
    assert "netorium-windows-x64.exe" in platform_instructions.standalone_command


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
