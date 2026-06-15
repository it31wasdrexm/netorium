#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

VENV_DIR="${NETORIUM_RELEASE_VENV:-.venv-release}"
ASSET_DIR="${NETORIUM_RELEASE_ASSET_DIR:-release-assets}"

find_python() {
  if [[ -n "${NETORIUM_PYTHON:-}" ]]; then
    if command -v "$NETORIUM_PYTHON" >/dev/null 2>&1; then
      printf '%s\n' "$NETORIUM_PYTHON"
      return 0
    fi
    echo "Configured NETORIUM_PYTHON was not found: $NETORIUM_PYTHON" >&2
    return 1
  fi

  local candidate
  for candidate in python3 python3.14 python3.13 python3.12 python3.11 python; do
    if command -v "$candidate" >/dev/null 2>&1 \
      && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  return 1
}

asset_arch() {
  case "$(uname -m)" in
    x86_64 | amd64) printf 'x64' ;;
    arm64 | aarch64) printf 'arm64' ;;
    *) uname -m ;;
  esac
}

python_bin="$(find_python)" || {
  echo "Python 3.11+ was not found." >&2
  echo "Install Python 3.11+ or set NETORIUM_PYTHON=/path/to/python." >&2
  exit 1
}

echo "Using Python: $("$python_bin" -c 'import sys; print(sys.executable + " " + sys.version.split()[0])')"

if ! "$python_bin" -m venv "$VENV_DIR"; then
  echo "Could not create $VENV_DIR." >&2
  echo "On Debian/Ubuntu, install the venv package for the selected Python, such as python3-full." >&2
  exit 1
fi

VENV_PYTHON="$VENV_DIR/bin/python"
"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -e ".[release]"
"$VENV_PYTHON" -m PyInstaller --noconfirm --clean packaging/netorium.spec

mkdir -p "$ASSET_DIR"

case "$(uname -s)" in
  Linux)
    source_path="dist/netorium"
    asset_name="netorium-linux-$(asset_arch)"
    ;;
  Darwin)
    source_path="dist/netorium"
    asset_name="netorium-macos-$(asset_arch)"
    ;;
  *)
    echo "Unsupported native build host: $(uname -s)." >&2
    echo "Use GitHub Actions or a matching OS machine." >&2
    echo "For Windows, run scripts/build-windows.ps1 on Windows PowerShell." >&2
    exit 1
    ;;
esac

if [[ ! -f "$source_path" ]]; then
  echo "Expected build output was not created: $source_path" >&2
  exit 1
fi

cp "$source_path" "$ASSET_DIR/$asset_name"
echo "Built: $ASSET_DIR/$asset_name"
