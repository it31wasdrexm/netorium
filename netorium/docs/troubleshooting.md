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

## Docker Firewall Limitation

Docker is useful when the host PC should not have Python installed, but a
container cannot directly manage the host Windows Firewall. Use Docker for docs,
config, inventory, integration tests, and dry-run workflows. Use a native Windows
binary or the future controller/agent model for real endpoint firewall changes.
