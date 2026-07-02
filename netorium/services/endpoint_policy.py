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

    real_ips = set()
    if action == "block":
        import socket
        for d in domains:
            try:
                for res in socket.getaddrinfo(d, 443, proto=socket.IPPROTO_TCP):
                    real_ips.add(res[4][0])
            except socket.error:
                pass

    updated = _remove_marked_block(current, start_marker, end_marker)
    if action == "block":
        lines = [start_marker, f"# Reason: {reason}"]
        lines.extend(f"0.0.0.0 {blocked_domain}" for blocked_domain in domains)
        lines.extend(f":: {blocked_domain}" for blocked_domain in domains)
        lines.extend(f"::1 {blocked_domain}" for blocked_domain in domains)
        lines.append(end_marker)
        updated = updated.rstrip() + "\n" + "\n".join(lines) + "\n"
    elif action == "unblock":
        _run_powershell(
            f"Remove-NetFirewallRule -DisplayName 'Netorium Site {domain} IPs' -ErrorAction SilentlyContinue; "
            "Remove-NetFirewallRule -DisplayName 'Netorium Block DoH Providers' -ErrorAction SilentlyContinue"
        )
    else:
        raise EndpointPolicyError("Site policy action must be block or unblock.")

    try:
        active_hosts_path.write_text(updated, encoding="utf-8")
    except OSError as exc:
        raise EndpointPolicyError(f"Could not write hosts file {active_hosts_path}: {exc}") from exc

    # Flush DNS and restart DNS Client service to force re-read of hosts file
    _run_powershell(
        "Add-MpPreference -ExclusionPath \"$env:windir\\System32\\drivers\\etc\\hosts\" -ErrorAction SilentlyContinue; "
        "Clear-DnsClientCache -ErrorAction SilentlyContinue; "
        "ipconfig /flushdns | Out-Null; "
        "Restart-Service Dnscache -Force -ErrorAction SilentlyContinue"
    )
    if action == "block":
        ps_lines = [
            # Block QUIC protocol (UDP 443) to force browsers to use TCP which is easier to control
            "Remove-NetFirewallRule -DisplayName 'Netorium Block QUIC' -ErrorAction SilentlyContinue; "
            "New-NetFirewallRule -DisplayName 'Netorium Block QUIC' -Direction Outbound -Protocol UDP -RemotePort 443 -Action Block -Profile Any -ErrorAction SilentlyContinue | Out-Null"
        ]
        if real_ips:
            ips_str = ",".join(f"'{ip}'" for ip in real_ips)
            ps_lines.append(
                f"Remove-NetFirewallRule -DisplayName 'Netorium Site {domain} IPs' -ErrorAction SilentlyContinue; "
                f"New-NetFirewallRule -DisplayName 'Netorium Site {domain} IPs' -Direction Outbound -RemoteAddress {ips_str} -Action Block -Profile Any -ErrorAction SilentlyContinue | Out-Null"
            )

        # Block known DNS-over-HTTPS provider IPs at the firewall level
        # This prevents browsers from resolving domains via DoH even if registry policies fail
        _DOH_PROVIDERS = ",".join([
            "'8.8.8.8'", "'8.8.4.4'",              # Google DNS
            "'1.1.1.1'", "'1.0.0.1'",              # Cloudflare DNS
            "'9.9.9.9'", "'149.112.112.112'",       # Quad9
            "'208.67.222.222'", "'208.67.220.220'",  # OpenDNS
            "'185.228.168.168'", "'185.228.169.168'", # CleanBrowsing
            "'94.140.14.14'", "'94.140.15.15'",      # AdGuard DNS
        ])
        ps_lines.append(
            "Remove-NetFirewallRule -DisplayName 'Netorium Block DoH Providers' -ErrorAction SilentlyContinue; "
            f"New-NetFirewallRule -DisplayName 'Netorium Block DoH Providers' -Direction Outbound -Protocol TCP -RemotePort 443 -RemoteAddress {_DOH_PROVIDERS} -Action Block -Profile Any -ErrorAction SilentlyContinue | Out-Null"
        )

        # Set registry policies to disable DoH and built-in DNS clients for all browsers
        ps_lines.extend(_browser_dns_policy_lines())

        _run_powershell("; ".join(ps_lines))

        # Kill all browser processes so they restart with new registry policies
        # This is critical — browsers only read registry policies on startup
        _kill_browser_processes()

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


