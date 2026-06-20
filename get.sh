#!/usr/bin/env bash
set -euo pipefail

GITHUB_REPO="${NETORIUM_GITHUB_REPO:-it31wasdrexm/netorium}"
INSTALL_URL="${NETORIUM_INSTALL_URL:-https://raw.githubusercontent.com/${GITHUB_REPO}/main/install.sh}"

export NETORIUM_QUICK_INSTALL=1
exec bash <(curl -fsSL "$INSTALL_URL")
