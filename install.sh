#!/usr/bin/env bash
set -euo pipefail

PACKAGE_NAME="${NETORIUM_PACKAGE_NAME:-netorium-cli}"
INSTALL_SOURCE="${NETORIUM_INSTALL_SOURCE:-github}"
GITHUB_REPO="${NETORIUM_GITHUB_REPO:-it31wasdrexm/netorium}"
GITHUB_REF="${NETORIUM_GITHUB_REF:-main}"
GITHUB_REF_KIND="${NETORIUM_GITHUB_REF_KIND:-heads}"
PACKAGE_SPEC="${NETORIUM_PACKAGE_SPEC:-}"
VENV_DIR="${NETORIUM_VENV_DIR:-${HOME}/.local/share/netorium/venv}"
BIN_DIR="${NETORIUM_BIN_DIR:-${HOME}/.local/bin}"

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

if command -v pipx >/dev/null 2>&1; then
  pipx install --force "$PACKAGE_SPEC"
else
  if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3.11+ or pipx is required for this installer." >&2
    echo "For no-Python machines, use the standalone release binary or Docker image." >&2
    echo "Release: https://github.com/${GITHUB_REPO}/releases/latest" >&2
    exit 1
  fi
  if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
    echo "Python 3.11+ is required for the venv fallback." >&2
    echo "For no-Python machines, use the standalone release binary or Docker image." >&2
    echo "Release: https://github.com/${GITHUB_REPO}/releases/latest" >&2
    exit 1
  fi

  python3 -m venv "$VENV_DIR"
  "$VENV_DIR/bin/python" -m pip install --upgrade pip
  "$VENV_DIR/bin/python" -m pip install --upgrade "$PACKAGE_SPEC"

  mkdir -p "$BIN_DIR"
  TARGET="$VENV_DIR/bin/netorium"
  LINK="$BIN_DIR/netorium"
  if [[ -L "$LINK" || ! -e "$LINK" ]]; then
    ln -sfn "$TARGET" "$LINK"
  else
    echo "Netorium installed in: $TARGET"
    echo "Existing command was not replaced: $LINK"
  fi
fi

echo "Netorium CLI installed."
echo "Run: netorium --help"
