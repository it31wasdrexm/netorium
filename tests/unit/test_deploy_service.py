from __future__ import annotations

from pathlib import Path

import pytest

from netorium.services.controller import init_controller
from netorium.services.deploy import (
    DeployError,
    build_deploy_instructions,
    create_deploy_token,
    render_linux_agent_script,
    render_windows_agent_script,
    write_agent_script,
)


def test_build_deploy_instructions_uses_local_controller_url(tmp_path: Path) -> None:
    database_path = tmp_path / "netorium.db"
    init_controller(database_path, host="192.168.1.10", port=8765)

    instructions = build_deploy_instructions(database_path)

    assert instructions.controller_url == "http://192.168.1.10:8765"
    assert "netorium deploy token create --zone accounting --ttl 24h" == (
        instructions.token_create_command
    )
    assert "$Controller = 'http://192.168.1.10:8765'" in instructions.windows_install
    assert "CONTROLLER=http://192.168.1.10:8765" in instructions.linux_install
    assert "ENROLL_TOKEN" in instructions.windows_install
    assert "ENROLL_TOKEN" in instructions.linux_install


def test_create_deploy_token_prints_install_commands_with_real_token(tmp_path: Path) -> None:
    database_path = tmp_path / "netorium.db"
    init_controller(database_path, host="192.168.1.10", port=8765)

    result = create_deploy_token(database_path, zone="accounting", ttl="24h")

    assert result.token.token.startswith("ng_enroll_")
    assert result.controller_url == "http://192.168.1.10:8765"
    assert result.token.token in result.windows_install
    assert result.token.token in result.linux_install
    assert "netorium-agent enroll" in result.windows_install
    assert "netorium-agent enroll" in result.linux_install


def test_deploy_instructions_require_initialized_controller(tmp_path: Path) -> None:
    with pytest.raises(DeployError, match="controller init"):
        build_deploy_instructions(tmp_path / "netorium.db")


def test_render_agent_scripts_include_install_and_enroll_commands() -> None:
    windows = render_windows_agent_script(
        controller_url="http://192.168.1.10:8765",
        token="ng_enroll_test",
    )
    linux = render_linux_agent_script(
        controller_url="http://192.168.1.10:8765",
        token="ng_enroll_test",
    )

    assert "$ErrorActionPreference = \"Stop\"" in windows
    assert "install-agent.ps1" in windows
    assert "ng_enroll_test" in windows
    assert "#!/usr/bin/env bash" in linux
    assert "install-agent.sh" in linux
    assert "ng_enroll_test" in linux


def test_write_agent_script_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    output = tmp_path / "install-agent.ps1"
    output.write_text("existing", encoding="utf-8")

    with pytest.raises(DeployError, match="already exists"):
        write_agent_script(
            output,
            platform_name="windows",
            controller_url="http://192.168.1.10:8765",
        )

    path = write_agent_script(
        output,
        platform_name="windows",
        controller_url="http://192.168.1.10:8765",
        force=True,
    )

    assert path == output
    assert "netorium-agent enroll" in output.read_text(encoding="utf-8")
