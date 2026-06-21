from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Mapping, Protocol, cast

from netorium.core.platform import user_cache_dir, user_config_path, user_data_dir
from netorium.core.settings import ConfigError, read_config_data
from netorium.services.update_checker import DEFAULT_PACKAGE_NAME

PackageManager = Literal["auto", "pipx", "pip", "standalone", "none"]
SelectedPackageManager = Literal["pipx", "pip", "standalone", "none"]


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
    package_command_detached: bool
    remove_data: bool
    path_targets: tuple[UninstallPathTarget, ...]
    deferred_path_targets: tuple[UninstallPathTarget, ...]
    external_database_path: Path | None


@dataclass(frozen=True)
class UninstallResult:
    package_command_ran: bool
    removed_paths: tuple[Path, ...]
    skipped_paths: tuple[Path, ...]
    deferred_paths: tuple[Path, ...]


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
    active_platform = platform_name or sys.platform
    resolved_manager, package_command = _build_package_command(
        selected_manager,
        package_name=package_name,
        executable=active_executable,
        platform_name=active_platform,
        which=active_which,
    )

    config_path = user_config_path(platform_name=active_platform, env=env)
    data_dir = user_data_dir(platform_name=active_platform, env=env)
    cache_dir = user_cache_dir(platform_name=active_platform, env=env)
    configured_database_path = _read_configured_database_path(config_path)

    path_targets: tuple[UninstallPathTarget, ...] = ()
    deferred_path_targets: tuple[UninstallPathTarget, ...] = ()
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

    package_command_detached = False
    if resolved_manager == "standalone":
        if active_platform.startswith("win"):
            package_command_detached = True
            deferred_targets = _windows_standalone_targets(
                executable=Path(active_executable),
                remove_data=remove_data,
                config_dir=config_path.parent,
                data_dir=data_dir,
                cache_dir=cache_dir,
            )
            deferred_path_targets = _dedupe_targets(deferred_targets)
            path_targets = ()
            package_command = _windows_deferred_remove_command(deferred_path_targets)
        else:
            path_targets = _dedupe_targets(
                [
                    UninstallPathTarget("Standalone executable", Path(active_executable)),
                    *path_targets,
                ]
            )
            package_command = None

    return UninstallPlan(
        package_name=package_name,
        package_manager=resolved_manager,
        package_command=package_command,
        package_command_detached=package_command_detached,
        remove_data=remove_data,
        path_targets=path_targets,
        deferred_path_targets=deferred_path_targets,
        external_database_path=external_database_path,
    )


def execute_uninstall_plan(
    plan: UninstallPlan,
    *,
    runner: CommandRunner | None = None,
) -> UninstallResult:
    package_command_ran = False
    active_runner = runner or _run_command
    if plan.package_command is not None and not plan.package_command_detached:
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

    if plan.package_command is not None and plan.package_command_detached:
        exit_code = (
            active_runner(plan.package_command)
            if runner is not None
            else _run_command_detached(plan.package_command)
        )
        package_command_ran = True
        if exit_code != 0:
            raise UninstallError(
                f"Deferred uninstall command failed with exit code {exit_code}: "
                f"{format_command(plan.package_command)}"
            )

    return UninstallResult(
        package_command_ran=package_command_ran,
        removed_paths=tuple(removed_paths),
        skipped_paths=tuple(skipped_paths),
        deferred_paths=tuple(target.path for target in plan.deferred_path_targets),
    )


def format_command(command: tuple[str, ...]) -> str:
    return " ".join(_quote_display_part(part) for part in command)


def _normalize_package_manager(value: str) -> PackageManager:
    normalized = value.lower()
    if normalized not in ("auto", "pipx", "pip", "standalone", "none"):
        raise UninstallError(
            "Package manager must be one of: auto, pipx, pip, standalone, none."
        )
    return cast(PackageManager, normalized)


def _build_package_command(
    package_manager: PackageManager,
    *,
    package_name: str,
    executable: str,
    platform_name: str,
    which: Callable[[str], str | None],
) -> tuple[SelectedPackageManager, tuple[str, ...] | None]:
    if package_manager == "none":
        return "none", None

    if package_manager == "standalone":
        return "standalone", None

    if package_manager == "pipx":
        if which("pipx") is None:
            raise UninstallError("pipx was requested, but it was not found on PATH.")
        return "pipx", ("pipx", "uninstall", package_name)

    if package_manager == "pip":
        if getattr(sys, "frozen", False):
            if which("pip") is not None:
                return "pip", ("pip", "uninstall", "-y", package_name)
            raise UninstallError(
                "Cannot uninstall: frozen executable detected and pip not found on PATH."
            )
        return "pip", (executable, "-m", "pip", "uninstall", "-y", package_name)

    if getattr(sys, "frozen", False):
        return "standalone", None

    if which("pipx") is not None:
        return "pipx", ("pipx", "uninstall", package_name)

    return "pip", (executable, "-m", "pip", "uninstall", "-y", package_name)


def _windows_standalone_targets(
    *,
    executable: Path,
    remove_data: bool,
    config_dir: Path,
    data_dir: Path,
    cache_dir: Path,
) -> list[UninstallPathTarget]:
    if remove_data:
        targets = [
            UninstallPathTarget("Configuration directory", config_dir),
            UninstallPathTarget("Application data directory", data_dir),
            UninstallPathTarget("Cache directory", cache_dir),
        ]
        if not _is_relative_to(executable, data_dir):
            targets.append(UninstallPathTarget("Standalone executable", executable))
        return targets

    return [
        UninstallPathTarget("Standalone executable", executable),
        UninstallPathTarget("Standalone bin directory", executable.parent),
    ]


def _windows_deferred_remove_command(
    targets: tuple[UninstallPathTarget, ...],
) -> tuple[str, ...] | None:
    if not targets:
        return None

    commands = ["timeout /t 3 /nobreak >nul 2>nul"]
    for target in targets:
        quoted_path = _cmd_quote(target.path)
        quoted_children = _cmd_quote_string(f"{target.path}\\*")
        commands.append(f"if exist {quoted_children} rmdir /s /q {quoted_path} >nul 2>nul")
        commands.append(f"if exist {quoted_path} del /f /q {quoted_path} >nul 2>nul")
    return ("cmd.exe", "/d", "/c", " & ".join(commands))


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


def _run_command_detached(args: tuple[str, ...]) -> int:
    kwargs: dict[str, object] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform.startswith("win"):
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )
        kwargs["creationflags"] = creationflags

    try:
        subprocess.Popen(args, **kwargs)
    except FileNotFoundError as exc:
        raise UninstallError(
            f"Command not found while scheduling uninstall cleanup: {args[0]}"
        ) from exc
    return 0


def _cmd_quote(path: Path) -> str:
    return _cmd_quote_string(str(path))


def _cmd_quote_string(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _quote_display_part(value: str) -> str:
    if not value or re.search(r"\s", value):
        return '"' + value.replace('"', '\\"') + '"'
    return value
