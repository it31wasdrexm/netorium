from __future__ import annotations

import os
import platform
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


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
        lines.append(end_marker)
        updated = updated.rstrip() + "\n" + "\n".join(lines) + "\n"
    elif action != "unblock":
        raise EndpointPolicyError("Site policy action must be block or unblock.")

    try:
        active_hosts_path.write_text(updated, encoding="utf-8")
    except OSError as exc:
        raise EndpointPolicyError(f"Could not write hosts file {active_hosts_path}: {exc}") from exc

    _run_powershell("Clear-DnsClientCache -ErrorAction SilentlyContinue")
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
    if action == "block":
        script = (
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
            "-PolicyStore ActiveStore -Confirm:$false -ErrorAction SilentlyContinue"
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
        "Remove-NetQosPolicy -Name $Name -PolicyStore ActiveStore "
        "-Confirm:$false -ErrorAction SilentlyContinue; "
        "New-NetQosPolicy "
        "-Name $Name "
        "-PolicyStore ActiveStore "
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
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise EndpointPolicyError(f"Could not start PowerShell: {exc}") from exc
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip() or "unknown PowerShell error"
        raise EndpointPolicyError(stderr)


def _hosts_domains(domain: str) -> list[str]:
    clean_domain = domain[2:] if domain.startswith("*.") else domain
    domains = [clean_domain]
    if not clean_domain.startswith("www."):
        domains.append(f"www.{clean_domain}")
    return domains


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
