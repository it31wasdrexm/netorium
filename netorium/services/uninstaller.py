from __future__ import annotations

import ntpath
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Mapping, Protocol, cast

from netorium.core.platform import user_cache_dir, user_config_path, user_data_dir
from netorium.core.settings import ConfigError, read_config_data
from netorium.services.windows_background import (
    build_schtasks_delete_command,
    build_schtasks_run_command,
)
DEFAULT_PACKAGE_NAME = "netorium-cli"

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
    config_path = user_config_path(platform_name=active_platform, env=env)
    data_dir = user_data_dir(platform_name=active_platform, env=env)
    cache_dir = user_cache_dir(platform_name=active_platform, env=env)
    resolved_manager, package_command = _build_package_command(
        selected_manager,
        package_name=package_name,
        executable=active_executable,
        data_dir=data_dir,
        platform_name=active_platform,
        which=active_which,
    )

    configured_database_path = _read_configured_database_path(config_path)
    executable_path = Path(active_executable)

    if (
        selected_manager == "auto"
        and active_platform.startswith("win")
        and _is_relative_to(executable_path, data_dir)
    ):
        resolved_manager = "standalone"
        package_command = None

    path_targets: tuple[UninstallPathTarget, ...] = ()
    deferred_path_targets: tuple[UninstallPathTarget, ...] = ()
    external_database_path: Path | None = None
    if remove_data:
        if active_platform.startswith("win"):
            targets = [
                UninstallPathTarget("Configuration directory", config_path.parent),
                UninstallPathTarget("Application data directory", data_dir),
            ]
        else:
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

        path_targets = _dedupe_targets(_collapse_nested_path_targets(targets))

    install_artifact_targets = _install_artifact_targets(
        executable=executable_path,
        data_dir=data_dir,
        platform_name=active_platform,
        which=active_which,
        remove_data=remove_data,
        config_dir=config_path.parent,
        cache_dir=cache_dir,
    )

    package_command_detached = False
    if resolved_manager == "standalone":
        if active_platform.startswith("win"):
            package_command_detached = True
            deferred_targets = _dedupe_targets(
                [*install_artifact_targets, *_windows_install_targets(
                    executable=executable_path,
                    remove_data=remove_data,
                    config_dir=config_path.parent,
                    data_dir=data_dir,
                    cache_dir=cache_dir,
                )]
            )
            deferred_path_targets = deferred_targets
            path_targets = ()
            bin_dir = _windows_bin_dir(executable_path, data_dir=data_dir)
            package_command = _windows_deferred_remove_command(
                deferred_path_targets,
                bin_dir=bin_dir,
                executable=executable_path,
            )
        else:
            package_command_detached = True
            deferred_path_targets = _dedupe_targets([*install_artifact_targets, *path_targets])
            path_targets = ()
            package_command = _linux_deferred_remove_command(
                deferred_path_targets,
                launcher_path=_resolve_launcher_path(active_which),
            )
    elif package_command is not None and resolved_manager in {"pipx", "pip"}:
        package_command_detached = True
        deferred_path_targets = _dedupe_targets([*install_artifact_targets, *path_targets])
        path_targets = ()
        package_command = _build_deferred_package_command(
            package_command,
            platform_name=active_platform,
            launcher_path=_resolve_launcher_path(active_which),
            extra_paths=tuple(target.path for target in install_artifact_targets),
        )

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
    if command and command[0] in {"windows-batch-cleanup", "windows-powershell-cleanup"}:
        return "Windows cleanup script"
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
    data_dir: Path,
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
        return "pip", _pip_uninstall_command(executable, package_name, which=which)

    executable_path = Path(executable)
    venv_dir = data_dir / "venv"
    if _is_relative_to(executable_path, venv_dir):
        return "pip", _pip_uninstall_command(executable, package_name, which=which)

    if getattr(sys, "frozen", False):
        return "standalone", None

    if which("pipx") is not None:
        return "pipx", ("pipx", "uninstall", package_name)

    return "pip", _pip_uninstall_command(executable, package_name, which=which)


