from pathlib import Path
from typing import Any

import pytest

from netorium.core.settings import CONFIG_TEMPLATE
from netorium.services.update_notifications import get_startup_update_notice


class FakeResponse:
    status_code = 200
    text = ""

    def json(self) -> dict[str, Any]:
        return {
            "tag_name": "v0.2.0",
            "html_url": "https://github.com/example/netorium/releases/tag/v0.2.0",
        }


class FakeClient:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get(self, url: str, timeout: float) -> FakeResponse:
        self.urls.append(url)
        return FakeResponse()


def test_startup_notice_skips_missing_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    client = FakeClient()

    notice = get_startup_update_notice(
        client=client,
        current_version="0.1.0",
        system_name="Linux",
    )

    assert notice is None
    assert client.urls == []


def test_startup_notice_skips_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "config" / "netorium"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text(
        CONFIG_TEMPLATE.replace("check_on_start = true", "check_on_start = false"),
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    client = FakeClient()

    notice = get_startup_update_notice(
        client=client,
        current_version="0.1.0",
        system_name="Linux",
    )

    assert notice is None
    assert client.urls == []


def test_startup_notice_returns_platform_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "config" / "netorium"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text(CONFIG_TEMPLATE, encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    client = FakeClient()

    notice = get_startup_update_notice(
        client=client,
        current_version="0.1.0",
        system_name="Windows",
    )

    assert notice is not None
    assert notice.info.latest_version == "0.2.0"
    assert notice.platform.platform_name == "Windows"
    assert "install.ps1" in notice.platform.install_command
    assert "netorium-windows-x64.exe" in notice.platform.standalone_command
    assert client.urls == ["https://api.github.com/repos/it31wasdrexm/netorium/releases/latest"]
