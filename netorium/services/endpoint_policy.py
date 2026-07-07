from __future__ import annotations

import json
import os
import platform
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from netorium.core.platform import user_data_dir
from netorium.core.subprocess_utils import run_text_optional


class EndpointPolicyError(RuntimeError):
    pass


@dataclass(frozen=True)
class EndpointPolicyResult:
    message: str


def apply_ip_firewall_policy(
    *,
    action: str,
    ip_address: str,
    reason: str,
    platform_name: str | None = None,
) -> EndpointPolicyResult:
    _require_windows(platform_name)
    rule_name = _rule_name("IP", ip_address)
    if action == "block":
        script = (
            f"$Name = {_ps_quote(rule_name)}; "
            "Remove-NetFirewallRule -DisplayName $Name -ErrorAction SilentlyContinue; "
            "New-NetFirewallRule "
            "-DisplayName $Name "
            "-Direction Outbound "
            f"-RemoteAddress {_ps_quote(ip_address)} "
            "-Action Block "
            "-Profile Any "
            f"-Description {_ps_quote(reason)} "
            "-ErrorAction Stop | Out-Null"
        )
    elif action == "unblock":
        script = (
            f"Remove-NetFirewallRule -DisplayName {_ps_quote(rule_name)} "
            "-ErrorAction SilentlyContinue"
        )
    else:
        raise EndpointPolicyError("Firewall action must be block or unblock.")

    _run_powershell(script)
    return EndpointPolicyResult(f"Windows firewall {action} applied for {ip_address}.")


def apply_site_policy(
    *,
    action: str,
    domain: str,
    reason: str,
    hosts_path: Path | None = None,
    platform_name: str | None = None,
) -> EndpointPolicyResult:
    active_platform = _active_platform_name(platform_name)
    if active_platform.startswith("win"):
        active_hosts_path = hosts_path or Path(os.environ.get("SystemRoot", r"C:\Windows")) / (
            r"System32\drivers\etc\hosts"
        )
    else:
        active_hosts_path = hosts_path or Path("/etc/hosts")
    domains = _hosts_domains(domain)
    start_marker = f"# NETORIUM BLOCK START {domain}"
    end_marker = f"# NETORIUM BLOCK END {domain}"
    rule_name = _rule_name("Site", domain)

    try:
        current = active_hosts_path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        raise EndpointPolicyError(f"Could not read hosts file {active_hosts_path}: {exc}") from exc

    updated = _remove_marked_block(current, start_marker, end_marker)
    if action == "block":
        lines = [start_marker, f"# Reason: {reason}"]
        lines.extend(_hosts_block_lines(domains))
        lines.append(end_marker)
        updated = updated.rstrip() + "\n" + "\n".join(lines) + "\n"
        if active_platform.startswith("win"):
            firewall_script = _site_firewall_block_script(rule_name, domains, reason)
        else:
            firewall_script = None
    elif action == "unblock":
        if active_platform.startswith("win"):
            firewall_script = _site_firewall_unblock_script(rule_name)
        else:
            firewall_script = None
    else:
        raise EndpointPolicyError("Site policy action must be block or unblock.")

    try:
        active_hosts_path.write_text(updated, encoding="utf-8")
    except OSError as exc:
        raise EndpointPolicyError(f"Could not write hosts file {active_hosts_path}: {exc}") from exc

    if active_platform.startswith("win"):
        if firewall_script is not None:
            _run_powershell(firewall_script)
        _run_powershell(_site_dns_flush_script())
        return EndpointPolicyResult(f"Windows hosts site {action} applied for {domain}.")
    _flush_dns_cache_non_windows()
    return EndpointPolicyResult(f"{active_platform} hosts site {action} applied for {domain}.")