def _install_artifact_targets(
    *,
    executable: Path,
    data_dir: Path,
    platform_name: str,
    which: Callable[[str], str | None],
    remove_data: bool,
    config_dir: Path,
    cache_dir: Path,
) -> list[UninstallPathTarget]:
    if platform_name.startswith("win"):
        return _windows_install_targets(
            executable=executable,
            remove_data=remove_data,
            config_dir=config_dir,
            data_dir=data_dir,
            cache_dir=cache_dir,
        )

    targets: list[UninstallPathTarget] = []
    launcher = which("netorium")
    if launcher is not None:
        targets.append(UninstallPathTarget("CLI launcher", Path(launcher).expanduser()))

    venv_dir = data_dir / "venv"
    if venv_dir.exists() or _is_relative_to(executable, venv_dir):
        targets.append(UninstallPathTarget("Python virtual environment", venv_dir))

    if getattr(sys, "frozen", False) or not _is_relative_to(executable, venv_dir):
        targets.append(UninstallPathTarget("Standalone executable", executable))

    local_bin = Path.home() / ".local" / "bin" / "netorium"
    if local_bin.exists():
        targets.append(UninstallPathTarget("Local bin launcher", local_bin))

    if remove_data:
        targets.extend(
            [
                UninstallPathTarget("Configuration directory", config_dir),
                UninstallPathTarget("Application data directory", data_dir),
                UninstallPathTarget("Cache directory", cache_dir),
            ]
        )

    return targets


def _linux_deferred_remove_command(
    targets: tuple[UninstallPathTarget, ...],
    *,
    launcher_path: Path | None = None,
) -> tuple[str, ...]:
    cleanup_parts = ["sleep 3", _linux_stop_netorium_processes_fragment()]
    seen_paths: set[Path] = set()
    if launcher_path is not None:
        seen_paths.add(launcher_path.expanduser())
        cleanup_parts.append(f"rm -f {shlex.quote(str(launcher_path))}")
    for target in targets:
        key = target.path.expanduser()
        if key in seen_paths:
            continue
        seen_paths.add(key)
        cleanup_parts.append(f"rm -rf {shlex.quote(str(key))}")
    return ("sh", "-c", "; ".join(cleanup_parts))


def _windows_install_targets(
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
        ]
        programdata_dir = _windows_programdata_dir()
        if programdata_dir is not None:
            targets.append(UninstallPathTarget("Windows service logs directory", programdata_dir))
        if not _is_relative_to(executable, data_dir):
            targets.append(UninstallPathTarget("Standalone executable", executable))
        bin_dir = data_dir / "bin"
        if bin_dir.exists() or _is_relative_to(executable, bin_dir):
            targets.append(UninstallPathTarget("Windows launcher directory", bin_dir))
        venv_dir = data_dir / "venv"
        if venv_dir.exists() or _is_relative_to(executable, venv_dir):
            targets.append(UninstallPathTarget("Windows virtual environment", venv_dir))
        return _collapse_nested_path_targets(targets)

    local_targets = _windows_local_install_targets(executable=executable, data_dir=data_dir)
    if local_targets:
        return local_targets

    return [
        UninstallPathTarget("Standalone executable", executable),
        UninstallPathTarget("Standalone bin directory", executable.parent),
    ]


def _windows_programdata_dir() -> Path | None:
    programdata = os.environ.get("ProgramData")
    if not programdata:
        return None
    return Path(programdata) / "Netorium"


def _windows_local_install_targets(
    *,
    executable: Path,
    data_dir: Path,
) -> list[UninstallPathTarget]:
    if not _is_relative_to(executable, data_dir):
        return []

    targets: list[UninstallPathTarget] = []
    bin_dir = data_dir / "bin"
    venv_dir = data_dir / "venv"

    if _is_relative_to(executable, venv_dir):
        targets.append(UninstallPathTarget("Windows virtual environment", venv_dir))
        targets.append(UninstallPathTarget("Windows launcher directory", bin_dir))
        return targets

    if _is_relative_to(executable, bin_dir):
        targets.append(UninstallPathTarget("Windows launcher directory", bin_dir))
        targets.append(UninstallPathTarget("Windows virtual environment", venv_dir))
        return targets

    return [
        UninstallPathTarget("Standalone executable", executable),
        UninstallPathTarget("Standalone bin directory", executable.parent),
    ]


