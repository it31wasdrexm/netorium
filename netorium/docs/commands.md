# Commands

## Base

```bash
netorium --help
netorium version
netorium doctor
netorium docs
netorium docs install
```

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
