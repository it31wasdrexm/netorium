from __future__ import annotations

import os
import platform
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

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
            "-ErrorAction Stop"
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
    _require_windows(platform_name)
    active_hosts_path = hosts_path or Path(os.environ.get("SystemRoot", r"C:\Windows")) / (
        r"System32\drivers\etc\hosts"
    )
    domains = _hosts_domains(domain)
    start_marker = f"# NETORIUM BLOCK START {domain}"
    end_marker = f"# NETORIUM BLOCK END {domain}"

    try:
        current = active_hosts_path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        raise EndpointPolicyError(f"Could not read hosts file {active_hosts_path}: {exc}") from exc

    updated = _remove_marked_block(current, start_marker, end_marker)
    if action == "block":
        lines = [start_marker, f"# Reason: {reason}"]
        lines.extend(f"0.0.0.0 {blocked_domain}" for blocked_domain in domains)
        lines.extend(f":: {blocked_domain}" for blocked_domain in domains)
        lines.extend(f"::1 {blocked_domain}" for blocked_domain in domains)
        lines.append(end_marker)
        updated = updated.rstrip() + "\n" + "\n".join(lines) + "\n"
    elif action != "unblock":
        raise EndpointPolicyError("Site policy action must be block or unblock.")

    try:
        active_hosts_path.write_text(updated, encoding="utf-8")
    except OSError as exc:
        raise EndpointPolicyError(f"Could not write hosts file {active_hosts_path}: {exc}") from exc

    _run_powershell(
        "Add-MpPreference -ExclusionPath \"$env:windir\\System32\\drivers\\etc\\hosts\" -ErrorAction SilentlyContinue; "
        "Clear-DnsClientCache -ErrorAction SilentlyContinue; "
        "ipconfig /flushdns | Out-Null"
    )
    if action == "block":
        _run_powershell(
            "New-NetFirewallRule -DisplayName 'Netorium Block QUIC' -Direction Outbound -Protocol UDP -RemotePort 443 -Action Block -Profile Any -ErrorAction SilentlyContinue; "
            "if (-not (Test-Path 'HKLM:\\SOFTWARE\\Policies\\Google\\Chrome')) { New-Item -Path 'HKLM:\\SOFTWARE\\Policies\\Google\\Chrome' -Force | Out-Null }; "
            "Set-ItemProperty -Path 'HKLM:\\SOFTWARE\\Policies\\Google\\Chrome' -Name 'DnsOverHttpsMode' -Value 'off' -Force -ErrorAction SilentlyContinue; "
            "if (-not (Test-Path 'HKLM:\\SOFTWARE\\Policies\\Microsoft\\Edge')) { New-Item -Path 'HKLM:\\SOFTWARE\\Policies\\Microsoft\\Edge' -Force | Out-Null }; "
            "Set-ItemProperty -Path 'HKLM:\\SOFTWARE\\Policies\\Microsoft\\Edge' -Name 'BuiltInDnsClientEnabled' -Value 0 -Type DWord -Force -ErrorAction SilentlyContinue; "
            "if (-not (Test-Path 'HKLM:\\SOFTWARE\\Policies\\Mozilla\\Firefox')) { New-Item -Path 'HKLM:\\SOFTWARE\\Policies\\Mozilla\\Firefox' -Force | Out-Null }; "
            "Set-ItemProperty -Path 'HKLM:\\SOFTWARE\\Policies\\Mozilla\\Firefox' -Name 'DNSOverHTTPS' -Value 1 -Type DWord -Force -ErrorAction SilentlyContinue"
        )
    return EndpointPolicyResult(f"Windows hosts site {action} applied for {domain}.")


def apply_app_policy(
    *,
    action: str,
    executable: str,
    reason: str,
    platform_name: str | None = None,
) -> EndpointPolicyResult:
    _require_windows(platform_name)
    rule_name = _rule_name("App", executable)
    
    # Map common aliases to their actual executable names
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
        "epic": "EpicGamesLauncher.exe"
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
        script = (
            f"Remove-NetFirewallRule -DisplayName {_ps_quote(rule_name)} "
            "-ErrorAction SilentlyContinue"
        )
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


