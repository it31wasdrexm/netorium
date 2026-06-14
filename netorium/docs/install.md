# Installation

## GitHub Install

Linux / macOS:

```bash
curl -fsSL https://github.com/it31wasdrexm/netorium/raw/main/install.sh | bash
```

To install from another fork or repository:

```bash
curl -fsSL https://github.com/it31wasdrexm/netorium/raw/main/install.sh | NETORIUM_GITHUB_REPO=OWNER/REPO bash
```

Windows PowerShell:

```powershell
irm https://github.com/it31wasdrexm/netorium/raw/main/install.ps1 | iex
```

## PyPI Install

After the package is published to PyPI:

```bash
curl -fsSL https://github.com/it31wasdrexm/netorium/raw/main/install.sh | NETORIUM_INSTALL_SOURCE=pypi bash
```

```bash
curl -fsSL https://github.com/it31wasdrexm/netorium/raw/main/install.sh \
  | NETORIUM_INSTALL_SOURCE=pypi bash
```

## Local Checkout

From the repository root:

```bash
python -m pip install -e .
netorium --help
```

## Linux / macOS Installer Behavior

The installer uses `pipx` when it is available. If `pipx` is not installed, it
creates a dedicated virtual environment at `~/.local/share/netorium/venv`,
installs Netorium there, and links `netorium` into `~/.local/bin`.

## Verify

```bash
netorium --help
netorium version
netorium config init
netorium doctor
```
