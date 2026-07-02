from __future__ import annotations

from dataclasses import dataclass
import platform
from typing import Any, Literal, Protocol, cast

import requests

from netorium.core.metadata import get_version

DEFAULT_PACKAGE_NAME = "netorium-cli"
DEFAULT_GITHUB_REPO = "it31wasdrexm/netorium"
DEFAULT_DOCKER_IMAGE = "ghcr.io/it31wasdrexm/netorium:latest"
DEFAULT_TIMEOUT_SECONDS = 10.0
PLACEHOLDER_REPO = "OWNER/REPO"

UpdateSource = Literal["github", "pypi"]


class HttpResponse(Protocol):
    status_code: int
    text: str

    def json(self) -> Any:
        pass


class HttpClient(Protocol):
    def get(self, url: str, timeout: float) -> HttpResponse:
        pass


class UpdateCheckError(RuntimeError):
    pass


@dataclass(frozen=True)
class UpdateConfig:
    source: UpdateSource
    repo: str
    package_name: str = DEFAULT_PACKAGE_NAME


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    release_url: str
    source: UpdateSource
    install_command: str

    @property
    def is_update_available(self) -> bool:
        return compare_versions(self.latest_version, self.current_version) > 0


@dataclass(frozen=True)
class DownloadInstructions:
    release_url: str
    linux_macos_installer: str
    windows_installer: str
    pypi_install: str
    docker_run: str
    docker_build: str
    standalone_assets: tuple[str, ...]


@dataclass(frozen=True)
class PlatformInstallInstructions:
    platform_name: str
    install_command: str
    standalone_command: str
    standalone_asset: str | None