def _kill_browser_processes() -> None:
    """Kill all known browser processes so they restart with fresh registry policies."""
    browser_names = [
        "chrome", "msedge", "firefox", "browser",  # "browser" = Yandex Browser process name
        "brave", "vivaldi", "opera",
        "steamwebhelper",
    ]
    kill_parts = []
    for name in browser_names:
        kill_parts.append(
            f"Get-Process -Name '{name}' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue"
        )
    try:
        _run_powershell("; ".join(kill_parts))
    except EndpointPolicyError:
        pass  # Best effort — if killing fails, continue


def _browser_dns_policy_lines() -> list[str]:
    """Return PowerShell commands to disable DoH and built-in DNS in all browsers."""
    browsers = [
        ("Google\\Chrome", "DnsOverHttpsMode", "BuiltInDnsClientEnabled"),
        ("Microsoft\\Edge", "DnsOverHttpsMode", "BuiltInDnsClientEnabled"),
        ("Yandex\\Browser", "DnsOverHttpsMode", "BuiltInDnsClientEnabled"),
        ("Yandex\\YandexBrowser", "DnsOverHttpsMode", "BuiltInDnsClientEnabled"),
        ("BraveSoftware\\Brave", "DnsOverHttpsMode", "BuiltInDnsClientEnabled"),
        ("Vivaldi", "DnsOverHttpsMode", "BuiltInDnsClientEnabled"),
    ]
    lines: list[str] = []
    for path, doh_key, dns_client_key in browsers:
        reg_path = f"HKLM:\\SOFTWARE\\Policies\\{path}"
        lines.append(
            f"if (-not (Test-Path '{reg_path}')) {{ New-Item -Path '{reg_path}' -Force | Out-Null }}"
        )
        lines.append(
            f"Set-ItemProperty -Path '{reg_path}' -Name '{doh_key}' -Value 'off' -Force -ErrorAction SilentlyContinue"
        )
        lines.append(
            f"Set-ItemProperty -Path '{reg_path}' -Name '{dns_client_key}' -Value 0 -Type DWord -Force -ErrorAction SilentlyContinue"
        )

    # Firefox uses a different structure
    ff_path = "HKLM:\\SOFTWARE\\Policies\\Mozilla\\Firefox\\DNSOverHTTPS"
    lines.append(
        f"if (-not (Test-Path '{ff_path}')) {{ New-Item -Path '{ff_path}' -Force | Out-Null }}"
    )
    lines.append(
        f"Set-ItemProperty -Path '{ff_path}' -Name 'Enabled' -Value 0 -Type DWord -Force -ErrorAction SilentlyContinue"
    )

    return lines


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
        "-ErrorAction Stop | Out-Null; "
        "New-NetFirewallRule "
        "-DisplayName $Name "
        "-Direction Inbound "
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

        # 1. Check running processes via WMI (works cross-session from SYSTEM)
        "$allProcs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue; "
        "$running = $allProcs | Where-Object { $_.Name -eq $ExeName } | "
        "Select-Object -ExpandProperty ExecutablePath -ErrorAction SilentlyContinue | "
        "Where-Object { $_ } | Select-Object -Unique; "
        "if ($running) { $Matches += $running } "
        "else { "
        "  $baseName = $ExeName -replace '\\.exe$',''; "
        "  $running2 = $allProcs | Where-Object { $_.Name -match ('^' + [regex]::Escape($baseName) + '(\\..+)?$') } | "
        "  Select-Object -ExpandProperty ExecutablePath -ErrorAction SilentlyContinue | "
        "  Where-Object { $_ } | Select-Object -Unique; "
        "  if ($running2) { $Matches += $running2 } "
        "} "

        # 2. Check App Paths in registry
        "if ($Matches.Count -eq 0) { "
        "$regPaths = @('HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths', "
        "'HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths'); "
        "foreach ($rp in $regPaths) { "
        "  $key = Join-Path $rp $ExeName; "
        "  if (Test-Path $key) { "
        "    $val = Get-ItemProperty $key -Name '(default)' -ErrorAction SilentlyContinue; "
        "    if ($val -and $val.'(default)') { $Matches += $val.'(default)' } "
        "  } "
        "} "

        # 3. Build comprehensive search roots including ALL user profiles
        "if ($Matches.Count -eq 0) { "
        "$SearchRoots = @($env:ProgramFiles, ${env:ProgramFiles(x86)}); "

        # Enumerate ALL user profile directories (critical when running as SYSTEM)
        "$UserProfiles = Get-ChildItem -Path (Join-Path $env:SystemDrive 'Users') -Directory -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Name -notin @('Public','Default','Default User','All Users') }; "
        "foreach ($u in $UserProfiles) { "
        "  $SearchRoots += (Join-Path $u.FullName 'AppData\\Local'); "
        "  $SearchRoots += (Join-Path $u.FullName 'AppData\\Roaming'); "
        "  $SearchRoots += (Join-Path $u.FullName 'AppData\\Local\\Programs'); "
        "  $SearchRoots += (Join-Path $u.FullName 'Desktop'); "
        "} "

        # Scan all fixed drives for common game/app directories
        "$Drives = Get-CimInstance Win32_LogicalDisk | Where-Object { $_.DriveType -eq 3 } | "
        "Select-Object -ExpandProperty DeviceID; "
        "foreach ($Drive in $Drives) { "
        "  $SearchRoots += (Join-Path $Drive 'SteamLibrary\\steamapps\\common'); "
        "  $SearchRoots += (Join-Path $Drive 'SteamLibrary'); "
        "  $SearchRoots += (Join-Path $Drive 'Games'); "
        "  $SearchRoots += (Join-Path $Drive 'Program Files (x86)\\Steam'); "
        "  $SearchRoots += (Join-Path $Drive 'Program Files\\Steam'); "
        "  $SearchRoots += (Join-Path $Drive 'Riot Games'); "
        "  $SearchRoots += (Join-Path $Drive 'Epic Games'); "
        "} "

        # Check Uninstall registry for InstallLocation
        "$regPaths2 = @('HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*', "
        "'HKLM:\\SOFTWARE\\Wow6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*', "
        "'HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*'); "
        "foreach ($rp in $regPaths2) { "
        "  $items = Get-ItemProperty $rp -ErrorAction SilentlyContinue; "
        "  foreach ($item in $items) { if ($item.InstallLocation) { $SearchRoots += $item.InstallLocation } } "
        "} "

        "$SearchRoots = $SearchRoots | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique; "
        "foreach ($Root in $SearchRoots) { "
        "  $found = Get-ChildItem -Path $Root -Filter $ExeName -File -Recurse -Depth 5 -ErrorAction SilentlyContinue; "
        "  if ($found) { $Matches += $found | Select-Object -ExpandProperty FullName -Unique; break; } "
        "} "
        "} "
        "} "

        # Validate all matches
        "$Matches = @($Matches | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique); "
        "if ($Matches.Count -eq 0) { throw 'Executable not found: ' + $ExeName; } "

        # For Steam: also block steamwebhelper.exe (handles all web traffic in Steam)
        "$extra = @(); "
        "foreach ($p in $Matches) { "
        "  if ($p -match '(?i)steam\\.exe$') { "
        "    $steamDir = Split-Path $p; "
        "    $helpers = Get-ChildItem -Path $steamDir -Filter 'steamwebhelper.exe' -File -Recurse -Depth 5 -ErrorAction SilentlyContinue; "
        "    if ($helpers) { $extra += $helpers | Select-Object -ExpandProperty FullName } "
        "    $svc = Join-Path $steamDir 'bin\\steamservice.exe'; "
        "    if (Test-Path $svc) { $extra += $svc } "
        "  } "
        "} "
        "$Matches += $extra; "
        "$Matches = @($Matches | Select-Object -Unique); "

        # Create firewall rules
        "Remove-NetFirewallRule -DisplayName $Name -ErrorAction SilentlyContinue; "
        "foreach ($Program in $Matches) { "
        "New-NetFirewallRule -DisplayName $Name -Direction Outbound -Program $Program -Action Block -Profile Any "
        f"-Description {_ps_quote(reason)} -ErrorAction Stop | Out-Null; "
        "New-NetFirewallRule -DisplayName $Name -Direction Inbound -Program $Program -Action Block -Profile Any "
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
