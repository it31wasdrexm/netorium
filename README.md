<div align="center">

# N E T O R I U M

**Building-level network access control**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

</div>

Netorium lets you manage corporate networks by zones — *Accounting*, *Guests*, *3rd Floor* — instead of raw IP lists. One CLI, a central controller, real Windows Firewall policies on endpoints, and Telegram alerts when something looks off.

### Key capabilities

- **Smart zoning** — group devices by floor, department, or role
- **Endpoint policies** — block sites, apps, and games via Windows Firewall
- **Bandwidth shaping** — QoS limits per agent or zone
- **Traffic monitoring** — reports and anomaly alerts
- **Cross-platform** — controller on Linux, macOS, or Windows

### Download and install

**Windows (PowerShell)**

```powershell
irm https://raw.githubusercontent.com/it31wasdrexm/netorium/main/install.ps1 | iex
```

**Linux / macOS**

```bash
curl -fsSL https://raw.githubusercontent.com/it31wasdrexm/netorium/main/install.sh | bash
```

### Documentation

Full setup, commands, and deployment — **[NETORIUM_GUIDE.md](./NETORIUM_GUIDE.md)**
