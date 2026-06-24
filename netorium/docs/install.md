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

If PowerShell blocks local scripts with an execution policy error, allow local
user scripts once, then run the same direct command again:

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

The helper uses `.venv-release-win` by default so a checkout that already has a
Linux `.venv-release` does not mix Linux and Windows virtual environment files.
To override the release environment or temp directory:

```powershell
$env:NETORIUM_RELEASE_VENV = ".venv-release-custom"
$env:NETORIUM_RELEASE_TEMP_DIR = ".netorium-release-tmp"
.\scripts\build-windows.ps1
```

The helper copies the result to:

```text
release-assets/netorium-windows-x64.exe
```

It also verifies the standalone executable by running `version`, installs the
same no-Python executable as the current user's `netorium` command, and checks
that command:

```powershell
.\scripts\build-windows.ps1
netorium version
```

This copies the executable to `%LOCALAPPDATA%\Netorium\bin\netorium.exe` and
adds that directory to the current user's `PATH`. Open a new PowerShell window
if the current terminal still cannot find `netorium`.

To build only the release asset without installing the `netorium` command:

```powershell
.\scripts\build-windows.ps1 -NoInstallUser
```

The build machine still needs Python 3.11+ to create the executable. The
resulting `netorium-windows-x64.exe` runs on the target Windows PC without
Python installed.

## GitHub Install

Short one-liners:

Linux / macOS:

```bash
curl -fsSL https://raw.githubusercontent.com/it31wasdrexm/netorium/main/get.sh | bash
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/it31wasdrexm/netorium/main/get.ps1 | iex
```

These short installers download the full installer, show a progress UI, detect
updates when `netorium` is already installed, and fall back to the standalone
release binary when Python 3.11+ or `pipx` is not available.

Full installer URLs still work:

```bash
curl -fsSL https://raw.githubusercontent.com/it31wasdrexm/netorium/main/install.sh | bash
```

```powershell
irm https://raw.githubusercontent.com/it31wasdrexm/netorium/main/install.ps1 | iex
```

To install from another fork or repository:

```bash
curl -fsSL https://raw.githubusercontent.com/it31wasdrexm/netorium/main/get.sh \
  | NETORIUM_GITHUB_REPO=OWNER/REPO bash
```

```powershell
$env:NETORIUM_GITHUB_REPO = "OWNER/REPO"
irm https://raw.githubusercontent.com/it31wasdrexm/netorium/main/get.ps1 | iex
```

## PyPI Install

After the package is published to PyPI:

```bash
curl -fsSL https://raw.githubusercontent.com/it31wasdrexm/netorium/main/get.sh | NETORIUM_INSTALL_SOURCE=pypi bash
```

```powershell
$env:NETORIUM_INSTALL_SOURCE = "pypi"
irm https://raw.githubusercontent.com/it31wasdrexm/netorium/main/get.ps1 | iex
```

## Windows Installer Behavior

The Windows installer uses `pipx` when it is available. If `pipx` is not
installed, it looks for Python 3.11+ through `py -3`, `python`, then `python3`
and installs Netorium into a dedicated user virtual environment.

If neither `pipx` nor Python 3.11+ is installed, the default GitHub installer
downloads the latest standalone executable from GitHub Releases. On Windows it
installs as:

```text
%LOCALAPPDATA%\Netorium\bin\netorium.exe
```

and adds that directory to the current user's `PATH`. The release may publish
the executable as `netorium-windows-x64.exe` or `netorium.exe`; the installer
accepts both names.

On Linux and macOS the installer downloads `netorium-linux-x64` or the matching
macOS asset into `~/.local/bin/netorium` when Python is unavailable.

## Controller Background Service

After initializing the local controller, install it as a background service so
it starts with the PC:

```bash
netorium controller init
netorium controller install-service
```

On Linux, the default user service works without root. Use `--system` for a
system-wide unit that survives logout. Netorium re-execs under `sudo` with
`python -m netorium` and the correct `PYTHONPATH` for pip, pipx, and editable
installs. The system unit runs as the installing user account.