def apply_app_policy(
    *,
    action: str,
    executable: str,
    reason: str,
    platform_name: str | None = None,
) -> EndpointPolicyResult:
    active_platform = _active_platform_name(platform_name)
    if active_platform.startswith("linux") or active_platform == "darwin":
        return _apply_unix_app_policy(action=action, executable=executable, reason=reason)

    _require_windows(active_platform)
    rule_name = _rule_name("App", executable)

    aliases = {
        "tg": "Telegram.exe",
        "tg.exe": "Telegram.exe",
        "telegram": "Telegram.exe",
        "dota": "dota2.exe",
        "dota.exe": "dota2.exe",
        "dota2": "dota2.exe",
        "cs1.6": "hl.exe",
        "cs16": "hl.exe",
        "minecraft": "MinecraftLauncher.exe",
        "mc": "MinecraftLauncher.exe",
        "discord": "Discord.exe",
        "steam": "steam.exe",
        "epic": "EpicGamesLauncher.exe",
    }

    executable_lower = executable.lower()
    if executable_lower in aliases:
        executable = aliases[executable_lower]

    if action == "block":
        if _looks_like_executable_path(executable):
            script = _app_block_program_script(rule_name, executable, reason)
        else:
            script = _app_block_by_name_script(rule_name, executable, reason)
    elif action == "unblock":
        script = _app_unblock_script(rule_name)
    else:
        raise EndpointPolicyError("Application policy action must be block or unblock.")

    _run_powershell(script)
    return EndpointPolicyResult(f"Windows firewall app {action} applied for {executable}.")


