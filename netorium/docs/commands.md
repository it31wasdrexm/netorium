# Commands

## Base

```bash
netorium --help
netorium version
netorium doctor
netorium docs
```

## Configuration

```bash
netorium config path
netorium config init
netorium config show
netorium config validate
```

## Planned MVP Areas

```bash
netorium update check
netorium zone list
netorium device list
netorium firewall status
```

Dangerous commands must keep `--dry-run`, require a reason, and write audit logs.
