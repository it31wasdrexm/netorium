# Commands

## Base

```bash
netorium
netorium --help
netorium version
netorium doctor
netorium uninstall
netorium docs
netorium docs install
```

Running `netorium` without arguments starts interactive mode. Inside it, use the
same commands without the `netorium` prefix:

```text
netorium> version
netorium> config path
netorium> exit
```

## Uninstall

```bash
netorium uninstall
netorium uninstall --yes
netorium uninstall --yes --remove-data
```

`netorium uninstall` is a dry-run by default. Use `--yes` to remove the installed
package. Add `--remove-data` only when you also want to remove Netorium user
configuration, local data, and cache directories.

## Configuration

```bash
netorium config path
netorium config init
netorium config show
netorium config validate
```

## Updates

```bash
netorium update check
netorium update show
netorium update install
```

Update commands check the configured GitHub release or PyPI package and print safe
manual install commands. They do not run package-manager commands automatically.
`netorium update show` and `netorium update install` also print the GitHub release
page, standalone binary names, Docker commands, and a recommended command for the
current operating system.

When `check_on_start = true` in the config, interactive mode shows a soft update
notice at startup if a newer release is available.

## Controller

```bash
netorium controller init
netorium controller status
netorium controller start --host 0.0.0.0 --port 8765
netorium controller token create --zone accounting --ttl 24h
```

The controller is a local LAN process for the main administrator PC. It stores
MVP state in SQLite, prints an enrollment URL for office agents, and creates
one-time enrollment tokens. Raw enrollment tokens are shown only once; the local
database stores their hashes.

## Deployment

```bash
netorium deploy instructions
netorium deploy token create --zone accounting --ttl 24h
netorium deploy script windows --output install-agent.ps1
netorium deploy script linux --output install-agent.sh
```

Deployment commands export copy-paste agent install/enroll commands for the
local controller URL. Token creation is shared with the controller token store:
raw tokens are shown once, while SQLite stores only token hashes.

## Endpoint Agent

```bash
netorium-agent --help
netorium-agent enroll --controller http://192.168.1.10:8765 --token TOKEN
netorium-agent status
netorium-agent run
netorium-agent service install
netorium-agent service start
netorium-agent service stop
netorium-agent update check
```

The agent enrolls with the local controller, stores endpoint state in the user's
Netorium config directory, and never prints enrollment or device tokens. The
foreground `run` command sends a heartbeat to the controller and receives the
current command queue. Endpoint firewall application and rollback are the next
deployment phase.

## Zones

```bash
netorium zone add accounting --floor 3 --department "Accounting"
netorium zone list
netorium zone show accounting
netorium zone delete accounting
```

Zone changes are stored in SQLite and write audit log entries.

## Devices

```bash
netorium device add 192.168.1.25 --zone accounting --hostname pc-acc-01
netorium device list
netorium device show 192.168.1.25
netorium device move 192.168.1.25 --zone reception
netorium device delete 192.168.1.25
```

Device IP addresses are validated before storage. Device changes are linked to
zones and write audit log entries.

## Firewall

```bash
netorium firewall status
netorium firewall block 192.168.1.25 --reason "Policy violation" --dry-run
netorium firewall unblock 192.168.1.25 --reason "Access restored" --dry-run
```

Firewall commands are safe by default and run as dry-run unless `--real --yes` is
explicitly requested. Real firewall changes are Windows-only and not enabled in
this MVP checkpoint yet.

## PRTG

```bash
netorium prtg test
```

The PRTG test command checks the configured API endpoint and credentials. It does
not print the configured passhash.

## Active Directory

```bash
netorium ad test
```

The AD test command checks the configured LDAP bind. It does not print the
configured bind password.

## Telegram

```bash
netorium telegram test
```

The Telegram test command checks the configured bot token through Telegram
`getMe`. It does not print the bot token or chat id.

## Audit

```bash
netorium audit list
netorium audit list --limit 20
```

Audit output is local and read-only from the CLI.

## Planned MVP Areas

```bash
netorium schedule list
```

Dangerous commands must keep `--dry-run`, require a reason, and write audit logs.
