#!/usr/bin/env bash
set -euo pipefail

GITHUB_REPO="${NETORIUM_GITHUB_REPO:-it31wasdrexm/netorium}"
RAW_BASE_URL="https://raw.githubusercontent.com/${GITHUB_REPO}/main"
INSTALL_URL="${NETORIUM_INSTALL_URL:-${RAW_BASE_URL}/get.sh}"

curl -fsSL "$INSTALL_URL" | bash

echo "Netorium Agent installed."
echo "Next:"
echo "  netorium-agent enroll --controller http://YOUR-CONTROLLER:8765 --token YOUR_TOKEN"