def _require_windows(platform_name: str | None = None) -> None:
    active_platform = platform_name or platform.system()
    if not active_platform.lower().startswith("win"):
        raise EndpointPolicyError("Real endpoint policy commands are Windows-only.")


def _run_powershell(script: str) -> None:
    command: Sequence[str] = (
        "powershell.exe",
        "-NoProfile",
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
    domains = {clean_domain, f"www.{clean_domain}"}
    for prefix in ("m", "mobile", "music", "api", "cdn", "static", "i", "s", "login", "auth"):
        domains.add(f"{prefix}.{clean_domain}")
    return sorted(domains)


def _looks_like_executable_path(executable: str) -> bool:
    return any(marker in executable for marker in ("\\", "/", ":"))


def _app_block_program_script(rule_name: str, executable: str, reason: str) -> str:
    return (
        f"$Name = {_ps_quote(rule_name)}; "
        "Remove-NetFirewallRule -DisplayName $Name -ErrorAction SilentlyContinue; "
        "New-NetFirewallRule "
        "-DisplayName $Name "
        "-Direction Outbound "
        f"-Program {_ps_quote(executable)} "
        "-Action Block "
        "-Profile Any "
        f"-Description {_ps_quote(reason)} "
        "-ErrorAction Stop"
    )


def _app_block_by_name_script(rule_name: str, executable: str, reason: str) -> str:
    return (
        f"$Name = {_ps_quote(rule_name)}; "
        f"$ExeName = {_ps_quote(executable)}; "
        "$Matches = @(); "
        "$running = Get-Process | Where-Object { $_.ProcessName -eq $ExeName.Replace('.exe','') } | Select-Object -ExpandProperty Path -Unique -ErrorAction SilentlyContinue; "
        "if ($running) { $Matches += $running } "
        "else { "
        "$regPaths = @('HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths', 'HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths'); "
        "foreach ($rp in $regPaths) { "
        "  $key = Join-Path $rp $ExeName; "
        "  if (Test-Path $key) { "
        "    $val = Get-ItemProperty $key -Name '(default)' -ErrorAction SilentlyContinue; "
        "    if ($val) { $Matches += $val.'(default)' } "
        "  } "
        "} "
        "if ($Matches.Count -eq 0) { "
        "$SearchRoots = @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA, $env:APPDATA); "
        "$Drives = Get-WmiObject Win32_LogicalDisk | Where-Object { $_.DriveType -eq 3 } | Select-Object -ExpandProperty DeviceID; "
        "foreach ($Drive in $Drives) { "
        "$SearchRoots += (Join-Path $Drive 'SteamLibrary\\steamapps\\common'); "
        "$SearchRoots += (Join-Path $Drive 'Games'); "
        "$SearchRoots += (Join-Path $Drive 'Program Files (x86)\\Steam\\steamapps\\common'); "
        "$SearchRoots += (Join-Path $Drive 'Riot Games'); "
        "$SearchRoots += (Join-Path $Drive 'Epic Games'); "
        "} "
        "$SearchRoots = $SearchRoots | Where-Object { $_ -and (Test-Path $_) }; "
        "foreach ($Root in $SearchRoots) { "
        "  $found = Get-ChildItem -Path $Root -Filter $ExeName -File -Recurse -Depth 4 -ErrorAction SilentlyContinue; "
        "  if ($found) { $Matches += $found | Select-Object -ExpandProperty FullName -Unique; break; } "
        "} "
        "} "
        "} "
        "$Matches = @($Matches | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique); "
        "if ($Matches.Count -eq 0) { throw 'Executable not found: ' + $ExeName; } "
        "Remove-NetFirewallRule -DisplayName $Name -ErrorAction SilentlyContinue; "
        "foreach ($Program in $Matches) { "
        "New-NetFirewallRule -DisplayName $Name -Direction Outbound -Program $Program -Action Block -Profile Any "
        f"-Description {_ps_quote(reason)} -ErrorAction Stop | Out-Null "
        "}"
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
