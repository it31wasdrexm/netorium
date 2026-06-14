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
    assert '"$VENV_DIR/bin/python" -m pip install --upgrade "$PACKAGE_SPEC"' in text
    assert "python3 -m pip install --user --upgrade" not in text
    assert "NETORIUM_VENV_DIR" in text
    assert "NETORIUM_BIN_DIR" in text


def test_windows_installer_supports_github_pypi_and_local_modes() -> None:
    text = (PROJECT_ROOT / "install.ps1").read_text(encoding="utf-8")

    assert "NETORIUM_INSTALL_SOURCE" in text
    assert "NETORIUM_GITHUB_REPO" in text
    assert "NETORIUM_GITHUB_REF_KIND" in text
    assert "it31wasdrexm/netorium" in text
    assert "pipx install --force" in text
    assert "py -m pip install --user --upgrade" in text


def test_install_docs_include_download_commands() -> None:
    text = (PROJECT_ROOT / "netorium" / "docs" / "install.md").read_text(encoding="utf-8")

    assert "github.com/it31wasdrexm/netorium/raw/main/install.sh" in text
    assert "github.com/it31wasdrexm/netorium/raw/main/install.ps1" in text
    assert "NETORIUM_GITHUB_REPO=OWNER/REPO" in text
    assert "| NETORIUM_INSTALL_SOURCE=pypi bash" in text
    assert "If `pipx` is not installed" in text
    assert "~/.local/share/netorium/venv" in text


def test_pyproject_declares_build_backend() -> None:
    text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "[build-system]" in text
    assert 'build-backend = "setuptools.build_meta"' in text
