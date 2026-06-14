# Installation

## GitHub Install

Linux / macOS:

```bash
curl -fsSL https://github.com/it31wasdrexm/netorium/raw/main/install.sh | bash
```

To install from another fork or repository:

```bash
curl -fsSL https://github.com/it31wasdrexm/netorium/raw/main/install.sh \
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
curl -fsSL https://github.com/it31wasdrexm/netorium/raw/main/install.sh | NETORIUM_INSTALL_SOURCE=pypi bash
```

```powershell
$env:NETORIUM_INSTALL_SOURCE = "pypi"
irm https://raw.githubusercontent.com/it31wasdrexm/netorium/main/install.ps1 | iex
```

## Windows Installer Behavior

The Windows installer uses `pipx` when it is available. If `pipx` is not
installed, it looks for Python 3.11+ through `py -3`, `python`, then `python3`,
and installs Netorium with `pip --user`.

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
```
