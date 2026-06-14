# Installation

## GitHub Install

Replace `OWNER/REPO` with the GitHub repository path.

```bash
curl -fsSL https://raw.githubusercontent.com/OWNER/REPO/main/install.sh \
  | NETORIUM_GITHUB_REPO=OWNER/REPO bash
```

Windows PowerShell:

```powershell
$env:NETORIUM_GITHUB_REPO = "OWNER/REPO"
irm https://raw.githubusercontent.com/OWNER/REPO/main/install.ps1 | iex
```

## PyPI Install

After the package is published to PyPI:

```bash
curl -fsSL https://raw.githubusercontent.com/OWNER/REPO/main/install.sh \
  | NETORIUM_INSTALL_SOURCE=pypi bash
```

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
