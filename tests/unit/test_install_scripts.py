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


def test_dockerfile_installs_and_runs_cli() -> None:
    text = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "FROM python:3.11-slim" in text
    assert "python -m pip install --no-cache-dir ." in text
    assert 'ENTRYPOINT ["netorium"]' in text


def test_release_workflow_builds_standalone_assets() -> None:
    text = (PROJECT_ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )

    assert "netorium-windows-x64.exe" in text
    assert "netorium-linux-x64" in text
    assert "pyinstaller --noconfirm --clean packaging/netorium.spec" in text
    assert "ghcr.io/${{ github.repository }}" in text


def test_pyproject_declares_build_backend() -> None:
    text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "[build-system]" in text
    assert 'build-backend = "setuptools.build_meta"' in text
    assert '"pyinstaller>=6.9"' in text
