# Examples

Start interactive mode and run commands without repeating the `netorium` prefix:

```text
netorium
netorium> version
netorium> config path
netorium> exit
```

Create and validate a local configuration file:

```bash
netorium config init
netorium config validate
```

Print the active config path:

```bash
netorium config path
```

Inspect configuration without exposing secrets:

```bash
netorium config show
```

Check local CLI health:

```bash
netorium doctor --verbose
```

Preview uninstall and then remove Netorium completely:

```bash
netorium uninstall
netorium uninstall --yes --remove-data
```

Check for a newer release:

```bash
netorium update check
netorium update show
```

Show download options for a PC without Python:

```bash
netorium update install
```

Initialize the local office controller and create an enrollment token:

```bash
netorium controller init
netorium controller status
netorium controller token create --zone accounting --ttl 24h
```

Export copy-paste agent deployment commands:

```bash
netorium deploy instructions
netorium deploy token create --zone accounting --ttl 24h
netorium deploy script windows --output install-agent.ps1
```

Enroll and inspect an endpoint agent:

```bash
netorium-agent enroll --controller http://192.168.1.10:8765 --token TOKEN
netorium-agent status
netorium-agent run
```

Queue a dry-run firewall command for an enrolled endpoint and inspect the
result after the agent runs:

```bash
netorium controller agent list
netorium controller agent command firewall --agent-id AGENT_ID --action block --ip 192.168.1.25 --reason "Policy test"
netorium-agent run
netorium controller agent command list --agent-id AGENT_ID
```

Run Netorium through Docker:

```bash
docker run --rm -it ghcr.io/it31wasdrexm/netorium:latest --help
```

Create the first zone and inspect the audit log:

```bash
netorium zone add accounting --floor 3 --department "Accounting"
netorium zone list
netorium audit list
```

Add and move a device between zones:

```bash
netorium zone add reception --floor 1 --department "Reception"
netorium device add 192.168.1.25 --zone accounting --hostname pc-acc-01
netorium device move 192.168.1.25 --zone reception
netorium device show 192.168.1.25
```

Preview a firewall block without changing local firewall rules:

```bash
netorium firewall block 192.168.1.25 --reason "Policy violation" --dry-run
netorium audit list
```

Test PRTG API settings after replacing the placeholder credentials:

```bash
netorium prtg test
```

Test Active Directory bind settings after replacing the placeholder credentials:

```bash
netorium ad test
```

Test Telegram bot settings after replacing the placeholder credentials:

```bash
netorium telegram test
```

Show installation instructions:

```bash
netorium docs install
```