def check_for_update(
    config: UpdateConfig,
    current_version: str | None = None,
    client: HttpClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> UpdateInfo:
    active_client: HttpClient = client or cast(HttpClient, requests.Session())
    active_current_version = current_version or get_version()

    if config.source == "github":
        return _check_github(config, active_current_version, active_client, timeout)
    if config.source == "pypi":
        return _check_pypi(config, active_current_version, active_client, timeout)

    raise UpdateCheckError(f"Unsupported update source: {config.source}")


def compare_versions(left: str, right: str) -> int:
    left_parts = _version_parts(left)
    right_parts = _version_parts(right)
    max_length = max(len(left_parts), len(right_parts))
    padded_left = left_parts + (0,) * (max_length - len(left_parts))
    padded_right = right_parts + (0,) * (max_length - len(right_parts))

    if padded_left > padded_right:
        return 1
    if padded_left < padded_right:
        return -1
    return 0


def build_update_config(source: str, repo: str, package_name: str = DEFAULT_PACKAGE_NAME) -> UpdateConfig:
    normalized_source = source.lower()
    if normalized_source not in ("github", "pypi"):
        raise UpdateCheckError(f"Unsupported update source: {source}")
    normalized_repo = repo.strip()
    if normalized_source == "github" and (
        not normalized_repo or normalized_repo == PLACEHOLDER_REPO
    ):
        normalized_repo = DEFAULT_GITHUB_REPO
    return UpdateConfig(
        source=cast(UpdateSource, normalized_source),
        repo=normalized_repo,
        package_name=package_name,
    )


def build_download_instructions(
    repo: str = DEFAULT_GITHUB_REPO,
    package_name: str = DEFAULT_PACKAGE_NAME,
    docker_image: str = DEFAULT_DOCKER_IMAGE,
) -> DownloadInstructions:
    active_repo = repo.strip()
    if not active_repo or active_repo == PLACEHOLDER_REPO:
        active_repo = DEFAULT_GITHUB_REPO

    raw_base_url = f"https://raw.githubusercontent.com/{active_repo}/main"
    release_url = f"https://github.com/{active_repo}/releases/latest"

    return DownloadInstructions(
        release_url=release_url,
        linux_macos_installer=f"curl -fsSL {raw_base_url}/get.sh | bash",
        windows_installer=f"irm {raw_base_url}/get.ps1 | iex",
        pypi_install=f"pipx install --force {package_name}",
        docker_run=f"docker run --rm -it {docker_image}",
        docker_build="docker build -t netorium-cli .",
        standalone_assets=(
            "netorium-windows-x64.exe",
            "netorium-linux-x64",
            "netorium-macos-x64",
            "netorium-macos-arm64",
        ),
    )


def build_platform_install_instructions(
    instructions: DownloadInstructions,
    system_name: str | None = None,
    machine: str | None = None,
) -> PlatformInstallInstructions:
    normalized_system = (system_name or platform.system()).lower()
    normalized_machine = (machine or platform.machine()).lower()

    if normalized_system.startswith("win"):
        asset = instructions.standalone_assets[0]
        return PlatformInstallInstructions(
            platform_name="Windows",
            install_command=instructions.windows_installer,
            standalone_command=(
                "Invoke-WebRequest -Uri "
                f"{_release_asset_url(instructions.release_url, asset)} "
                f"-OutFile .\\{asset}; .\\{asset} version"
            ),
            standalone_asset=asset,
        )

    if normalized_system == "linux":
        asset = instructions.standalone_assets[1]
        return PlatformInstallInstructions(
            platform_name="Linux",
            install_command=instructions.linux_macos_installer,
            standalone_command=(
                "mkdir -p ~/.local/bin && "
                "curl -fL -o ~/.local/bin/netorium "
                f"{_release_asset_url(instructions.release_url, asset)} && "
                "chmod +x ~/.local/bin/netorium && netorium version"
            ),
            standalone_asset=asset,
        )

    if normalized_system == "darwin":
        asset = instructions.standalone_assets[3] if "arm" in normalized_machine else instructions.standalone_assets[2]
        return PlatformInstallInstructions(
            platform_name="macOS",
            install_command=instructions.linux_macos_installer,
            standalone_command=(
                "mkdir -p ~/.local/bin && "
                "curl -fL -o ~/.local/bin/netorium "
                f"{_release_asset_url(instructions.release_url, asset)} && "
                "chmod +x ~/.local/bin/netorium && netorium version"
            ),
            standalone_asset=asset,
        )

    return PlatformInstallInstructions(
        platform_name="this OS",
        install_command=instructions.pypi_install,
        standalone_command=f"Open {instructions.release_url} and download the matching asset.",
        standalone_asset=None,
    )


def _check_github(
    config: UpdateConfig,
    current_version: str,
    client: HttpClient,
    timeout: float,
) -> UpdateInfo:
    if not config.repo or config.repo == PLACEHOLDER_REPO:
        raise UpdateCheckError("GitHub update repository is not configured in [updates].repo.")

    url = f"https://api.github.com/repos/{config.repo}/releases/latest"
    payload = _get_json(client, url, timeout, "GitHub")
    latest_version = _read_required_string(payload, "tag_name", "GitHub release tag")
    release_url = _read_optional_string(payload, "html_url") or (
        f"https://github.com/{config.repo}/releases/latest"
    )

    return UpdateInfo(
        current_version=current_version,
        latest_version=_strip_version_prefix(latest_version),
        release_url=release_url,
        source="github",
        install_command=f"pipx upgrade {config.package_name}",
    )


def _check_pypi(
    config: UpdateConfig,
    current_version: str,
    client: HttpClient,
    timeout: float,
) -> UpdateInfo:
    url = f"https://pypi.org/pypi/{config.package_name}/json"
    payload = _get_json(client, url, timeout, "PyPI")
    info = payload.get("info")
    if not isinstance(info, dict):
        raise UpdateCheckError("PyPI response does not contain package info.")

    latest_version = _read_required_string(info, "version", "PyPI package version")
    release_url = f"https://pypi.org/project/{config.package_name}/{latest_version}/"

    return UpdateInfo(
        current_version=current_version,
        latest_version=_strip_version_prefix(latest_version),
        release_url=release_url,
        source="pypi",
        install_command=f"pipx upgrade {config.package_name}",
    )


def _get_json(client: HttpClient, url: str, timeout: float, source_name: str) -> dict[str, Any]:
    try:
        response = client.get(url, timeout=timeout)
    except requests.RequestException as exc:
        raise UpdateCheckError(f"{source_name} update check failed: {exc}") from exc

    if response.status_code >= 400:
        raise UpdateCheckError(f"{source_name} update check failed with HTTP {response.status_code}.")

    payload = response.json()
    if not isinstance(payload, dict):
        raise UpdateCheckError(f"{source_name} update response is not a JSON object.")
    return payload


def _read_required_string(payload: dict[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise UpdateCheckError(f"{label} is missing from update response.")
    return value


def _read_optional_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _release_asset_url(release_url: str, asset: str) -> str:
    return f"{release_url.rstrip('/')}/download/{asset}"


def _strip_version_prefix(version: str) -> str:
    stripped = version.strip()
    if stripped.startswith(("v", "V")):
        return stripped[1:]
    return stripped


def _version_parts(version: str) -> tuple[int, ...]:
    normalized = _strip_version_prefix(version)
    parts: list[int] = []
    for raw_part in normalized.replace("-", ".").split("."):
        digits = ""
        for char in raw_part:
            if not char.isdigit():
                break
            digits += char
        parts.append(int(digits or "0"))
    return tuple(parts)
