# Installation

## No-Python Options

Use GitHub Releases when the target PC should not have Python installed.

Release page:

```text
https://github.com/it31wasdrexm/netorium/releases/latest
```

Download the matching standalone asset:

```text
netorium-windows-x64.exe
netorium-linux-x64
netorium-macos-x64
netorium-macos-arm64
```

Linux and macOS need the executable bit after download:

```bash
chmod +x ./netorium-linux-x64
./netorium-linux-x64 --help
```

On Windows, download `netorium-windows-x64.exe` and run:

```powershell
.\netorium-windows-x64.exe --help
```

## Local Standalone Build

From the repository root:

```bash
scripts/build-standalone.sh
```

This creates `.venv-release`, installs release dependencies inside that venv,
and copies the native binary to `release-assets/`. It does not require the
exact `python3.11` command; it accepts any local Python 3.11+ command such as
`python3` or `python3.14`.

If you build manually, create and activate a venv before running pip:

```bash
python3 -m venv .venv-release
source .venv-release/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[release]"
python -m PyInstaller --noconfirm --clean packaging/netorium.spec
```

## Windows EXE on Windows

Build the Windows standalone executable on Windows, not on Linux. PyInstaller
builds for the current OS, so native Linux Python cannot produce
`netorium-windows-x64.exe`.

In Windows PowerShell from the repository root:

```powershell
.\scripts\build-windows.ps1
```

The helper copies the result to:

```text
release-assets/netorium-windows-x64.exe
```

## GitHub Install

Linux / macOS:

```bash
curl -fsSL https://raw.githubusercontent.com/it31wasdrexm/netorium/main/install.sh | bash
```

To install from another fork or repository:

```bash
curl -fsSL https://raw.githubusercontent.com/it31wasdrexm/netorium/main/install.sh \
  | NETORIUM_GITHUB_REPO=OWNER/REPO bash
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/it31wasdrexm/netorium/main/install.ps1 | iex
```

To install from another fork or repository:

```powershell
$env:NETORIUM_GITHUB_REPO = "OWNER/REPO"
irm https://raw.githubusercontent.com/it31wasdrexm/netorium/main/install.ps1 | iex
```

## PyPI Install

After the package is published to PyPI:

```bash
curl -fsSL https://raw.githubusercontent.com/it31wasdrexm/netorium/main/install.sh | NETORIUM_INSTALL_SOURCE=pypi bash
```

```powershell
$env:NETORIUM_INSTALL_SOURCE = "pypi"
irm https://raw.githubusercontent.com/it31wasdrexm/netorium/main/install.ps1 | iex
```

## Windows Installer Behavior

The Windows installer uses `pipx` when it is available. If `pipx` is not
installed, it looks for Python 3.11+ through `py -3`, `python`, then `python3`
and installs Netorium into a dedicated user virtual environment.

## Docker

Docker does not require Python on the host PC.

Run the published image after the release workflow publishes it:

```bash
docker run --rm -it ghcr.io/it31wasdrexm/netorium:latest --help
```

Build locally from a source checkout:

```bash
docker build -t netorium-cli .
docker run --rm -it netorium-cli --help
```

Mount config and data volumes for persistent local state:

```bash
docker run --rm -it \
  -v netorium-config:/root/.config/netorium \
  -v netorium-data:/root/.local/share/netorium \
  ghcr.io/it31wasdrexm/netorium:latest config path
```

Docker is suitable for CLI checks, docs, config, inventory, integrations, and
dry-run workflows. It cannot directly manage the host Windows Firewall; use a
native Windows executable, future controller/agent flow, or supported Windows
remote management for real endpoint firewall changes.

## Local Checkout

From the repository root:

```bash
python -m pip install -e .
netorium --help
```

## Verify

```bash
netorium --help
netorium version
netorium config init
netorium doctor
netorium update show
```
