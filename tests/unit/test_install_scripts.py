from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_linux_installer_supports_github_pypi_and_local_modes() -> None:
    text = (PROJECT_ROOT / "install.sh").read_text(encoding="utf-8")

    assert "NETORIUM_INSTALL_SOURCE" in text
    assert "NETORIUM_GITHUB_REPO" in text
    assert "NETORIUM_GITHUB_REF_KIND" in text
    assert "it31wasdrexm/netorium" in text
    assert "pipx install --force" in text
    assert "python3 -m venv" in text
    assert "NETORIUM_VENV_DIR" in text
    assert "python3 -m pip install --user --upgrade" not in text
    assert "standalone release binary or Docker image" in text


def test_windows_installer_supports_github_pypi_and_local_modes() -> None:
    text = (PROJECT_ROOT / "install.ps1").read_text(encoding="utf-8")

    assert "NETORIUM_INSTALL_SOURCE" in text
    assert "NETORIUM_GITHUB_REPO" in text
    assert "NETORIUM_GITHUB_REF_KIND" in text
    assert "it31wasdrexm/netorium" in text
    assert "pipx install --force" in text
    assert "Get-PythonCommand" in text
    assert '"py"; Arguments = @("-3")' in text
    assert '"python"; Arguments = @()' in text
    assert '"python3"; Arguments = @()' in text
    assert "Python 3.11+ or pipx is required" in text
    assert '"-m", "venv", $VenvDir' in text
    assert "NETORIUM_VENV_DIR" in text
    assert '"-m", "pip", "install", "--user", "--upgrade"' not in text


def test_install_docs_include_download_commands() -> None:
    text = (PROJECT_ROOT / "netorium" / "docs" / "install.md").read_text(encoding="utf-8")

    assert "raw.githubusercontent.com/it31wasdrexm/netorium/main/install.sh" in text
    assert "raw.githubusercontent.com/it31wasdrexm/netorium/main/install.ps1" in text
    assert "NETORIUM_GITHUB_REPO=OWNER/REPO" in text
    assert "| NETORIUM_INSTALL_SOURCE=pypi bash" in text
    assert "If `pipx` is not" in text
    assert "`py -3`, `python`, then `python3`" in text
    assert "netorium-windows-x64.exe" in text
    assert "docker run --rm -it ghcr.io/it31wasdrexm/netorium:latest" in text
    assert "scripts/build-standalone.sh" in text
    assert ".\\scripts\\build-windows.ps1" in text
    assert "Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force" in text
    assert "Unblock-File .\\scripts\\build-windows.ps1" in text
    assert "-ExecutionPolicy Bypass" not in text
    assert ".venv-win" in text
    assert ".venv-release-win" in text
    assert "Build the Windows standalone executable on Windows" in text
    assert "scripts/build-windows-on-linux.sh" not in text


def test_local_release_helpers_use_native_asset_names() -> None:
    native = (PROJECT_ROOT / "scripts" / "build-standalone.sh").read_text(encoding="utf-8")
    windows = (PROJECT_ROOT / "scripts" / "build-windows.ps1").read_text(encoding="utf-8")

    assert "python3.14" in native
    assert "python3.11 -m venv" not in native
    assert "NETORIUM_PYTHON" in native
    assert "NETORIUM_RELEASE_VENV" in native
    assert "NETORIUM_RELEASE_TEMP_DIR" in native
    assert "PYINSTALLER_CONFIG_DIR" in native
    assert "-m PyInstaller --noconfirm --clean packaging/netorium.spec" in native
    assert "python -m pip install --upgrade pip" not in native
    assert "asset_name=\"netorium-linux-$(asset_arch)\"" in native
    assert "build-windows-on-linux.sh" not in native

    assert "NETORIUM_PYTHON" in windows
    assert "Python 3.11+ was not found" in windows
    assert ".venv-release-win" in windows
    assert ".netorium-release-tmp" in windows
    assert "$env:TEMP" in windows
    assert "$env:PIP_CACHE_DIR" in windows
    assert "$env:PYINSTALLER_CONFIG_DIR" in windows
    assert 'Join-Path "dist" "netorium.exe"' in windows
    assert "netorium-windows-$(Get-AssetArch).exe" in windows
    assert "NETORIUM_WINE_PYTHON" not in windows
    assert "${LASTEXITCODE}:" in windows
    assert "$LASTEXITCODE:" not in windows
    assert (PROJECT_ROOT / "scripts" / "build-windows.cmd").exists() is False


def test_install_docs_document_native_linux_and_windows_release_assets() -> None:
    text = (PROJECT_ROOT / "netorium" / "docs" / "install.md").read_text(encoding="utf-8")

    assert "scripts/build-standalone.sh" in text
    assert ".\\scripts\\build-windows.ps1" in text
    assert ".\\scripts\\build-windows.cmd" not in text
    assert "Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force" in text
    assert "Unblock-File .\\scripts\\build-windows.ps1" in text
    assert "-ExecutionPolicy Bypass" not in text
    assert ".venv-release-win" in text
    assert ".netorium-release-tmp" in text
    assert "release-assets/netorium-windows-x64.exe" in text
    assert "runs on the target Windows PC without" in text
    assert "Python installed" in text
    assert "Build the Windows standalone executable on Windows" in text
    assert "scripts/build-windows-on-linux.sh" not in text


def test_gitignore_excludes_local_release_outputs() -> None:
    text = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "www/" in text
    assert "README_CODEX.md" not in text
    assert "TECH_SPEC_EN.md" not in text
    assert "TECH_SPEC_RU.md" not in text
    assert "RELEASE_BUILD.md" not in text
    assert "INSTALL.md" not in text
    assert ".venv-release/" in text
    assert ".venv-release-win/" in text
    assert ".venv-win/" in text
    assert "release-assets/" in text


def test_dockerfile_installs_and_runs_cli() -> None:
    text = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "FROM python:3.11-slim" in text
    assert "python -m pip install --no-cache-dir ." in text
    assert 'ENTRYPOINT ["netorium"]' in text


def test_dockerignore_excludes_local_agent_docs() -> None:
    text = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "www/" in text


def test_github_actions_release_workflow_was_removed() -> None:
    assert (PROJECT_ROOT / ".github" / "workflows" / "release.yml").exists() is False


def test_pyinstaller_spec_uses_paths_relative_to_spec_file() -> None:
    text = (PROJECT_ROOT / "packaging" / "netorium.spec").read_text(encoding="utf-8")

    assert "Path(SPECPATH)" in text
    assert 'spec_dir / "standalone_entry.py"' in text
    assert "pathex=[str(project_root)]" in text
    assert '["packaging/standalone_entry.py"]' not in text


def test_pyproject_declares_build_backend() -> None:
    text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "[build-system]" in text
    assert 'build-backend = "setuptools.build_meta"' in text
    assert '"pyinstaller>=6.9"' in text
    assert "[tool.setuptools.packages.find]" in text
    assert 'include = ["netorium*"]' in text
