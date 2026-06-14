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