def _windows_bin_dir(executable: Path, *, data_dir: Path) -> Path | None:
    bin_dir = data_dir / "bin"
    if _is_relative_to(executable, bin_dir):
        return bin_dir
    if executable.parent.name.lower() == "bin" and _is_relative_to(executable.parent, data_dir):
        return executable.parent
    if executable.name.lower() == "netorium.exe":
        return executable.parent
    raw_executable = str(executable)
    normalized_executable = raw_executable.replace("/", "\\")
    if ntpath.basename(normalized_executable).lower() == "netorium.exe":
        parent = ntpath.dirname(normalized_executable)
        if ntpath.basename(parent).lower() == "bin":
            return Path(parent)
    return None


def _windows_deferred_remove_command(
    targets: tuple[UninstallPathTarget, ...],
    *,
    bin_dir: Path | None = None,
    executable: Path | None = None,
) -> tuple[str, ...] | None:
    cleanup_script = _windows_cleanup_powershell_script(
        targets,
        bin_dir=bin_dir,
        executable=executable,
    )
    if not cleanup_script:
        return None

    return ("windows-powershell-cleanup", cleanup_script)


def _windows_cleanup_powershell_script(
    targets: tuple[UninstallPathTarget, ...],
    *,
    bin_dir: Path | None = None,
    executable: Path | None = None,
) -> str:
    removal_paths: list[Path] = []
    if executable is not None:
        removal_paths.append(executable)
    if bin_dir is not None:
        removal_paths.append(bin_dir / "netorium.exe")
        removal_paths.append(bin_dir / "nssm.exe")
        removal_paths.append(bin_dir / "netorium.cmd")
        removal_paths.append(bin_dir)
    removal_paths.extend(target.path for target in targets)
    sorted_paths = _sort_windows_removal_paths(removal_paths)
    if not sorted_paths and bin_dir is None:
        return ""

    path_literals = ",".join(_powershell_single_quote(_windows_path_text(path)) for path in sorted_paths)
    lines = [
        "$ErrorActionPreference = 'SilentlyContinue'",
        "Get-Process -Name netorium,netorium-agent,nssm -ErrorAction SilentlyContinue | "
        "Stop-Process -Force -ErrorAction SilentlyContinue",
        "foreach ($svc in @('NetoriumController','NetoriumAgent')) {",
        "  sc.exe stop $svc | Out-Null",
        "  sc.exe delete $svc | Out-Null",
        "}",
        "foreach ($task in @('NetoriumController','NetoriumAgent')) {",
        "  schtasks /End /TN $task 2>$null | Out-Null",
        "  schtasks /Delete /TN $task /F 2>$null | Out-Null",
        "}",
        "netsh advfirewall firewall delete rule name=\"Netorium Controller\" 2>$null | Out-Null",
        "netsh advfirewall firewall delete rule name=\"Netorium Controller App\" 2>$null | Out-Null",
        "Start-Sleep -Seconds 3",
        f"$Paths = @({path_literals})",
        "for ($retry = 1; $retry -le 6; $retry++) {",
        "  foreach ($target in $Paths) {",
        "    if (Test-Path -LiteralPath $target) {",
        "      Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction SilentlyContinue",
        "    }",
        "  }",
        "  Start-Sleep -Seconds 3",
        "}",
    ]
    if bin_dir is not None:
        entry = _powershell_single_quote(_windows_path_text(bin_dir).rstrip("\\/"))
        lines.extend(
            [
                f"$Entry = {entry}",
                "$UserPath = [Environment]::GetEnvironmentVariable('Path','User')",
                "if ($UserPath) {",
                "$Parts = $UserPath -split ';' | Where-Object {",
                "$_.TrimEnd('\\') -ine $Entry.TrimEnd('\\') -and $_.Trim() -ne ''",
                "}",
                "[Environment]::SetEnvironmentVariable('Path', ($Parts -join ';'), 'User')",
                "}",
            ]
        )
    return "\n".join(lines)


