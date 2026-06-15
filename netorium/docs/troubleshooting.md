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

The expected release asset is:

```text
release-assets/netorium-windows-x64.exe
```

If a GitHub Release asset is named only `netorium`, it was uploaded from
`dist/netorium` directly. Upload the renamed file from `release-assets/`
instead.

## Docker Firewall Limitation

Docker is useful when the host PC should not have Python installed, but a
container cannot directly manage the host Windows Firewall. Use Docker for docs,
config, inventory, integration tests, and dry-run workflows. Use a native Windows
binary or the future controller/agent model for real endpoint firewall changes.
