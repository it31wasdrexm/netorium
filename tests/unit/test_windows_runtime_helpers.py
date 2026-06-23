from __future__ import annotations

from pathlib import Path

import pytest

from netorium.services import uninstaller
from netorium.services.windows_nssm import resolve_nssm_executable


def test_resolve_nssm_prefers_binary_beside_frozen_executable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    install_dir = tmp_path / "bin"
    install_dir.mkdir()
    nssm_path = install_dir / "nssm.exe"
    nssm_path.write_text("nssm", encoding="utf-8")
    executable = install_dir / "netorium.exe"
    executable.write_text("netorium", encoding="utf-8")

    monkeypatch.setattr(uninstaller.sys, "frozen", True, raising=False)
    monkeypatch.setattr(uninstaller.sys, "executable", str(executable))
    monkeypatch.setattr("netorium.services.windows_nssm.sys.frozen", True, raising=False)
    monkeypatch.setattr("netorium.services.windows_nssm.sys.executable", str(executable))
    monkeypatch.setattr("netorium.services.windows_nssm.sys.platform", "win32")
    monkeypatch.setattr("netorium.services.windows_nssm.shutil.which", lambda _name: None)

    assert resolve_nssm_executable() == str(nssm_path)


def test_windows_cleanup_script_orders_deepest_paths_first(tmp_path: Path) -> None:
    data_dir = tmp_path / "Local" / "Netorium"
    cache_dir = data_dir / "Cache"
    cache_dir.mkdir(parents=True)
    executable = data_dir / "bin" / "netorium.exe"
    executable.parent.mkdir(parents=True)
    executable.write_text("exe", encoding="utf-8")

    script_lines = uninstaller._windows_cleanup_script_lines(
        (
            uninstaller.UninstallPathTarget("Application data directory", data_dir),
            uninstaller.UninstallPathTarget("Cache directory", cache_dir),
        ),
        executable=executable,
        bin_dir=executable.parent,
    )

    rmdir_lines = [line for line in script_lines if "rmdir /s /q" in line]
    cache_index = next(index for index, line in enumerate(rmdir_lines) if "Cache" in line)
    quoted_data_dir = f'"{data_dir}"'
    data_index = next(
        index
        for index, line in enumerate(rmdir_lines)
        if f"rmdir /s /q {quoted_data_dir}" in line
    )
    assert cache_index < data_index
