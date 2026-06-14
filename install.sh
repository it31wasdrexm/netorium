#!/usr/bin/env bash
set -euo pipefail

PACKAGE_NAME="netorium-cli"

if command -v pipx >/dev/null 2>&1; then
  pipx install "$PACKAGE_NAME"
else
  python3 -m pip install --user "$PACKAGE_NAME"
fi

echo "Netorium CLI installed."
echo "Run: netorium --help"
