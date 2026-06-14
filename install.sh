#!/usr/bin/env bash
set -euo pipefail

PACKAGE_NAME="${NETORIUM_PACKAGE_NAME:-netorium-cli}"
INSTALL_SOURCE="${NETORIUM_INSTALL_SOURCE:-github}"
GITHUB_REPO="${NETORIUM_GITHUB_REPO:-OWNER/REPO}"
GITHUB_REF="${NETORIUM_GITHUB_REF:-main}"
GITHUB_REF_KIND="${NETORIUM_GITHUB_REF_KIND:-heads}"
PACKAGE_SPEC="${NETORIUM_PACKAGE_SPEC:-}"

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
  python3 -m pip install --user --upgrade "$PACKAGE_SPEC"
fi

echo "Netorium CLI installed."
echo "Run: netorium --help"
