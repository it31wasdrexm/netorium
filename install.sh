#!/usr/bin/env bash
set -euo pipefail

PACKAGE_NAME="${NETORIUM_PACKAGE_NAME:-netorium-cli}"
INSTALL_SOURCE="${NETORIUM_INSTALL_SOURCE:-github}"
GITHUB_REPO="${NETORIUM_GITHUB_REPO:-it31wasdrexm/netorium}"
GITHUB_REF="${NETORIUM_GITHUB_REF:-main}"
GITHUB_REF_KIND="${NETORIUM_GITHUB_REF_KIND:-heads}"
PACKAGE_SPEC="${NETORIUM_PACKAGE_SPEC:-}"
RUN_COMMAND="netorium --help"

if [[ -z "$PACKAGE_SPEC" ]]; then
  case "$INSTALL_SOURCE" in
    github)
      if [[ "$GITHUB_REPO" == "OWNER/REPO" ]]; then
        echo "Netorium GitHub repository is not configured." >&2
        echo "Set NETORIUM_GITHUB_REPO=owner/repo or NETORIUM_PACKAGE_SPEC before running this installer." >&2
        exit 1
      fi
      PACKAGE_SPEC="https://github.com/${GITHUB_REPO}/archive/refs/${GITHUB_REF_KIND}/${GITHUB_REF}.zip"
      ;;
    pypi)
      PACKAGE_SPEC="$PACKAGE_NAME"
      ;;
    local)
      SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
      PACKAGE_SPEC="$SCRIPT_DIR"
      ;;
    *)
      echo "Unsupported NETORIUM_INSTALL_SOURCE: $INSTALL_SOURCE" >&2
      echo "Use github, pypi, local, or set NETORIUM_PACKAGE_SPEC directly." >&2
      exit 1
      ;;
  esac
fi

install_with_venv() {
  if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 is required to install Netorium CLI." >&2
    exit 1
  fi

  if [[ -z "${HOME:-}" ]]; then
    echo "HOME is required when installing without pipx." >&2
    exit 1
  fi

  DATA_HOME="${XDG_DATA_HOME:-"$HOME/.local/share"}"
  VENV_DIR="${NETORIUM_VENV_DIR:-"$DATA_HOME/netorium/venv"}"
  BIN_DIR="${NETORIUM_BIN_DIR:-"$HOME/.local/bin"}"
  COMMAND_LINK="$BIN_DIR/netorium"

  if ! python3 -m venv "$VENV_DIR"; then
    echo "Could not create a Python virtual environment." >&2
    echo "Install pipx or python3-venv, then run this installer again." >&2
    exit 1
  fi

  if ! "$VENV_DIR/bin/python" -m pip --version >/dev/null 2>&1; then
    "$VENV_DIR/bin/python" -m ensurepip --upgrade
  fi

  "$VENV_DIR/bin/python" -m pip install --upgrade "$PACKAGE_SPEC"

  mkdir -p "$BIN_DIR"
  if [[ -e "$COMMAND_LINK" && ! -L "$COMMAND_LINK" ]]; then
    echo "Netorium CLI installed into $VENV_DIR." >&2
    echo "Could not create $COMMAND_LINK because that path already exists and is not a symlink." >&2
    echo "Run directly: $VENV_DIR/bin/netorium --help" >&2
    RUN_COMMAND="$VENV_DIR/bin/netorium --help"
    return
  fi

  ln -sfn "$VENV_DIR/bin/netorium" "$COMMAND_LINK"

  if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo "Netorium CLI was linked to $COMMAND_LINK."
    echo "Add $BIN_DIR to PATH or run: $COMMAND_LINK --help"
    RUN_COMMAND="$COMMAND_LINK --help"
  fi
}

if command -v pipx >/dev/null 2>&1; then
  pipx install --force "$PACKAGE_SPEC"
else
  install_with_venv
fi

echo "Netorium CLI installed."
echo "Run: $RUN_COMMAND"
