#!/usr/bin/env bash
set -euo pipefail

PACKAGE_NAME="netgate-cli"

if command -v pipx >/dev/null 2>&1; then
  pipx install "$PACKAGE_NAME"
else
  python3 -m pip install --user "$PACKAGE_NAME"
fi

echo "NetGate CLI installed."
echo "Run: netgate --help"
