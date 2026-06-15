from __future__ import annotations

from dataclasses import dataclass

from netorium.core.settings import ConfigError, load_settings
from netorium.services.update_checker import (
    DEFAULT_TIMEOUT_SECONDS,
    HttpClient,
    PlatformInstallInstructions,
    UpdateCheckError,
    UpdateInfo,
    build_download_instructions,
    build_platform_install_instructions,
    build_update_config,
    check_for_update,
)


@dataclass(frozen=True)
class StartupUpdateNotice:
    info: UpdateInfo
    platform: PlatformInstallInstructions


def get_startup_update_notice(
    client: HttpClient | None = None,
    current_version: str | None = None,
    system_name: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> StartupUpdateNotice | None:
    try:
        settings = load_settings()
    except ConfigError:
        return None

    if not settings.updates.check_on_start:
        return None

    try:
        config = build_update_config(
            source=settings.updates.source,
            repo=settings.updates.repo,
        )
        info = check_for_update(
            config,
            current_version=current_version,
            client=client,
            timeout=timeout,
        )
    except UpdateCheckError:
        return None

    if not info.is_update_available:
        return None

    instructions = build_download_instructions(
        repo=config.repo,
        package_name=config.package_name,
    )
    return StartupUpdateNotice(
        info=info,
        platform=build_platform_install_instructions(
            instructions,
            system_name=system_name,
        ),
    )
