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
netorium uninstall --dry-run
netorium uninstall --dry-run --remove-data
netorium uninstall --yes
netorium uninstall --yes --remove-data
```

`netorium uninstall` is guided by default. It first asks whether to remove the
installed Netorium command, then asks whether to remove Netorium user
configuration, local data, database, and cache directories. Use `--dry-run` to
preview the plan without deleting anything. Use `--yes` for automation, and add
`--remove-data` only when automation should also remove local Netorium data.

## Configuration

```bash
netorium config path
netorium config init
netorium config show
netorium config validate
netorium config backup netorium_backup.zip
netorium config backup /path/to/backup/directory
```

The `backup` subcommand creates a ZIP archive containing the database and config
files. Pass a filename ending in `.zip` or a directory path as the destination.

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
netorium controller install-service
netorium controller install-service --system
netorium controller uninstall-service
netorium controller token create --zone accounting --ttl 24h
netorium controller agent list
netorium controller agent command firewall --agent-id AGENT_ID --action block --ip 192.168.1.25 --reason "Policy test"
netorium controller agent command firewall --agent-id AGENT_ID --action block --ip 192.168.1.25 --reason "Policy test" --real
netorium controller agent command site --agent-id AGENT_ID --action block --domain youtube.com --reason "Class policy"
netorium controller agent command site --agent-id AGENT_ID --action block --domain youtube.com --reason "Class policy" --real
netorium controller agent command app --agent-id AGENT_ID --action block --executable dota2.exe --reason "No game traffic"
netorium controller agent command binary --agent-id AGENT_ID --action block --executable cs1.6.exe --reason "No game traffic"
netorium controller agent command binary --agent-id AGENT_ID --action block --executable C:\Games\cs1.6.exe --reason "No game traffic" --real
netorium controller agent command speed --agent-id AGENT_ID --download-kbps 2048 --upload-kbps 512 --reason "Temporary limit"
netorium controller agent command speed --agent-id AGENT_ID --upload-kbps 512 --reason "Temporary upload limit" --real
netorium controller agent command speed --agent-id AGENT_ID --clear --reason "Limit removed"
netorium controller agent command list --agent-id AGENT_ID
```

The controller is a local LAN process for the main administrator PC. It stores
MVP state in SQLite, prints an enrollment URL for office agents, and creates
one-time enrollment tokens. Raw enrollment tokens are shown only once; the local
database stores their hashes. Controller agent commands are queued in SQLite and
are signed before delivery. They are dry-run by default; passing `--real` queues
a real Windows endpoint command for the enrolled agent. Supported endpoint
payloads are IP firewall actions, website domain block/unblock through the
Windows hosts file, application/binary network block/unblock through Windows
Firewall program rules, and per-agent speed-limit set/clear through Windows QoS.
Real endpoint commands require the agent to run on Windows with administrator
rights. Windows QoS throttles outbound traffic; reliable download limiting needs
a router, gateway, or future packet-filter adapter.

`controller install-service` registers a background service on Linux (systemd),
Windows (Task Scheduler or NSSM), or macOS (launchd). On Linux, the default user
service works without root; pass `--system` to install a system-wide unit.
Netorium re-execs under `sudo` with `python -m netorium` and the correct
`PYTHONPATH` for pip, pipx, and editable installs. The system unit runs as the
installing user account.
Windows, run PowerShell or Windows Terminal as Administrator before calling
`netorium controller install-service`; remove an old service first with
`netorium controller uninstall-service` if Windows reports that it already
exists.

## Policy Shortcuts

Shorter commands for everyday endpoint blocking. Target one agent by ID,
hostname, or every enrolled agent with `all`.

```bash
netorium policy agents
netorium policy list
netorium policy site AGENT_OR_ALL youtube.com --reason "Class policy"
netorium policy site all youtube.com --reason "Class policy" --real
netorium policy game AGENT_OR_ALL dota2.exe --reason "No game traffic"
netorium policy game all cs1.6.exe --reason "No game traffic" --real
netorium policy app AGENT_OR_ALL "C:\Games\cs1.6.exe" --reason "No game traffic" --real
netorium policy speed AGENT_OR_ALL --reason "Temporary limit" --down 2048 --up 512 --real
netorium policy clear-speed all --reason "Limit removed" --real
```

`policy game` is an alias for `policy app`. Dry-run is the default; add `--real`
to queue a real Windows endpoint command. Add `--unblock` to remove a site or
application block.

See `TESTING_RU.md` in the repository root for a full copy-paste testing flow.

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
current command queue. It verifies controller signatures, can process dry-run
endpoint firewall, website, application, and speed-limit commands, can apply
real Windows endpoint firewall/hosts/QoS commands when queued with `--real`, and
reports completed or failed command results back to the controller. Rollback is
currently handled through explicit unblock/clear commands.

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
netorium telegram start
netorium telegram start --token BOT_TOKEN
```

`netorium telegram start` runs the Telegram bot in the foreground, listening for
admin commands and monitoring traffic anomalies. The bot supports commands like
`/status`, `/agents`, `/traffic`, `/block_site`, `/limit_speed`, and more.
Press Ctrl+C to stop the bot.

## Audit

```bash
netorium audit list
netorium audit list --limit 20
```

Audit output is local and read-only from the CLI.

## Reports

```bash
netorium report traffic
netorium report traffic --threshold 500
netorium report anomalies
netorium report anomalies --threshold 500
netorium report export --format csv --output traffic.csv
netorium report export --format json --output traffic.json
```

Report commands show real-time traffic usage and anomaly detection for all
enrolled devices. The `--threshold` option sets the anomaly threshold in
megabytes (default: 1000 MB). Export commands save reports in CSV or JSON format.

## Planned MVP Areas

```bash
netorium schedule list
```

Dangerous commands must keep `--dry-run`, require a reason, and write audit logs.