def apply_speed_policy(
    *,
    action: str,
    download_kbps: int | None,
    upload_kbps: int | None,
    reason: str,
    platform_name: str | None = None,
) -> EndpointPolicyResult:
    _require_windows(platform_name)
    policy_name = "Netorium Endpoint Speed Limit"
    if action == "clear":
        _run_powershell(
            f"Remove-NetQosPolicy -Name {_ps_quote(policy_name)} "
            "-PolicyStore PersistentStore -Confirm:$false -ErrorAction SilentlyContinue"
        )
        return EndpointPolicyResult("Windows QoS speed limit cleared.")
    if action != "limit":
        raise EndpointPolicyError("Speed policy action must be limit or clear.")

    throttle_kbps = upload_kbps if upload_kbps is not None else download_kbps
    if throttle_kbps is None:
        raise EndpointPolicyError("Speed limit requires upload_kbps or download_kbps.")
    throttle_bits = throttle_kbps * 1000
    script = (
        f"$Name = {_ps_quote(policy_name)}; "
        "if (-not (Test-Path 'HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\QoS')) { New-Item -Path 'HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\QoS' -Force | Out-Null }; "
        "Set-ItemProperty -Path 'HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\QoS' -Name 'Do not use NLA' -Value 1 -Type DWord -Force -ErrorAction SilentlyContinue; "
        "Remove-NetQosPolicy -Name $Name -PolicyStore PersistentStore "
        "-Confirm:$false -ErrorAction SilentlyContinue; "
        "New-NetQosPolicy "
        "-Name $Name "
        "-PolicyStore PersistentStore "
        f"-ThrottleRateActionBitsPerSecond {throttle_bits} "
        f"-NetworkProfile All "
        f"-Precedence 127 "
        f"-ErrorAction Stop"
    )
    _run_powershell(script)
    note = (
        "Windows QoS throttles outbound traffic; download limiting needs a router, "
        "gateway, or future packet-filter adapter."
        if download_kbps is not None
        else "Windows QoS throttles outbound traffic."
    )
    return EndpointPolicyResult(f"Windows QoS speed limit applied at {throttle_kbps}kbps. {note}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _require_windows(platform_name: str | None = None) -> None:
    active_platform = _active_platform_name(platform_name)
    if not active_platform.lower().startswith("win"):
        raise EndpointPolicyError("Real endpoint policy commands are Windows-only.")


def _active_platform_name(platform_name: str | None) -> str:
    if platform_name is not None:
        return platform_name.lower()
    return platform.system().lower()


def _run_powershell(script: str) -> None:
    command: Sequence[str] = (
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-WindowStyle",
        "Hidden",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        script,
    )
    try:
        completed = run_text_optional(command)
    except OSError as exc:
        raise EndpointPolicyError(f"Could not start PowerShell: {exc}") from exc
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip() or "unknown PowerShell error"
        raise EndpointPolicyError(stderr)


def _hosts_domains(domain: str) -> list[str]:
    clean_domain = domain[2:] if domain.startswith("*.") else domain
    if clean_domain.startswith("www."):
        clean_domain = clean_domain[4:]
    return sorted({clean_domain, f"www.{clean_domain}", f"m.{clean_domain}"})


def _hosts_block_lines(domains: list[str]) -> list[str]:
    lines: list[str] = []
    for blocked_domain in domains:
        for ip_address in ("0.0.0.0", "127.0.0.1", "::1"):
            lines.append(f"{ip_address} {blocked_domain}")
    return lines


def _site_firewall_block_script(rule_name: str, domains: list[str], reason: str) -> str:
    parts = [
        f"$Reason = {_ps_quote(reason)};",
        f"Get-NetFirewallRule -ErrorAction SilentlyContinue | "
        f"Where-Object {{ $_.DisplayName -like {_ps_quote(f'{rule_name}%')} }} | "
        "Remove-NetFirewallRule -ErrorAction SilentlyContinue;",
    ]
    for index, blocked_domain in enumerate(domains):
        display_name = f"{rule_name} {index + 1}"[:120]
        parts.append(
            "New-NetFirewallRule "
            f"-DisplayName {_ps_quote(display_name)} "
            "-Direction Outbound "
            "-Action Block "
            "-Profile Any "
            f"-RemoteFqdn {_ps_quote(blocked_domain)} "
            f"-Description $Reason "
            "-ErrorAction Stop | Out-Null"
        )
    return " ".join(parts)


def _site_firewall_unblock_script(rule_name: str) -> str:
    return (
        f"Get-NetFirewallRule -ErrorAction SilentlyContinue | "
        f"Where-Object {{ $_.DisplayName -like {_ps_quote(f'{rule_name}%')} }} | "
        "Remove-NetFirewallRule -ErrorAction SilentlyContinue"
    )


def _site_dns_flush_script() -> str:
    return (
        "Stop-Service -Name Dnscache -Force -ErrorAction SilentlyContinue; "
        "Start-Service -Name Dnscache -ErrorAction SilentlyContinue; "
        "Clear-DnsClientCache -ErrorAction SilentlyContinue; "
        "ipconfig /flushdns | Out-Null"
    )


def _flush_dns_cache_non_windows() -> None:
    commands: tuple[tuple[str, ...], ...] = (
        ("resolvectl", "flush-caches"),
        ("systemd-resolve", "--flush-caches"),
        ("service", "nscd", "restart"),
    )
    for command in commands:
        if shutil.which(command[0]) is None:
            continue
        run_text_optional(command)


def _looks_like_executable_path(executable: str) -> bool:
    return any(marker in executable for marker in ("\\", "/", ":"))


def _app_rule_names(rule_name: str) -> tuple[str, str]:
    return f"{rule_name} Out"[:120], f"{rule_name} In"[:120]


def _app_block_program_script(rule_name: str, executable: str, reason: str) -> str:
    out_name, in_name = _app_rule_names(rule_name)
    return (
        f"Remove-NetFirewallRule -DisplayName {_ps_quote(out_name)} -ErrorAction SilentlyContinue; "
        f"Remove-NetFirewallRule -DisplayName {_ps_quote(in_name)} -ErrorAction SilentlyContinue; "
        f"New-NetFirewallRule -DisplayName {_ps_quote(out_name)} -Direction Outbound "
        f"-Program {_ps_quote(executable)} -Action Block -Profile Any "
        f"-Description {_ps_quote(reason)} -ErrorAction Stop | Out-Null; "
        f"New-NetFirewallRule -DisplayName {_ps_quote(in_name)} -Direction Inbound "
        f"-Program {_ps_quote(executable)} -Action Block -Profile Any "
        f"-Description {_ps_quote(reason)} -ErrorAction Stop | Out-Null"
    )


def _app_block_by_name_script(rule_name: str, executable: str, reason: str) -> str:
    out_name, in_name = _app_rule_names(rule_name)
    return (
        f"$ExeName = {_ps_quote(executable)}; "
        "if ($ExeName -notmatch '\\.exe$') { $ExeName += '.exe' }; "
        "$Matches = @(where.exe $ExeName 2>$null | "
        "Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique); "
        "if ($Matches.Count -eq 0) { "
        "  $running = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
        "  Where-Object { $_.Name -ieq $ExeName } | "
        "  Select-Object -ExpandProperty ExecutablePath -ErrorAction SilentlyContinue | "
        "  Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique; "
        "  if ($running) { $Matches += $running } "
        "}; "
        "if ($Matches.Count -eq 0) { "
        "  foreach ($rp in @('HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths', "
        "'HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths')) { "
        "    $key = Join-Path $rp $ExeName; "
        "    if (Test-Path $key) { "
        "      $val = (Get-ItemProperty $key -Name '(default)' -ErrorAction SilentlyContinue).'(default)'; "
        "      if ($val -and (Test-Path $val)) { $Matches += $val } "
        "    } "
        "  } "
        "}; "
        "$Matches = @($Matches | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique); "
        "if ($Matches.Count -eq 0) { throw ('Executable not found: ' + $ExeName) }; "
        f"$OutBase = {_ps_quote(out_name)}; "
        f"$InBase = {_ps_quote(in_name)}; "
        f"$Reason = {_ps_quote(reason)}; "
        "foreach ($Program in $Matches) { "
        "  Remove-NetFirewallRule -DisplayName $OutBase -ErrorAction SilentlyContinue; "
        "  Remove-NetFirewallRule -DisplayName $InBase -ErrorAction SilentlyContinue; "
        "  New-NetFirewallRule -DisplayName $OutBase -Direction Outbound -Program $Program "
        "  -Action Block -Profile Any -Description $Reason -ErrorAction Stop | Out-Null; "
        "  New-NetFirewallRule -DisplayName $InBase -Direction Inbound -Program $Program "
        "  -Action Block -Profile Any -Description $Reason -ErrorAction Stop | Out-Null "
        "}"
    )


def _app_unblock_script(rule_name: str) -> str:
    out_name, in_name = _app_rule_names(rule_name)
    prefix = _ps_quote(f"{rule_name}%")
    return (
        f"Remove-NetFirewallRule -DisplayName {_ps_quote(out_name)} -ErrorAction SilentlyContinue; "
        f"Remove-NetFirewallRule -DisplayName {_ps_quote(in_name)} -ErrorAction SilentlyContinue; "
        f"Get-NetFirewallRule -ErrorAction SilentlyContinue | "
        f"Where-Object {{ $_.DisplayName -like {prefix} }} | "
        "Remove-NetFirewallRule -ErrorAction SilentlyContinue"
    )


def _remove_marked_block(text: str, start_marker: str, end_marker: str) -> str:
    pattern = re.compile(
        r"(?ms)^%s\r?\n.*?^%s\r?\n?" % (re.escape(start_marker), re.escape(end_marker))
    )
    return pattern.sub("", text).rstrip() + "\n"


def _rule_name(kind: str, target: str) -> str:
    safe_target = re.sub(r"[^A-Za-z0-9_.:-]+", "_", target).strip("_")
    return f"Netorium {kind} {safe_target}"[:120]


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _app_blocklist_path() -> Path:
    return user_data_dir() / "agent_app_blocklist.json"


def _load_app_blocklist() -> list[str]:
    path = _app_blocklist_path()
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    clean_entries = [str(item).strip() for item in payload if str(item).strip()]
    seen: set[str] = set()
    unique: list[str] = []
    for item in clean_entries:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _save_app_blocklist(entries: Sequence[str]) -> None:
    path = _app_blocklist_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(list(entries), ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise EndpointPolicyError(f"Could not update app blocklist {path}: {exc}") from exc


def _apply_unix_app_policy(*, action: str, executable: str, reason: str) -> EndpointPolicyResult:
    blocklist = _load_app_blocklist()
    normalized = executable.strip()
    if not normalized:
        raise EndpointPolicyError("Executable cannot be empty.")

    lowered = normalized.lower()
    existing = {item.lower() for item in blocklist}
    if action == "block":
        if lowered not in existing:
            blocklist.append(normalized)
            _save_app_blocklist(blocklist)
        _terminate_matching_processes(normalized)
        return EndpointPolicyResult(
            f"Unix app block enabled for {normalized}. Reason: {reason}. "
            "Matching processes will be terminated."
        )
    if action == "unblock":
        updated = [item for item in blocklist if item.lower() != lowered]
        _save_app_blocklist(updated)
        return EndpointPolicyResult(f"Unix app block removed for {normalized}.")
    raise EndpointPolicyError("Application policy action must be block or unblock.")


def enforce_unix_app_blocklist() -> None:
    if _active_platform_name(None).startswith("win"):
        return
    for executable in _load_app_blocklist():
        _terminate_matching_processes(executable)


def _terminate_matching_processes(executable: str) -> None:
    process_name = Path(executable).name or executable
    try:
        run_text_optional(("pkill", "-f", process_name))
    except OSError:
        return
