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
GITHUB_API_BASE_URL="${NETORIUM_GITHUB_API_BASE_URL:-https://api.github.com}"
RELEASE_API_URL="${NETORIUM_RELEASE_API_URL:-${GITHUB_API_BASE_URL}/repos/${GITHUB_REPO}/releases/latest}"
STANDALONE_URL="${NETORIUM_STANDALONE_URL:-}"
STANDALONE_ASSET_NAME="${NETORIUM_STANDALONE_ASSET_NAME:-}"
UPDATE_MODE="${NETORIUM_UPDATE:-0}"

if [[ -t 1 ]]; then
  NETORIUM_TTY=1
else
  NETORIUM_TTY=0
fi

if [[ "${NETORIUM_NO_COLOR:-}" == "1" ]]; then
  NETORIUM_TTY=0
fi

NETORIUM_RESET=""
NETORIUM_BOLD=""
NETORIUM_DIM=""
NETORIUM_CYAN=""
NETORIUM_GREEN=""
NETORIUM_YELLOW=""
NETORIUM_MAGENTA=""
NETORIUM_RED=""

if [[ "$NETORIUM_TTY" == "1" ]]; then
  NETORIUM_RESET=$'\033[0m'
  NETORIUM_BOLD=$'\033[1m'
  NETORIUM_DIM=$'\033[2m'
  NETORIUM_CYAN=$'\033[36m'
  NETORIUM_GREEN=$'\033[32m'
  NETORIUM_YELLOW=$'\033[33m'
  NETORIUM_MAGENTA=$'\033[35m'
  NETORIUM_RED=$'\033[31m'
fi

netorium_print_banner() {
  if [[ "$NETORIUM_TTY" != "1" ]]; then
    return 0
  fi

  printf '%b\n' "${NETORIUM_CYAN}${NETORIUM_BOLD}"
  cat <<'EOF'
 _   _      _             _
| \ | | ___| |_ ___ _ __ (_) ___  _ __
|  \| |/ _ \ __/ _ \ '_ \| |/ _ \| '_ \
| |\  |  __/ ||  __/ | | | | (_) | | | |
|_| \_|\___|\__\___|_| |_|_|\___/|_| |_|
EOF
  printf '%b\n' "${NETORIUM_RESET}${NETORIUM_DIM}  Network access control CLI${NETORIUM_RESET}"
  printf '\n'
}

netorium_step() {
  printf '%b\n' "${NETORIUM_CYAN}▸${NETORIUM_RESET} $*"
}

netorium_ok() {
  printf '%b\n' "${NETORIUM_GREEN}✔${NETORIUM_RESET} $*"
}

netorium_warn() {
  printf '%b\n' "${NETORIUM_YELLOW}!${NETORIUM_RESET} $*" >&2
}

netorium_fail() {
  printf '%b\n' "${NETORIUM_RED}✖${NETORIUM_RESET} $*" >&2
}

netorium_spinner() {
  local message="$1"
  shift
  if [[ "$NETORIUM_TTY" != "1" ]]; then
    "$@"
    return $?
  fi

  local frames=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
  local frame_index=0
  local output_file
  output_file="$(mktemp)"
  "$@" >"$output_file" 2>&1 &
  local pid=$!

  printf '%b' "${NETORIUM_MAGENTA}${frames[$frame_index]}${NETORIUM_RESET} ${message}"
  while kill -0 "$pid" >/dev/null 2>&1; do
    frame_index=$(( (frame_index + 1) % ${#frames[@]} ))
    printf '\r%b' "${NETORIUM_MAGENTA}${frames[$frame_index]}${NETORIUM_RESET} ${message}"
    sleep 0.08
  done

  wait "$pid"
  local status=$?
  printf '\r\033[K'
  if [[ "$status" -eq 0 ]]; then
    netorium_ok "$message"
  else
    cat "$output_file" >&2
    netorium_fail "$message"
  fi
  rm -f "$output_file"
  return "$status"
}

netorium_download() {
  local url="$1"
  local destination="$2"
  local label="$3"

  if [[ "$NETORIUM_TTY" == "1" ]] && command -v curl >/dev/null 2>&1; then
    netorium_step "$label"
    if curl -fL --progress-bar -o "$destination" "$url"; then
      printf '\n'
      netorium_ok "$label"
      return 0
    fi
    printf '\n'
    netorium_fail "Could not download: $url"
    return 1
  fi

  netorium_spinner "$label" curl -fsSL -o "$destination" "$url"
}

detect_update_mode() {
  if [[ "$UPDATE_MODE" == "1" ]]; then
    return 0
  fi
  if command -v netorium >/dev/null 2>&1; then
    UPDATE_MODE=1
  fi
}

get_asset_arch() {
  case "$(uname -m)" in
    x86_64|amd64) echo "x64" ;;
    aarch64|arm64) echo "arm64" ;;
    *) echo "x64" ;;
  esac
}