If `controller install-service --system` fails with `No module named 'netorium'`,
reinstall Netorium with the GitHub installer or standalone binary, then run the
service install again.

On Windows, run PowerShell or Windows Terminal as Administrator before installing
the service. Netorium uses NSSM when it is available; otherwise it registers the
service with `sc.exe` and quotes the installed executable path, including the
default standalone installer path:

```text
%LOCALAPPDATA%\Netorium\bin\netorium.exe
```

If Windows reports that the service already exists, remove it first:

```bash
netorium controller uninstall-service
netorium controller install-service
```

After installation, verify access from another PC before enrolling agents:

```powershell
curl http://CONTROLLER_IP:8765/health
Test-NetConnection CONTROLLER_IP -Port 8765
```

If these checks fail from the second PC while they pass on the controller PC,
the enrollment token is not the problem. Check that both computers are on the
same LAN/VPN, that the Windows network profile and firewall allow inbound TCP
8765, and that router or guest Wi-Fi client isolation is disabled.

## Uninstall

Use the guided command for normal removal:

```bash
netorium uninstall
```

It asks whether to remove the installed Netorium command and then asks whether
to remove local config, database, and cache. Preview the plan without deleting
anything:

```bash
netorium uninstall --dry-run --remove-data
```

For automation:

```bash
netorium uninstall --yes --remove-data
```

On Windows standalone installs, Netorium schedules cleanup through a temporary
`.cmd` script after the CLI process exits. Wait a few seconds and open a new
terminal before checking that `%LOCALAPPDATA%\Netorium\bin\netorium.exe` and the
user `PATH` entry are gone.

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

## Agent Deployment Helpers

After initializing the local controller, print copy-paste install/enroll
commands for office PCs:

```bash
netorium controller init
netorium deploy instructions
netorium deploy token create --zone accounting --ttl 24h
```

Generate an agent deployment script:

```bash
netorium deploy script windows --output install-agent.ps1
netorium deploy script linux --output install-agent.sh
```

These helpers export the local controller URL and one-time enrollment tokens.
After installing on an endpoint, enroll the agent:

```bash
netorium-agent enroll --controller http://192.168.1.10:8765 --token TOKEN
netorium-agent status
netorium-agent run
```

The current agent stores endpoint state locally, does not print enrollment or
device tokens, and sends heartbeat checks to the controller. The controller can
queue signed dry-run endpoint commands, and `netorium-agent run` verifies the
signature before reporting the completed or failed result back to the controller:

```bash
netorium controller agent command firewall --agent-id AGENT_ID --action block --ip 192.168.1.25 --reason "Policy test"
netorium controller agent command site --agent-id AGENT_ID --action block --domain youtube.com --reason "Class policy"
netorium controller agent command app --agent-id AGENT_ID --action block --executable dota2.exe --reason "No game traffic"
netorium controller agent command speed --agent-id AGENT_ID --download-kbps 2048 --upload-kbps 512 --reason "Temporary limit"
netorium-agent run
netorium controller agent command list --agent-id AGENT_ID
```

Current dry-run command types cover endpoint firewall IP actions, site
block/unblock by domain, application/binary network block/unblock, and
per-agent speed limit set/clear. Real endpoint firewall/application/QoS
application and rollback are the next deployment phase.

## Local Checkout

From the repository root:

```bash
python -m pip install -e .
netorium --help
```

On Windows, create a Windows virtual environment first if `netorium` is not
recognized or the cloned Linux `.venv` is present:

```powershell
cd C:\Users\roman\desktop\netorium
py -3 -m venv .venv-win
.\.venv-win\Scripts\python.exe -m pip install --upgrade pip
.\.venv-win\Scripts\python.exe -m pip install -e .
.\.venv-win\Scripts\netorium.exe --help
```

To make `netorium` available from any new terminal, install through the Windows
installer, run `.\scripts\build-windows.ps1`, or add the chosen Scripts/bin
directory to `PATH`.

## Verify

```bash
netorium --help
netorium version
netorium config init
netorium doctor
netorium update show
```
