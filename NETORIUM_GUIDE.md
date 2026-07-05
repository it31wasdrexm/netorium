# Netorium Complete Guide

Netorium is a cross-platform CLI for building-level network access control. Instead of managing raw IP addresses, you work with zones, enrolled agents, and policy commands that apply real Windows Firewall rules on endpoints.

---

## Table of contents

1. [Architecture](#architecture)
2. [Installation](#installation)
3. [Configuration](#configuration)
4. [Deployment modes](#deployment-modes)
5. [Controller workflow](#controller-workflow)
6. [Endpoint agents](#endpoint-agents)
7. [Policies: sites, apps, speed](#policies-sites-apps-speed)
8. [Traffic monitoring and reports](#traffic-monitoring-and-reports)
9. [Telegram integration](#telegram-integration)
10. [Inventory: zones and devices](#inventory-zones-and-devices)
11. [Firewall (local)](#firewall-local)
12. [Uninstall](#uninstall)
13. [Troubleshooting](#troubleshooting)

---

## Architecture

```
┌─────────────────────┐         HTTP (LAN)         ┌──────────────────────┐
│  Admin workstation  │◄──────────────────────────►│  Netorium Controller │
│  netorium CLI       │   enroll / heartbeat       │  SQLite + HTTP API   │
└─────────────────────┘                            └──────────┬───────────┘
                                                              │
                         signed policy commands             │
                                                              ▼
                                                   ┌──────────────────────┐
                                                   │  Windows endpoint      │
                                                   │  netorium agent        │
                                                   │  Firewall / hosts / QoS│
                                                   └──────────────────────┘
```

**Controller** stores agents, enrollment tokens, queued commands, audit logs, and traffic samples.

**Agent** polls `/heartbeat`, verifies command signatures, applies policies locally, and reports results.

**CLI** is the operator interface for init, policies, reports, Telegram, and service management.

---

## Installation

### One-line install

Windows:

```powershell
irm https://raw.githubusercontent.com/it31wasdrexm/netorium/main/install.ps1 | iex
```

Linux / macOS:

```bash
curl -fsSL https://raw.githubusercontent.com/it31wasdrexm/netorium/main/install.sh | bash
```

### Python package

```bash
pipx install netorium-cli
# or
python -m pip install netorium-cli
```

### Paths after install

| Platform | Config | Data / binary |
|----------|--------|---------------|
| Windows | `%APPDATA%\Netorium\config.toml` | `%LOCALAPPDATA%\Netorium\` |
| Linux | `~/.config/netorium/config.toml` | `~/.local/share/netorium/` |
| macOS | `~/.config/netorium/config.toml` | `~/Library/Application Support/netorium/` |

---

## Configuration

Create and validate config:

```bash
netorium config init
netorium config show
netorium config validate
```

Example `config.toml` sections:

```toml
[app]
database_path = "~/.local/share/netorium/netorium.db"
timezone = "Asia/Almaty"
log_level = "INFO"

[telegram]
bot_token = "YOUR_BOT_TOKEN"
chat_id = "YOUR_CHAT_ID"

[monitoring]
traffic_anomaly_threshold_mb = 1000
traffic_check_interval_seconds = 60
traffic_window_minutes = 15
```

`[monitoring]` controls report thresholds and Telegram anomaly alerts.

---

## Deployment modes

### Standalone

Single machine, local SQLite, useful for inventory and testing. Real firewall changes apply only on the machine where you run `--real` commands.

### Controller (recommended)

One admin PC runs the controller and exposes it on the LAN:

```bash
netorium controller init
netorium controller install-service   # optional background service
netorium controller start --host 0.0.0.0 --port 8765
netorium controller status
```

### Managed endpoints

Install the agent on each Windows PC:

```bash
netorium agent enroll --controller http://192.168.1.10:8765 --token ENROLL_TOKEN
netorium agent service install
netorium agent status
```

Agents do not need the admin password stored locally; they authenticate with a device token issued at enrollment.

---

## Controller workflow

```bash
# Initialize and inspect
netorium controller init
netorium controller status

# Enrollment tokens
netorium controller token create --zone accounting --ttl 24h
netorium controller token list

# Agents
netorium controller agent list
netorium controller agent command list --agent-id AGENT_ID
```

Service management:

```bash
netorium controller install-service
netorium controller stop-service
netorium controller uninstall-service
```

---

## Endpoint agents

The agent loop sends heartbeats every few seconds. Each heartbeat may include cumulative network byte counters; the controller stores samples for reports and anomaly detection.

Agent service commands:

```bash
netorium agent service install
netorium agent service start
netorium agent service stop
netorium agent service uninstall
```

Manual run (debug):

```bash
netorium agent run-once
netorium agent run-loop
```

---

## Policies: sites, apps, speed

Short policy commands target one agent ID, hostname, or `all`:

### Block / unblock websites

Uses Windows hosts file entries and outbound firewall FQDN rules:

```bash
netorium policy site all youtube.com --reason "Work hours" --real
netorium policy unblock-site pc-acc-01 youtube.com --reason "Break" --real
```

Domains are normalized: `www.` variants and mobile subdomains are included automatically.

### Block / unblock applications

Matches executable name or full path via Windows Firewall program rules:

```bash
netorium policy game all dota2.exe --reason "No games" --real
netorium policy app pc-01 "C:\Games\cs1.6.exe" --reason "Policy" --real
netorium policy unblock-game all steam.exe --real
```

Aliases like `tg`, `dota`, `minecraft`, `discord` are recognized.

### Speed limits

```bash
netorium policy speed all --down 2048 --up 512 --reason "Guest cap" --real
netorium policy clear-speed all --real
```

**How speed limiting works on Windows**

- Netorium creates a persistent **NetQosPolicy** named `Netorium Endpoint Speed Limit`.
- Windows QoS throttles **outbound** traffic from the endpoint.
- `--up` (upload) is the reliable knob on Windows; `--down` is stored for reporting but full download shaping requires router/gateway QoS.

**Recommended layered approach**

| Layer | Tool | Best for |
|-------|------|----------|
| Endpoint upload | Netorium QoS | Per-user PC upload cap |
| Per-VLAN / SSID | Managed switch or Wi‑Fi controller | Office zones |
| Internet gateway | Router traffic shaping | Symmetric up/down limits |

---

## Traffic monitoring and reports

Agents send `bytes_sent` and `bytes_received` (cumulative since boot) with each heartbeat. The controller computes usage deltas over a sliding window.

```bash
netorium report traffic
netorium report traffic --threshold 500 --window 15
netorium report anomalies --threshold 1000
netorium report export --format csv --output traffic.csv
netorium report export --format json --output traffic.json
```

**Anomaly detection**

- Compares total bytes (up + down) in the configured window against `traffic_anomaly_threshold_mb`.
- Highlights heavy download/upload patterns (large file transfers, streaming, game patches).
- Telegram bot sends alerts automatically when `netorium telegram start` is running.

---

## Telegram integration

Setup:

1. Create a bot with [@BotFather](https://t.me/BotFather).
2. Put `bot_token` and your numeric `chat_id` in `config.toml`.
3. Run `netorium telegram start` on the controller machine.

Commands:

| Command | Example |
|---------|---------|
| Status | `/status` |
| List agents | `/agents` |
| Traffic summary | `/traffic` |
| Block site | `/block_site all youtube.com` |
| Unblock site | `/unblock_site pc-01 youtube.com` |
| Block app | `/block_game all dota2.exe` |
| Unblock app | `/unblock_game all dota2.exe` |
| Limit speed | `/limit_speed all 2048 512` |
| Clear speed | `/clear_speed all` |

Use `all` as the target to queue commands for every enrolled agent. Blocking and unblocking through Telegram uses the same controller queue as CLI policies — agents pick up commands on the next heartbeat.

---

## Inventory: zones and devices

```bash
netorium zone add accounting --floor 3 --department "Accounting"
netorium zone list
netorium device add 192.168.1.25 --zone accounting --hostname pc-acc-01
netorium device list
netorium device move 192.168.1.25 --zone reception
```

Zones are logical groups for inventory and future rule targeting; endpoint policies currently target agents directly.

---

## Firewall (local)

Local IP block preview and apply on the controller machine:

```bash
netorium firewall status
netorium firewall block 192.168.1.50 --reason "Test" --real --yes
netorium firewall unblock 192.168.1.50 --reason "Restore" --real --yes
```

For office-wide control, prefer controller agent commands or `netorium policy` with `--real`.

---

## Uninstall

Guided removal:

```bash
netorium uninstall
```

Non-interactive full removal:

```bash
netorium uninstall --yes --remove-data
```

Preview plan:

```bash
netorium uninstall --dry-run --remove-data
```

Windows uninstall behavior:

1. Stops and removes controller/agent services and scheduled tasks.
2. Schedules a **single hidden cleanup task** that waits for Netorium to exit.
3. Deletes `%LOCALAPPDATA%\Netorium`, `%APPDATA%\Netorium`, `%ProgramData%\Netorium`, and removes the user PATH entry for the launcher.
4. Retries deletion up to six times to handle locked files.

After uninstall, wait a few seconds and open a **new** terminal before checking whether `netorium` is still available.

---

## Troubleshooting

**Agent not receiving commands**

- Confirm `netorium controller agent list` shows recent `last_seen`.
- Check agent service: `netorium agent service` / Windows Services for `NetoriumAgent`.
- Verify firewall allows inbound TCP on the controller port.

**Site block not working**

- Agent must run elevated (service install handles this).
- DNS cache is flushed automatically; try `ipconfig /flushdns` if needed.
- Some apps use DoH/DoT and bypass hosts — block at gateway if required.

**Speed limit seems ineffective on download**

- Expected on Windows: QoS limits upload. Add router shaping for download.

**Telegram bot not alerting**

- Run `netorium telegram start` continuously (service or screen/tmux).
- Ensure agents are enrolled and sending heartbeats with traffic counters.
- Lower `traffic_anomaly_threshold_mb` in config for testing.

**Uninstall left files behind**

- Run PowerShell as Administrator: `netorium uninstall --yes --remove-data`
- Manually remove `%LOCALAPPDATA%\Netorium` and `%APPDATA%\Netorium` if needed.
- Remove `Netorium` from the user PATH in System Properties.

---

## Updates

```bash
netorium update check
netorium update install
```

---

## Further reading

- [netorium/docs/commands.md](./netorium/docs/commands.md)
- [netorium/docs/install.md](./netorium/docs/install.md)
- [netorium/docs/troubleshooting.md](./netorium/docs/troubleshooting.md)
- [netorium/docs/examples.md](./netorium/docs/examples.md)
