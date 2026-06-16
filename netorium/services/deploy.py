from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path

from netorium.services.controller import (
    EnrollmentToken,
    ControllerError,
    create_enrollment_token,
    get_controller_status,
)
from netorium.services.update_checker import DEFAULT_GITHUB_REPO

DEFAULT_TOKEN_PLACEHOLDER = "ENROLL_TOKEN"


class DeployError(RuntimeError):
    pass


@dataclass(frozen=True)
class DeployInstructions:
    controller_url: str
    windows_install: str
    linux_install: str
    token_create_command: str


@dataclass(frozen=True)
class DeployTokenInstructions:
    token: EnrollmentToken
    controller_url: str
    windows_install: str
    linux_install: str


def build_deploy_instructions(
    database_path: str | Path,
    *,
    repo: str = DEFAULT_GITHUB_REPO,
    token: str = DEFAULT_TOKEN_PLACEHOLDER,
) -> DeployInstructions:
    controller_url = _controller_url(database_path)
    return DeployInstructions(
        controller_url=controller_url,
        windows_install=render_windows_install_commands(
            controller_url=controller_url,
            token=token,
            repo=repo,
        ),
        linux_install=render_linux_install_commands(
            controller_url=controller_url,
            token=token,
            repo=repo,
        ),
        token_create_command="netorium deploy token create --zone accounting --ttl 24h",
    )


def create_deploy_token(
    database_path: str | Path,
    *,
    zone: str,
    ttl: str = "24h",
    repo: str = DEFAULT_GITHUB_REPO,
) -> DeployTokenInstructions:
    controller_url = _controller_url(database_path)
    try:
        token = create_enrollment_token(database_path, zone=zone, ttl=ttl)
    except ControllerError as exc:
        raise DeployError(str(exc)) from exc

    return DeployTokenInstructions(
        token=token,
        controller_url=controller_url,
        windows_install=render_windows_install_commands(
            controller_url=controller_url,
            token=token.token,
            repo=repo,
        ),
        linux_install=render_linux_install_commands(
            controller_url=controller_url,
            token=token.token,
            repo=repo,
        ),
    )


def render_windows_install_commands(
    *,
    controller_url: str,
    token: str = DEFAULT_TOKEN_PLACEHOLDER,
    repo: str = DEFAULT_GITHUB_REPO,
) -> str:
    raw_base_url = _raw_base_url(repo)
    return "\n".join(
        (
            f"$Controller = {_ps_quote(controller_url)}",
            f"$Token = {_ps_quote(token)}",
            f"irm {raw_base_url}/install-agent.ps1 | iex",
            "netorium-agent enroll --controller $Controller --token $Token",
        )
    )


def render_linux_install_commands(
    *,
    controller_url: str,
    token: str = DEFAULT_TOKEN_PLACEHOLDER,
    repo: str = DEFAULT_GITHUB_REPO,
) -> str:
    raw_base_url = _raw_base_url(repo)
    return "\n".join(
        (
            f"CONTROLLER={shlex.quote(controller_url)}",
            f"TOKEN={shlex.quote(token)}",
            f"curl -fsSL {raw_base_url}/install-agent.sh | bash",
            'netorium-agent enroll --controller "$CONTROLLER" --token "$TOKEN"',
        )
    )


def render_windows_agent_script(
    *,
    controller_url: str,
    token: str = DEFAULT_TOKEN_PLACEHOLDER,
    repo: str = DEFAULT_GITHUB_REPO,
) -> str:
    commands = render_windows_install_commands(
        controller_url=controller_url,
        token=token,
        repo=repo,
    )
    return "\n".join(
        (
            "$ErrorActionPreference = \"Stop\"",
            "",
            commands,
            "",
            "Write-Host \"Netorium Agent enrollment command completed.\"",
            "",
        )
    )


def render_linux_agent_script(
    *,
    controller_url: str,
    token: str = DEFAULT_TOKEN_PLACEHOLDER,
    repo: str = DEFAULT_GITHUB_REPO,
) -> str:
    commands = render_linux_install_commands(
        controller_url=controller_url,
        token=token,
        repo=repo,
    )
    return "\n".join(
        (
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            commands,
            "",
            "echo \"Netorium Agent enrollment command completed.\"",
            "",
        )
    )


def write_agent_script(
    output_path: str | Path,
    *,
    platform_name: str,
    controller_url: str,
    token: str = DEFAULT_TOKEN_PLACEHOLDER,
    repo: str = DEFAULT_GITHUB_REPO,
    force: bool = False,
) -> Path:
    path = Path(output_path).expanduser()
    if path.exists() and not force:
        raise DeployError(f"Output file already exists: {path}. Use --force to overwrite it.")

    if platform_name == "windows":
        text = render_windows_agent_script(
            controller_url=controller_url,
            token=token,
            repo=repo,
        )
    elif platform_name == "linux":
        text = render_linux_agent_script(
            controller_url=controller_url,
            token=token,
            repo=repo,
        )
    else:
        raise DeployError(f"Unsupported deploy script platform: {platform_name}")

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise DeployError(f"Could not write deploy script {path}: {exc}") from exc

    return path


def _controller_url(database_path: str | Path) -> str:
    try:
        status = get_controller_status(database_path)
    except ControllerError as exc:
        raise DeployError(str(exc)) from exc

    if not status.initialized or status.enrollment_url is None:
        raise DeployError("Controller is not initialized. Run `netorium controller init` first.")

    return status.enrollment_url.removesuffix("/enroll")


def _raw_base_url(repo: str) -> str:
    clean_repo = repo.strip()
    if not clean_repo:
        raise DeployError("GitHub repository cannot be empty.")
    return f"https://raw.githubusercontent.com/{clean_repo}/main"


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
