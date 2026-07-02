<div align="center">

# 📘 Netorium Complete Guide

**The Ultimate Building-level Network Access Control CLI**

</div>

---

## 📖 Introduction

**Netorium CLI** is a cross-platform, open-source Python tool designed to simplify network access control. Instead of dealing with individual IPs and scattered firewall rules, Netorium lets you group devices by logical zones such as `3rd floor`, `accounting`, `server room`, `guests`, or `classroom`.

### What it can do:
- **Device & Zone Management:** Group and track devices by real-world departments.
- **Identity Sync:** Pull user data directly from Active Directory.
- **Monitoring & Traffic:** Integrated with PRTG API for traffic insights and status checks.
- **Endpoint Control:** Real Windows Firewall blocking and unblocking.
- **Rules & Scheduling:** Enforce access control during specific hours automatically.
- **Alerts:** Get Telegram notifications for network anomalies.
- **Automated Reports:** Generate comprehensive CSV/HTML reports of network usage and status.

---

## 🏗️ Architecture & Deployment

Netorium supports flexible deployment modes to fit any infrastructure:

### 1. Standalone Mode
Perfect for MVPs, development, and inventory. A single administrator computer runs the CLI and local SQLite database.
*Note: Real Windows Firewall changes apply only to the local machine.*

### 2. Controller Mode (Recommended)
Set up a main administrator PC as the central management point. It hosts the database, rules, schedules, and settings, exposing a LAN endpoint for agents.
```bash
netorium controller init
netorium controller start --host 0.0.0.0 --port 8765
```

### 3. Managed Endpoint Mode
For real, office-wide endpoint firewall control, install the Netorium Agent on client PCs.
```bash
netorium-agent enroll --controller http://192.168.1.10:8765 --token <TOKEN>
netorium-agent service install
```
*The agent securely polls for commands and does not require local administrator passwords.*

---

## 🚀 Installation Instructions

### One-line Install for Windows PowerShell
```powershell
irm https://raw.githubusercontent.com/it31wasdrexm/netorium/main/install.ps1 | iex
```

### One-line Install for Linux / macOS
```bash
curl -fsSL https://raw.githubusercontent.com/it31wasdrexm/netorium/main/install.sh | bash
```

### Python Package (pipx/pip)
```bash
pipx install netorium-cli
# OR
python -m pip install netorium-cli
```

---

## 🛠️ Core Commands Quick Reference

### Zone Management
```bash
netorium zone add accounting --floor 3 --department "Accounting"
netorium zone list
netorium zone show accounting
```

### Device Management
```bash
netorium device add 192.168.1.25 --zone accounting --hostname pc-acc-01
netorium device list
netorium device move 192.168.1.25 --zone reception
```

### Firewall & Policies
```bash
# Block an IP
netorium firewall block 192.168.1.25 --reason "Policy violation"

# Apply rule to entire zone
netorium firewall block-zone accounting --reason "After 18:00"

# Rollback last change
netorium firewall rollback --last
```

### Active Directory & PRTG
```bash
netorium ad lookup 192.168.1.25
netorium prtg traffic 192.168.1.25
netorium prtg sync
```

---

## ⚙️ Configuration

Your Netorium configuration is stored here:
* **Windows:** `%APPDATA%\Netorium\config.toml`
* **Linux/macOS:** `~/.config/netorium/config.toml`

Run `netorium config init` to create a default configuration, and `netorium config show` to view it.

---

## 🔄 Updates

Netorium makes keeping your tools up-to-date effortless:
```bash
netorium update check
netorium update install
```