get_standalone_asset_names() {
  local arch
  arch="$(get_asset_arch)"
  local names=()
  if [[ -n "$STANDALONE_ASSET_NAME" ]]; then
    names+=("$STANDALONE_ASSET_NAME")
  fi
  names+=("netorium-linux-${arch}")
  names+=("netorium-linux-x64")
  names+=("netorium")
  printf '%s\n' "${names[@]}"
}

resolve_standalone_download_url() {
  if [[ -n "$STANDALONE_URL" ]]; then
    echo "$STANDALONE_URL"
    return 0
  fi

  if [[ "$GITHUB_REPO" == "OWNER/REPO" ]]; then
    netorium_fail "Netorium GitHub repository is not configured."
    netorium_warn "Set NETORIUM_GITHUB_REPO=owner/repo or NETORIUM_STANDALONE_URL."
    return 1
  fi

  local asset_name
  while IFS= read -r asset_name; do
    local candidate="https://github.com/${GITHUB_REPO}/releases/latest/download/${asset_name}"
    if curl -fsI "$candidate" >/dev/null 2>&1; then
      echo "$candidate"
      return 0
    fi
  done < <(get_standalone_asset_names)

  netorium_fail "Could not find a Linux standalone release asset."
  netorium_warn "Release page: https://github.com/${GITHUB_REPO}/releases/latest"
  return 1
}

install_standalone_release() {
  local download_url
  download_url="$(resolve_standalone_download_url)" || return 1

  mkdir -p "$BIN_DIR"
  local target="$BIN_DIR/netorium"
  local temp="${target}.download"

  netorium_download "$download_url" "$temp" "Downloading Netorium CLI"
  chmod +x "$temp"
  mv -f "$temp" "$target"

  if ! "$target" version >/dev/null 2>&1; then
    netorium_fail "Downloaded Netorium binary failed verification."
    return 1
  fi

  local installed_version
  installed_version="$("$target" version 2>/dev/null || true)"
  netorium_ok "Standalone CLI installed: $target"
  if [[ -n "$installed_version" ]]; then
    netorium_ok "$installed_version"
  fi
  if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    netorium_warn "Add this directory to PATH if needed: $BIN_DIR"
  fi
}

resolve_package_spec() {
  if [[ -n "$PACKAGE_SPEC" ]]; then
    return 0
  fi

  case "$INSTALL_SOURCE" in
    github)
      if [[ "$GITHUB_REPO" == "OWNER/REPO" ]]; then
        netorium_fail "Netorium GitHub repository is not configured."
        netorium_warn "Set NETORIUM_GITHUB_REPO=owner/repo or NETORIUM_PACKAGE_SPEC."
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
      netorium_fail "Unsupported NETORIUM_INSTALL_SOURCE: $INSTALL_SOURCE"
      netorium_warn "Use github, pypi, local, or set NETORIUM_PACKAGE_SPEC directly."
      exit 1
      ;;
  esac
}

install_with_pipx() {
  netorium_spinner "Installing with pipx" pipx install --force "$PACKAGE_SPEC"
}

install_with_venv() {
  if ! command -v python3 >/dev/null 2>&1; then
    return 1
  fi
  if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
    return 1
  fi

  netorium_spinner "Creating virtual environment" python3 -m venv "$VENV_DIR"
  netorium_spinner "Upgrading pip" "$VENV_DIR/bin/python" -m pip install --upgrade pip
  netorium_spinner "Installing Netorium package" "$VENV_DIR/bin/python" -m pip install --upgrade "$PACKAGE_SPEC"

  mkdir -p "$BIN_DIR"
  local target="$VENV_DIR/bin/netorium"
  local link="$BIN_DIR/netorium"
  if [[ -L "$link" || ! -e "$link" ]]; then
    ln -sfn "$target" "$link"
    netorium_ok "Linked command: $link -> $target"
  else
    netorium_ok "Netorium installed in: $target"
    netorium_warn "Existing command was not replaced: $link"
  fi
  return 0
}

main() {
  detect_update_mode
  netorium_print_banner

  if [[ "$UPDATE_MODE" == "1" ]]; then
    netorium_step "Updating Netorium CLI"
  else
    netorium_step "Installing Netorium CLI"
  fi

  resolve_package_spec

  if command -v pipx >/dev/null 2>&1; then
    install_with_pipx
  elif install_with_venv; then
    :
  else
    netorium_warn "Python 3.11+ or pipx was not found. Switching to standalone release."
    install_standalone_release
  fi

  if command -v netorium >/dev/null 2>&1; then
    local version_line
    version_line="$(netorium version 2>/dev/null || true)"
    if [[ -n "$version_line" ]]; then
      netorium_ok "$version_line"
    fi
  fi

  printf '\n'
  if [[ "$UPDATE_MODE" == "1" ]]; then
    netorium_ok "Netorium CLI updated."
  else
    netorium_ok "Netorium CLI installed."
  fi
  netorium_step "Run: ${NETORIUM_BOLD}netorium --help${NETORIUM_RESET}"
}

main "$@"
