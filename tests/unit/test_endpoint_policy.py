from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Sequence

import pytest

from netorium.services.endpoint_policy import (
    EndpointPolicyError,
    apply_app_policy,
    apply_ip_firewall_policy,
    apply_site_policy,
    apply_speed_policy,
)


class RunRecorder:
    def __init__(self) -> None:
        self.commands: list[Sequence[str]] = []

    def __call__(
        self,
        command: Sequence[str],
        *,
        check: bool = False,
        capture_output: bool = False,
        text: bool = False,
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


def test_real_ip_firewall_policy_uses_windows_firewall(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = RunRecorder()
    monkeypatch.setattr(subprocess, "run", recorder)

    result = apply_ip_firewall_policy(
        action="block",
        ip_address="192.168.1.25",
        reason="Policy test",
        platform_name="Windows",
    )

    assert "applied for 192.168.1.25" in result.message
    assert recorder.commands
    script = _script(recorder.commands[0])
    assert "New-NetFirewallRule" in script
    assert "192.168.1.25" in script


def test_real_app_policy_uses_windows_firewall_program_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = RunRecorder()
    monkeypatch.setattr(subprocess, "run", recorder)

    result = apply_app_policy(
        action="block",
        executable=r"C:\Games\dota2.exe",
        reason="No game traffic",
        platform_name="Windows",
    )

    assert "dota2.exe" in result.message
    script = _script(recorder.commands[0])
    assert "New-NetFirewallRule" in script
    assert "-Program 'C:\\Games\\dota2.exe'" in script


def test_real_app_policy_searches_by_executable_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = RunRecorder()
    monkeypatch.setattr(subprocess, "run", recorder)

    result = apply_app_policy(
        action="block",
        executable="dota2.exe",
        reason="No game traffic",
        platform_name="Windows",
    )

    assert "dota2.exe" in result.message
    script = _script(recorder.commands[0])
    assert "Get-ChildItem" in script
    assert "dota2.exe" in script


def test_real_site_policy_updates_hosts_file_and_flushes_dns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hosts_path = tmp_path / "hosts"
    hosts_path.write_text("127.0.0.1 localhost\n", encoding="utf-8")
    recorder = RunRecorder()
    monkeypatch.setattr(subprocess, "run", recorder)

    block = apply_site_policy(
        action="block",
        domain="youtube.com",
        reason="Class policy",
        hosts_path=hosts_path,
        platform_name="Windows",
    )
    unblock = apply_site_policy(
        action="unblock",
        domain="youtube.com",
        reason="Class policy",
        hosts_path=hosts_path,
        platform_name="Windows",
    )

    assert "site block applied" in block.message
    assert "site unblock applied" in unblock.message
    text = hosts_path.read_text(encoding="utf-8")
    assert "127.0.0.1 localhost" in text
    assert "0.0.0.0 youtube.com" not in text
    assert any("Clear-DnsClientCache" in _script(command) for command in recorder.commands)


def test_real_speed_policy_uses_windows_qos(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = RunRecorder()
    monkeypatch.setattr(subprocess, "run", recorder)

    result = apply_speed_policy(
        action="limit",
        download_kbps=2048,
        upload_kbps=512,
        reason="Temporary limit",
        platform_name="Windows",
    )

    assert "512kbps" in result.message
    script = _script(recorder.commands[0])
    assert "New-NetQosPolicy" in script
    assert "-ThrottleRateActionBitsPerSecond 512000" in script


def test_real_endpoint_policy_rejects_non_windows() -> None:
    with pytest.raises(EndpointPolicyError, match="Windows-only"):
        apply_ip_firewall_policy(
            action="block",
            ip_address="192.168.1.25",
            reason="Policy test",
            platform_name="Linux",
        )


def _script(command: Sequence[Any]) -> str:
    return str(command[-1])
