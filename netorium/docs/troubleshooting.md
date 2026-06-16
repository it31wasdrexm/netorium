# Troubleshooting

## Config File Not Found

Run:

```bash
netorium config init
```

Then validate:

```bash
netorium config validate
```

## Secrets in Output

`netorium config show` masks passwords, tokens, passhashes, and Telegram chat ids.
If a new secret-like setting is added, update the masking rules before exposing it.

## Unsupported Firewall Platform

Real Windows Firewall changes are Windows-only. Linux and macOS workflows must use
dry-run behavior and show what would be applied.

## Update Release Not Found

`netorium update check` reads the latest GitHub release. If no release tag has
been published yet, use:

```bash
netorium update show
netorium docs install
```

These commands show the release page, installer commands, standalone binary names,
and Docker commands.

## Local Release Venv Fails

If `python3.11 -m venv .venv-release` fails with `command not found`, use the
Python command that exists on the machine:

```bash
python3 -m venv .venv-release
```

or:

```bash
python3.14 -m venv .venv-release
```

If `python -m pip install --upgrade pip` fails with an externally managed
environment error, the venv was not created or activated. Use:

```bash
scripts/build-standalone.sh
```

or activate the venv before running pip:

```bash
source .venv-release/bin/activate
python -m pip install --upgrade pip
```

## Windows EXE Build

PyInstaller does not cross-build a Windows executable from native Linux Python.
Build the Windows executable on Windows:

```powershell
.\scripts\build-windows.ps1
```

If Windows PowerShell prints that running scripts is disabled on this system,
allow local user scripts once, then run the same direct command again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force
.\scripts\build-windows.ps1
```

If the file was downloaded from the internet and is still blocked, unblock this
script once:

```powershell
Unblock-File .\scripts\build-windows.ps1
.\scripts\build-windows.ps1
```

The helper uses `.venv-release-win` by default so it does not mix files with a
Linux `.venv-release`. To override the release environment or temp directory:

```powershell
$env:NETORIUM_RELEASE_VENV = ".venv-release-custom"
$env:NETORIUM_RELEASE_TEMP_DIR = ".netorium-release-tmp"
.\scripts\build-windows.ps1
```

The expected release asset is:

```text
release-assets/netorium-windows-x64.exe
```

Python 3.11+ is required only on the Windows build machine. The generated
`netorium-windows-x64.exe` is the no-Python artifact for target Windows PCs.

## Netorium Command Not Recognized on Windows

A source checkout does not create a global `netorium` command by itself. If
`netorium` is not recognized, install it or run it through a Windows venv from
the repository root:

```powershell
py -3 -m venv .venv-win
.\.venv-win\Scripts\python.exe -m pip install --upgrade pip
.\.venv-win\Scripts\python.exe -m pip install -e .
.\.venv-win\Scripts\netorium.exe --help
```

Do not reuse a `.venv` copied from Linux on Windows. Linux virtual environments
have `bin/` launchers, while Windows needs `Scripts\*.exe` launchers.

If a GitHub Release asset is named only `netorium`, it was uploaded from
`dist/netorium` directly. Upload the renamed file from `release-assets/`
instead.

## Docker Firewall Limitation

Docker is useful when the host PC should not have Python installed, but a
container cannot directly manage the host Windows Firewall. Use Docker for docs,
config, inventory, integration tests, and dry-run workflows. Use a native Windows
binary or the future controller/agent model for real endpoint firewall changes.
