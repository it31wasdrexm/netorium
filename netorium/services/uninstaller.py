from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Mapping, Protocol, cast

from netorium.core.platform import user_cache_dir, user_config_path, user_data_dir
from netorium.core.settings import ConfigError, read_config_data
from netorium.services.update_checker import DEFAULT_PACKAGE_NAME

PackageManager = Literal["auto", "pipx", "pip", "none"]
SelectedPackageManager = Literal["pipx", "pip", "none"]


class CommandRunner(Protocol):
    def __call__(self, args: tuple[str, ...]) -> int:
        pass


class UninstallError(RuntimeError):
    pass


@dataclass(frozen=True)
class UninstallPathTarget:
    label: str
    path: Path


@dataclass(frozen=True)
class UninstallPlan:
    package_name: str
    package_manager: SelectedPackageManager
    package_command: tuple[str, ...] | None
    remove_data: bool
    path_targets: tuple[UninstallPathTarget, ...]
    external_database_path: Path | None


@dataclass(frozen=True)
class UninstallResult:
    package_command_ran: bool
    removed_paths: tuple[Path, ...]
    skipped_paths: tuple[Path, ...]


def build_uninstall_plan(
    *,
    remove_data: bool = False,
    package_manager: str = "auto",
    package_name: str = DEFAULT_PACKAGE_NAME,
    env: Mapping[str, str] | None = None,
    platform_name: str | None = None,
    executable: str | None = None,
    which: Callable[[str], str | None] | None = None,
) -> UninstallPlan:
    selected_manager = _normalize_package_manager(package_manager)
    active_which = which or shutil.which
    active_executable = executable or sys.executable
    resolved_manager, package_command = _build_package_command(
        selected_manager,
        package_name=package_name,
        executable=active_executable,
        which=active_which,
    )

    config_path = user_config_path(platform_name=platform_name, env=env)
    data_dir = user_data_dir(platform_name=platform_name, env=env)
    cache_dir = user_cache_dir(platform_name=platform_name, env=env)
    configured_database_path = _read_configured_database_path(config_path)

    path_targets: tuple[UninstallPathTarget, ...] = ()
    external_database_path: Path | None = None
    if remove_data:
        targets = [
            UninstallPathTarget("Configuration directory", config_path.parent),
            UninstallPathTarget("Application data directory", data_dir),
            UninstallPathTarget("Cache directory", cache_dir),
        ]
        database_target = _database_target(configured_database_path, data_dir)
        if database_target is not None:
            targets.append(database_target)
        elif configured_database_path is not None and not _is_relative_to(
            configured_database_path, data_dir
        ):
            external_database_path = configured_database_path

        path_targets = _dedupe_targets(targets)

    return UninstallPlan(
        package_name=package_name,
        package_manager=resolved_manager,
        package_command=package_command,
        remove_data=remove_data,
        path_targets=path_targets,
        external_database_path=external_database_path,
    )


def execute_uninstall_plan(
    plan: UninstallPlan,
    *,
    runner: CommandRunner | None = None,
) -> UninstallResult:
    package_command_ran = False
    active_runner = runner or _run_command
    if plan.package_command is not None:
        exit_code = active_runner(plan.package_command)
        package_command_ran = True
        if exit_code != 0:
            raise UninstallError(
                f"Package uninstall command failed with exit code {exit_code}: "
                f"{format_command(plan.package_command)}"
            )

    removed_paths: list[Path] = []
    skipped_paths: list[Path] = []
    for target in plan.path_targets:
        if _remove_path(target.path):
            removed_paths.append(target.path)
        else:
            skipped_paths.append(target.path)

    return UninstallResult(
        package_command_ran=package_command_ran,
        removed_paths=tuple(removed_paths),
        skipped_paths=tuple(skipped_paths),
    )


def format_command(command: tuple[str, ...]) -> str:
    return " ".join(command)


def _normalize_package_manager(value: str) -> PackageManager:
    normalized = value.lower()
    if normalized not in ("auto", "pipx", "pip", "none"):
        raise UninstallError("Package manager must be one of: auto, pipx, pip, none.")
    return cast(PackageManager, normalized)


def _build_package_command(
    package_manager: PackageManager,
    *,
    package_name: str,
    executable: str,
    which: Callable[[str], str | None],
) -> tuple[SelectedPackageManager, tuple[str, ...] | None]:
    if package_manager == "none":
        return "none", None

    if package_manager == "pipx":
        if which("pipx") is None:
            raise UninstallError("pipx was requested, but it was not found on PATH.")
        return "pipx", ("pipx", "uninstall", package_name)

    if package_manager == "pip":
        return "pip", (executable, "-m", "pip", "uninstall", "-y", package_name)

    if which("pipx") is not None:
        return "pipx", ("pipx", "uninstall", package_name)

    return "pip", (executable, "-m", "pip", "uninstall", "-y", package_name)


def _read_configured_database_path(config_path: Path) -> Path | None:
    try:
        data = read_config_data(config_path)
    except ConfigError:
        return None

    app_data = data.get("app")
    if not isinstance(app_data, dict):
        return None

    raw_database_path = app_data.get("database_path")
    if not isinstance(raw_database_path, str) or not raw_database_path.strip():
        return None

    return Path(raw_database_path).expanduser()


def _database_target(database_path: Path | None, data_dir: Path) -> UninstallPathTarget | None:
    if database_path is None or _is_relative_to(database_path, data_dir):
        return None

    if database_path.name == "netorium.db" and database_path.parent.name.lower() == "netorium":
        return UninstallPathTarget("Configured database file", database_path)

    return None


def _dedupe_targets(targets: list[UninstallPathTarget]) -> tuple[UninstallPathTarget, ...]:
    seen: set[Path] = set()
    unique_targets: list[UninstallPathTarget] = []
    for target in targets:
        key = target.path.expanduser()
        if key in seen:
            continue
        seen.add(key)
        unique_targets.append(UninstallPathTarget(target.label, key))
    return tuple(unique_targets)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        active_path = path.expanduser().resolve(strict=False)
        active_parent = parent.expanduser().resolve(strict=False)
        active_path.relative_to(active_parent)
        return True
    except ValueError:
        return False


def _remove_path(path: Path) -> bool:
    if not path.exists() and not path.is_symlink():
        return False

    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()
    return True


def _run_command(args: tuple[str, ...]) -> int:
    completed = subprocess.run(args, check=False)
    return completed.returncode
