#!/usr/bin/env bash
set -euo pipefail

PACKAGE_NAME="netgate-cli"

if command -v pipx >/dev/null 2>&1; then
  pipx install "$PACKAGE_NAME"
else
  python3 -m pip install --user "$PACKAGE_NAME"
fi

echo "NetGate Agent installed."
echo "Next:"
echo "  netgate-agent enroll --controller https://YOUR-CONTROLLER:8765 --token YOUR_TOKEN"