def _sort_windows_removal_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    unique_paths: list[Path] = []
    for path in paths:
        normalized = path.expanduser()
        if normalized in seen:
            continue
        seen.add(normalized)
        unique_paths.append(normalized)

    return sorted(
        unique_paths,
        key=lambda path: len(path.parts),
        reverse=True,
    )


def _build_deferred_package_command(
    command: tuple[str, ...],
    *,
    platform_name: str,
    launcher_path: Path | None = None,
    extra_paths: tuple[Path, ...] = (),
) -> tuple[str, ...]:
    if platform_name.startswith("win"):
        package_command = format_command(command)
        body_parts = ["Start-Sleep -Seconds 3"]
        if package_command and command[0] not in {"windows-powershell-cleanup", "windows-batch-cleanup"}:
            body_parts.append(f"& {package_command}")
        ps_launcher_cleanup = _launcher_cleanup_powershell_fragment(launcher_path)
        if ps_launcher_cleanup:
            body_parts.append(ps_launcher_cleanup)
        seen_paths: set[Path] = set()
        if launcher_path is not None:
            seen_paths.add(launcher_path.expanduser())
        for path in extra_paths:
            key = path.expanduser()
            if key in seen_paths:
                continue
            seen_paths.add(key)
            quoted = _powershell_single_quote(str(key))
            body_parts.append(
                f"if (Test-Path -LiteralPath {quoted}) "
                f"{{ Remove-Item -LiteralPath {quoted} -Recurse -Force -ErrorAction SilentlyContinue }}"
            )
        body = "; ".join(body_parts)
        return (
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-WindowStyle",
            "Hidden",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            body,
        )

    launcher_cleanup = _launcher_cleanup_fragment(platform_name, launcher_path)
    shell_parts = ["sleep 3", _linux_stop_netorium_processes_fragment(), " ".join(shlex.quote(part) for part in command)]
    if launcher_cleanup:
        shell_parts.append(launcher_cleanup)
    seen_paths: set[Path] = set()
    if launcher_path is not None:
        seen_paths.add(launcher_path.expanduser())
    for path in extra_paths:
        key = path.expanduser()
        if key in seen_paths:
            continue
        seen_paths.add(key)
        shell_parts.append(f"rm -rf {shlex.quote(str(key))}")
    return ("sh", "-c", "; ".join(shell_parts))


def _pip_uninstall_command(
    executable: str,
    package_name: str,
    *,
    which: Callable[[str], str | None],
) -> tuple[str, ...]:
    if getattr(sys, "frozen", False):
        if which("pip") is not None:
            return _with_break_system_packages(("pip", "uninstall", "-y", package_name))
        raise UninstallError(
            "Cannot uninstall: frozen executable detected and pip not found on PATH."
        )

    return _with_break_system_packages(
        (executable, "-m", "pip", "uninstall", "-y", package_name)
    )


def _with_break_system_packages(command: tuple[str, ...]) -> tuple[str, ...]:
    if not _is_externally_managed_python():
        return command
    if command[-1] == "--break-system-packages":
        return command
    return (*command, "--break-system-packages")


def _is_externally_managed_python() -> bool:
    for prefix in {Path(sys.prefix), Path(getattr(sys, "base_prefix", sys.prefix))}:
        if (prefix / "EXTERNALLY-MANAGED").exists():
            return True
    return False


def _resolve_launcher_path(which: Callable[[str], str | None]) -> Path | None:
    launcher = which("netorium")
    if launcher is None:
        return None
    return Path(launcher).expanduser()


def _linux_stop_netorium_processes_fragment() -> str:
    return (
        "pkill -f '[n]etorium agent run-loop' >/dev/null 2>&1 || true; "
        "pkill -f '[n]etorium controller run' >/dev/null 2>&1 || true"
    )


def _launcher_cleanup_fragment(platform_name: str, launcher_path: Path | None) -> str:
    if launcher_path is None:
        return ""
    if platform_name.startswith("win"):
        quoted = _cmd_quote_string(str(launcher_path))
        return f"if exist {quoted} del /f /q {quoted} >nul 2>nul"
    return f"rm -f {shlex.quote(str(launcher_path))}"


def _launcher_cleanup_powershell_fragment(launcher_path: Path | None) -> str:
    if launcher_path is None:
        return ""
    quoted = _powershell_single_quote(str(launcher_path))
    return (
        f"if (Test-Path -LiteralPath {quoted}) "
        f"{{ Remove-Item -LiteralPath {quoted} -Force -ErrorAction SilentlyContinue }}"
    )


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

    return UninstallPathTarget("Configured database file", database_path)


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
    if sys.platform.startswith("win"):
        return _run_windows_cleanup_detached(args)

    try:
        subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except FileNotFoundError as exc:
        raise UninstallError(
            f"Command not found while scheduling uninstall cleanup: {args[0]}"
        ) from exc
    return 0


def _run_windows_cleanup_detached(args: tuple[str, ...]) -> int:
    if len(args) >= 2 and args[0] == "windows-powershell-cleanup":
        return _schedule_windows_powershell_cleanup(args[1])
    if len(args) >= 1 and args[0] == "windows-batch-cleanup":
        return _schedule_windows_powershell_cleanup("\n".join(args[1:]))

    launch_args = args
    try:
        subprocess.Popen(
            launch_args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=_windows_no_window_flags(),
        )
    except FileNotFoundError as exc:
        raise UninstallError(
            f"Command not found while scheduling uninstall cleanup: {launch_args[0]}"
        ) from exc
    return 0


def _schedule_windows_powershell_cleanup(cleanup_body: str) -> int:
    parent_pid = os.getpid()
    task_name = f"NetoriumUninstall-{uuid.uuid4().hex[:8]}"
    script_path = Path(tempfile.gettempdir()) / f"netorium-uninstall-{parent_pid}.ps1"
    script_lines = [
        "$ErrorActionPreference = 'SilentlyContinue'",
        f"Wait-Process -Id {parent_pid} -ErrorAction SilentlyContinue",
        "Start-Sleep -Seconds 3",
        cleanup_body,
        f"schtasks /Delete /TN {_powershell_single_quote(task_name)} /F 2>$null | Out-Null",
        "Remove-Item -LiteralPath $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue",
    ]
    script_path.write_text("\n".join(script_lines), encoding="utf-8")

    task_action = subprocess.list2cmdline(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-WindowStyle",
            "Hidden",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        ]
    )
    create_args = [
        "schtasks",
        "/Create",
        "/TN",
        task_name,
        "/TR",
        task_action,
        "/SC",
        "ONCE",
        "/ST",
        "00:01",
        "/F",
        "/RL",
        "HIGHEST",
    ]
    try:
        _run_hidden_subprocess(create_args)
        _run_hidden_subprocess(build_schtasks_run_command(task_name))
    except FileNotFoundError as exc:
        _run_hidden_subprocess(build_schtasks_delete_command(task_name))
        raise UninstallError(
            f"Command not found while scheduling uninstall cleanup: {exc.filename}"
        ) from exc
    return 0


def _run_hidden_subprocess(args: list[str]) -> None:
    subprocess.run(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        creationflags=_windows_no_window_flags(),
    )


def _windows_no_window_flags() -> int:
    return (
        getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        | getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )


def _collapse_nested_path_targets(
    targets: list[UninstallPathTarget],
) -> list[UninstallPathTarget]:
    normalized = _dedupe_targets(targets)
    kept: list[UninstallPathTarget] = []
    for candidate in normalized:
        if any(_is_relative_to(candidate.path, existing.path) for existing in kept):
            continue
        kept.append(candidate)
    return kept


def _cmd_quote(path: Path) -> str:
    return _cmd_quote_string(_windows_path_text(path))


def _windows_path_text(path: Path) -> str:
    return str(path).replace("/", "\\")


def _cmd_quote_string(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _powershell_single_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _quote_display_part(value: str) -> str:
    if not value or re.search(r"\s", value):
        return '"' + value.replace('"', '\\"') + '"'
    return value
