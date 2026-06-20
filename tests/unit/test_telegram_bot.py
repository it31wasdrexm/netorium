from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from netorium.services.telegram_bot import (
    send_telegram_message,
    _handle_bot_command,
    _check_traffic_anomalies,
    _send_unauthorized_reply,
    NOTIFIED_IPS,
)
from netorium.services.traffic import TrafficRecord
from netorium.services.controller import (
    ControllerStatus,
    AgentRecord,
    AgentCommandRecord,
    BatchAgentCommandResult,
)

TOKEN = "123456:test-bot-token"
CHAT_ID = "987654321"


@pytest.fixture(autouse=True)
def _reset_notified_ips():
    """Ensure NOTIFIED_IPS is empty before and after every test."""
    NOTIFIED_IPS.clear()
    yield
    NOTIFIED_IPS.clear()


# ---------------------------------------------------------------------------
# send_telegram_message
# ---------------------------------------------------------------------------

class TestSendTelegramMessage:
    @patch("netorium.services.telegram_bot.requests.post")
    def test_success(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(status_code=200)
        send_telegram_message(TOKEN, CHAT_ID, "hello")

        mock_post.assert_called_once_with(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": "hello", "parse_mode": "HTML"},
            timeout=10,
        )

    @patch("netorium.services.telegram_bot.requests.post")
    def test_http_error_logged(self, mock_post: MagicMock, caplog) -> None:
        mock_post.return_value = MagicMock(status_code=403)
        send_telegram_message(TOKEN, CHAT_ID, "hello")
        assert "Failed to send Telegram message" in caplog.text

    @patch("netorium.services.telegram_bot.requests.post", side_effect=ConnectionError("no network"))
    def test_network_exception_logged(self, mock_post: MagicMock, caplog) -> None:
        send_telegram_message(TOKEN, CHAT_ID, "hello")
        assert "Telegram sendMessage error" in caplog.text


# ---------------------------------------------------------------------------
# _send_unauthorized_reply
# ---------------------------------------------------------------------------

class TestSendUnauthorizedReply:
    @patch("netorium.services.telegram_bot.send_telegram_message")
    def test_sends_access_denied(self, mock_send: MagicMock) -> None:
        _send_unauthorized_reply(TOKEN, "other-chat")
        mock_send.assert_called_once()
        args = mock_send.call_args
        assert args[0][0] == TOKEN
        assert args[0][1] == "other-chat"
        assert "Access Denied" in args[0][2]


# ---------------------------------------------------------------------------
# _handle_bot_command  —  /help and /start
# ---------------------------------------------------------------------------

class TestHandleBotCommandHelp:
    @patch("netorium.services.telegram_bot.send_telegram_message")
    def test_help_command(self, mock_send: MagicMock, tmp_path: Path) -> None:
        _handle_bot_command(TOKEN, CHAT_ID, "/help", tmp_path / "test.db")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "Netorium Admin Bot Commands" in text

    @patch("netorium.services.telegram_bot.send_telegram_message")
    def test_start_command(self, mock_send: MagicMock, tmp_path: Path) -> None:
        _handle_bot_command(TOKEN, CHAT_ID, "/start", tmp_path / "test.db")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "Netorium Admin Bot Commands" in text


# ---------------------------------------------------------------------------
# _handle_bot_command  —  /status
# ---------------------------------------------------------------------------

class TestHandleBotCommandStatus:
    @patch("netorium.services.telegram_bot.send_telegram_message")
    @patch("netorium.services.telegram_bot.list_agents", return_value=[
        AgentRecord(agent_id="a1", hostname="pc-01", zone="zone1", enrolled_at="2026-01-01", last_seen_at="2026-06-20"),
    ])
    @patch("netorium.services.telegram_bot.get_controller_status", return_value=ControllerStatus(
        initialized=True, host="192.168.1.10", port=8765,
        listen_url="http://192.168.1.10:8765", enrollment_url="http://192.168.1.10:8765/enroll",
        active_tokens=3,
    ))
    def test_status_success(self, mock_status, mock_agents, mock_send, tmp_path: Path) -> None:
        _handle_bot_command(TOKEN, CHAT_ID, "/status", tmp_path / "test.db")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "Netorium Status" in text
        assert "192.168.1.10" in text
        assert "8765" in text
        assert "3" in text  # active tokens
        assert "1" in text  # one enrolled agent

    @patch("netorium.services.telegram_bot.send_telegram_message")
    @patch("netorium.services.telegram_bot.get_controller_status", side_effect=RuntimeError("db locked"))
    def test_status_error(self, mock_status, mock_send, tmp_path: Path) -> None:
        _handle_bot_command(TOKEN, CHAT_ID, "/status", tmp_path / "test.db")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "Error retrieving status" in text


# ---------------------------------------------------------------------------
# _handle_bot_command  —  /agents
# ---------------------------------------------------------------------------

class TestHandleBotCommandAgents:
    @patch("netorium.services.telegram_bot.send_telegram_message")
    @patch("netorium.services.telegram_bot.list_agents", return_value=[
        AgentRecord(agent_id="a1", hostname="pc-01", zone="zone1", enrolled_at="2026-01-01", last_seen_at="2026-06-20"),
        AgentRecord(agent_id="a2", hostname="pc-02", zone="zone2", enrolled_at="2026-01-02", last_seen_at=None),
    ])
    def test_agents_listed(self, mock_agents, mock_send, tmp_path: Path) -> None:
        _handle_bot_command(TOKEN, CHAT_ID, "/agents", tmp_path / "test.db")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "Enrolled Agents" in text
        assert "pc-01" in text
        assert "pc-02" in text
        assert "never" in text  # agent a2 last_seen_at is None

    @patch("netorium.services.telegram_bot.send_telegram_message")
    @patch("netorium.services.telegram_bot.list_agents", return_value=[])
    def test_agents_empty(self, mock_agents, mock_send, tmp_path: Path) -> None:
        _handle_bot_command(TOKEN, CHAT_ID, "/agents", tmp_path / "test.db")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "No agents enrolled" in text

    @patch("netorium.services.telegram_bot.send_telegram_message")
    @patch("netorium.services.telegram_bot.list_agents", side_effect=RuntimeError("oops"))
    def test_agents_error(self, mock_agents, mock_send, tmp_path: Path) -> None:
        _handle_bot_command(TOKEN, CHAT_ID, "/agents", tmp_path / "test.db")
        mock_send.assert_called_once()
        assert "Error" in mock_send.call_args[0][2]


# ---------------------------------------------------------------------------
# _handle_bot_command  —  /policies
# ---------------------------------------------------------------------------

class TestHandleBotCommandPolicies:
    @patch("netorium.services.telegram_bot.send_telegram_message")
    @patch("netorium.services.telegram_bot.list_agent_commands", return_value=[
        AgentCommandRecord(
            command_id="cmd1", agent_id="a1", command_type="block_site",
            payload={}, signature="sig", status="delivered",
            result_message=None, created_at="2026-06-20",
            delivered_at="2026-06-20", completed_at=None,
        ),
    ])
    def test_policies_listed(self, mock_cmds, mock_send, tmp_path: Path) -> None:
        _handle_bot_command(TOKEN, CHAT_ID, "/policies", tmp_path / "test.db")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "Policy Commands" in text
        assert "cmd1" in text
        assert "block_site" in text

    @patch("netorium.services.telegram_bot.send_telegram_message")
    @patch("netorium.services.telegram_bot.list_agent_commands", return_value=[])
    def test_policies_empty(self, mock_cmds, mock_send, tmp_path: Path) -> None:
        _handle_bot_command(TOKEN, CHAT_ID, "/policies", tmp_path / "test.db")
        mock_send.assert_called_once()
        assert "No policy commands" in mock_send.call_args[0][2]

    @patch("netorium.services.telegram_bot.send_telegram_message")
    @patch("netorium.services.telegram_bot.list_agent_commands", side_effect=RuntimeError("fail"))
    def test_policies_error(self, mock_cmds, mock_send, tmp_path: Path) -> None:
        _handle_bot_command(TOKEN, CHAT_ID, "/policies", tmp_path / "test.db")
        assert "Error" in mock_send.call_args[0][2]


# ---------------------------------------------------------------------------
# _handle_bot_command  —  /traffic
# ---------------------------------------------------------------------------

class TestHandleBotCommandTraffic:
    @patch("netorium.services.telegram_bot.send_telegram_message")
    @patch("netorium.services.telegram_bot.get_traffic_report", return_value=[
        TrafficRecord(
            ip_address="10.0.0.1", hostname="pc-01", zone_name="zone1",
            download_mb=150.0, upload_mb=30.0, total_mb=180.0,
            is_anomaly=False,
        ),
        TrafficRecord(
            ip_address="10.0.0.2", hostname="pc-02", zone_name="zone1",
            download_mb=5000.0, upload_mb=1000.0, total_mb=6000.0,
            is_anomaly=True, anomaly_reason="High download burst",
        ),
    ])
    def test_traffic_report(self, mock_report, mock_send, tmp_path: Path) -> None:
        _handle_bot_command(TOKEN, CHAT_ID, "/traffic", tmp_path / "test.db")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "Traffic Report" in text
        assert "pc-01" in text
        assert "pc-02" in text
        assert "Anomaly" in text

    @patch("netorium.services.telegram_bot.send_telegram_message")
    @patch("netorium.services.telegram_bot.get_traffic_report", return_value=[])
    def test_traffic_empty(self, mock_report, mock_send, tmp_path: Path) -> None:
        _handle_bot_command(TOKEN, CHAT_ID, "/traffic", tmp_path / "test.db")
        assert "No traffic data" in mock_send.call_args[0][2]

    @patch("netorium.services.telegram_bot.send_telegram_message")
    @patch("netorium.services.telegram_bot.get_traffic_report", side_effect=RuntimeError("fail"))
    def test_traffic_error(self, mock_report, mock_send, tmp_path: Path) -> None:
        _handle_bot_command(TOKEN, CHAT_ID, "/traffic", tmp_path / "test.db")
        assert "Error" in mock_send.call_args[0][2]


# ---------------------------------------------------------------------------
# _handle_bot_command  —  /anomalies
# ---------------------------------------------------------------------------

class TestHandleBotCommandAnomalies:
    @patch("netorium.services.telegram_bot.send_telegram_message")
    @patch("netorium.services.telegram_bot.get_traffic_report", return_value=[
        TrafficRecord(
            ip_address="10.0.0.1", hostname="pc-01", zone_name="zone1",
            download_mb=100.0, upload_mb=20.0, total_mb=120.0,
            is_anomaly=False,
        ),
        TrafficRecord(
            ip_address="10.0.0.2", hostname="pc-02", zone_name="zone1",
            download_mb=9000.0, upload_mb=1500.0, total_mb=10500.0,
            is_anomaly=True, anomaly_reason="Excessive bandwidth",
        ),
    ])
    def test_anomalies_found(self, mock_report, mock_send, tmp_path: Path) -> None:
        _handle_bot_command(TOKEN, CHAT_ID, "/anomalies", tmp_path / "test.db")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "Active Traffic Anomalies" in text
        assert "pc-02" in text
        assert "Excessive bandwidth" in text
        # pc-01 is not anomalous, should not appear
        assert "pc-01" not in text

    @patch("netorium.services.telegram_bot.send_telegram_message")
    @patch("netorium.services.telegram_bot.get_traffic_report", return_value=[
        TrafficRecord(
            ip_address="10.0.0.1", hostname="pc-01", zone_name="zone1",
            download_mb=100.0, upload_mb=20.0, total_mb=120.0,
            is_anomaly=False,
        ),
    ])
    def test_anomalies_none(self, mock_report, mock_send, tmp_path: Path) -> None:
        _handle_bot_command(TOKEN, CHAT_ID, "/anomalies", tmp_path / "test.db")
        assert "No active traffic anomalies" in mock_send.call_args[0][2]

    @patch("netorium.services.telegram_bot.send_telegram_message")
    @patch("netorium.services.telegram_bot.get_traffic_report", side_effect=RuntimeError("nope"))
    def test_anomalies_error(self, mock_report, mock_send, tmp_path: Path) -> None:
        _handle_bot_command(TOKEN, CHAT_ID, "/anomalies", tmp_path / "test.db")
        assert "Error" in mock_send.call_args[0][2]


# ---------------------------------------------------------------------------
# _handle_bot_command  —  /block_site  /unblock_site
# ---------------------------------------------------------------------------

class TestHandleBotCommandBlockSite:
    @patch("netorium.services.telegram_bot.send_telegram_message")
    @patch("netorium.services.telegram_bot.enqueue_agent_site_commands")
    def test_block_site_success(self, mock_enqueue, mock_send, tmp_path: Path) -> None:
        mock_enqueue.return_value = BatchAgentCommandResult(targets=("a1", "a2"), commands=())
        _handle_bot_command(TOKEN, CHAT_ID, "/block_site all youtube.com", tmp_path / "test.db")
        mock_enqueue.assert_called_once_with(
            tmp_path / "test.db",
            agent_selector="all",
            action="block",
            domain="youtube.com",
            reason="Blocked via Telegram Bot",
            dry_run=False,
        )
        text = mock_send.call_args[0][2]
        assert "2 agents" in text
        assert "youtube.com" in text

    @patch("netorium.services.telegram_bot.send_telegram_message")
    def test_block_site_missing_args(self, mock_send, tmp_path: Path) -> None:
        _handle_bot_command(TOKEN, CHAT_ID, "/block_site", tmp_path / "test.db")
        assert "Usage" in mock_send.call_args[0][2]

    @patch("netorium.services.telegram_bot.send_telegram_message")
    @patch("netorium.services.telegram_bot.enqueue_agent_site_commands", side_effect=RuntimeError("not found"))
    def test_block_site_error(self, mock_enqueue, mock_send, tmp_path: Path) -> None:
        _handle_bot_command(TOKEN, CHAT_ID, "/block_site pc-01 example.com", tmp_path / "test.db")
        assert "Command failed" in mock_send.call_args[0][2]

    @patch("netorium.services.telegram_bot.send_telegram_message")
    @patch("netorium.services.telegram_bot.enqueue_agent_site_commands")
    def test_unblock_site_success(self, mock_enqueue, mock_send, tmp_path: Path) -> None:
        mock_enqueue.return_value = BatchAgentCommandResult(targets=("a1",), commands=())
        _handle_bot_command(TOKEN, CHAT_ID, "/unblock_site pc-01 youtube.com", tmp_path / "test.db")
        mock_enqueue.assert_called_once_with(
            tmp_path / "test.db",
            agent_selector="pc-01",
            action="unblock",
            domain="youtube.com",
            reason="Unblocked via Telegram Bot",
            dry_run=False,
        )
        text = mock_send.call_args[0][2]
        assert "1 agents" in text

    @patch("netorium.services.telegram_bot.send_telegram_message")
    def test_unblock_site_missing_args(self, mock_send, tmp_path: Path) -> None:
        _handle_bot_command(TOKEN, CHAT_ID, "/unblock_site", tmp_path / "test.db")
        assert "Usage" in mock_send.call_args[0][2]


# ---------------------------------------------------------------------------
# _handle_bot_command  —  /block_game  /unblock_game
# ---------------------------------------------------------------------------

class TestHandleBotCommandBlockGame:
    @patch("netorium.services.telegram_bot.send_telegram_message")
    @patch("netorium.services.telegram_bot.enqueue_agent_app_commands")
    def test_block_game_success(self, mock_enqueue, mock_send, tmp_path: Path) -> None:
        mock_enqueue.return_value = BatchAgentCommandResult(targets=("a1",), commands=())
        _handle_bot_command(TOKEN, CHAT_ID, "/block_game all dota2.exe", tmp_path / "test.db")
        mock_enqueue.assert_called_once_with(
            tmp_path / "test.db",
            agent_selector="all",
            action="block",
            executable="dota2.exe",
            reason="Blocked via Telegram Bot",
            dry_run=False,
        )
        text = mock_send.call_args[0][2]
        assert "block command queued" in text
        assert "dota2.exe" in text

    @patch("netorium.services.telegram_bot.send_telegram_message")
    def test_block_game_missing_args(self, mock_send, tmp_path: Path) -> None:
        _handle_bot_command(TOKEN, CHAT_ID, "/block_game", tmp_path / "test.db")
        assert "Usage" in mock_send.call_args[0][2]

    @patch("netorium.services.telegram_bot.send_telegram_message")
    @patch("netorium.services.telegram_bot.enqueue_agent_app_commands", side_effect=RuntimeError("fail"))
    def test_block_game_error(self, mock_enqueue, mock_send, tmp_path: Path) -> None:
        _handle_bot_command(TOKEN, CHAT_ID, "/block_game pc-01 cs2.exe", tmp_path / "test.db")
        assert "Command failed" in mock_send.call_args[0][2]

    @patch("netorium.services.telegram_bot.send_telegram_message")
    @patch("netorium.services.telegram_bot.enqueue_agent_app_commands")
    def test_unblock_game_success(self, mock_enqueue, mock_send, tmp_path: Path) -> None:
        mock_enqueue.return_value = BatchAgentCommandResult(targets=("a1", "a2", "a3"), commands=())
        _handle_bot_command(TOKEN, CHAT_ID, "/unblock_game all dota2.exe", tmp_path / "test.db")
        mock_enqueue.assert_called_once_with(
            tmp_path / "test.db",
            agent_selector="all",
            action="unblock",
            executable="dota2.exe",
            reason="Unblocked via Telegram Bot",
            dry_run=False,
        )
        assert "3 agents" in mock_send.call_args[0][2]

    @patch("netorium.services.telegram_bot.send_telegram_message")
    def test_unblock_game_missing_args(self, mock_send, tmp_path: Path) -> None:
        _handle_bot_command(TOKEN, CHAT_ID, "/unblock_game pc-01", tmp_path / "test.db")
        assert "Usage" in mock_send.call_args[0][2]


# ---------------------------------------------------------------------------
# _handle_bot_command  —  /limit_speed  /clear_speed
# ---------------------------------------------------------------------------

class TestHandleBotCommandSpeed:
    @patch("netorium.services.telegram_bot.send_telegram_message")
    @patch("netorium.services.telegram_bot.enqueue_agent_speed_commands")
    def test_limit_speed_success(self, mock_enqueue, mock_send, tmp_path: Path) -> None:
        mock_enqueue.return_value = BatchAgentCommandResult(targets=("a1",), commands=())
        _handle_bot_command(TOKEN, CHAT_ID, "/limit_speed pc-01 5000 2000", tmp_path / "test.db")
        mock_enqueue.assert_called_once_with(
            tmp_path / "test.db",
            agent_selector="pc-01",
            download_kbps=5000,
            upload_kbps=2000,
            reason="Speed limit set via Telegram Bot",
            dry_run=False,
        )
        text = mock_send.call_args[0][2]
        assert "5000/2000 kbps" in text

    @patch("netorium.services.telegram_bot.send_telegram_message")
    def test_limit_speed_missing_args(self, mock_send, tmp_path: Path) -> None:
        _handle_bot_command(TOKEN, CHAT_ID, "/limit_speed pc-01 5000", tmp_path / "test.db")
        assert "Usage" in mock_send.call_args[0][2]

    @patch("netorium.services.telegram_bot.send_telegram_message")
    @patch("netorium.services.telegram_bot.enqueue_agent_speed_commands", side_effect=RuntimeError("boom"))
    def test_limit_speed_error(self, mock_enqueue, mock_send, tmp_path: Path) -> None:
        _handle_bot_command(TOKEN, CHAT_ID, "/limit_speed pc-01 5000 2000", tmp_path / "test.db")
        assert "Command failed" in mock_send.call_args[0][2]

    @patch("netorium.services.telegram_bot.send_telegram_message")
    @patch("netorium.services.telegram_bot.enqueue_agent_speed_commands")
    def test_clear_speed_success(self, mock_enqueue, mock_send, tmp_path: Path) -> None:
        mock_enqueue.return_value = BatchAgentCommandResult(targets=("a1",), commands=())
        _handle_bot_command(TOKEN, CHAT_ID, "/clear_speed pc-01", tmp_path / "test.db")
        mock_enqueue.assert_called_once_with(
            tmp_path / "test.db",
            agent_selector="pc-01",
            download_kbps=None,
            upload_kbps=None,
            clear=True,
            reason="Speed limit cleared via Telegram Bot",
            dry_run=False,
        )
        text = mock_send.call_args[0][2]
        assert "clear command queued" in text

    @patch("netorium.services.telegram_bot.send_telegram_message")
    def test_clear_speed_missing_args(self, mock_send, tmp_path: Path) -> None:
        _handle_bot_command(TOKEN, CHAT_ID, "/clear_speed", tmp_path / "test.db")
        assert "Usage" in mock_send.call_args[0][2]

    @patch("netorium.services.telegram_bot.send_telegram_message")
    @patch("netorium.services.telegram_bot.enqueue_agent_speed_commands", side_effect=RuntimeError("no"))
    def test_clear_speed_error(self, mock_enqueue, mock_send, tmp_path: Path) -> None:
        _handle_bot_command(TOKEN, CHAT_ID, "/clear_speed pc-01", tmp_path / "test.db")
        assert "Command failed" in mock_send.call_args[0][2]


# ---------------------------------------------------------------------------
# _handle_bot_command  —  unknown command
# ---------------------------------------------------------------------------

class TestHandleBotCommandUnknown:
    @patch("netorium.services.telegram_bot.send_telegram_message")
    def test_unknown_command(self, mock_send: MagicMock, tmp_path: Path) -> None:
        _handle_bot_command(TOKEN, CHAT_ID, "/foobar", tmp_path / "test.db")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "Unknown command" in text
        assert "/help" in text


# ---------------------------------------------------------------------------
# _check_traffic_anomalies
# ---------------------------------------------------------------------------

class TestCheckTrafficAnomalies:
    @patch("netorium.services.telegram_bot.send_telegram_message")
    @patch("netorium.services.telegram_bot.get_traffic_report")
    def test_new_anomaly_triggers_notification(self, mock_report, mock_send, tmp_path: Path) -> None:
        mock_report.return_value = [
            TrafficRecord(
                ip_address="10.0.0.5", hostname="bad-host", zone_name="zone1",
                download_mb=9999.0, upload_mb=500.0, total_mb=10499.0,
                is_anomaly=True, anomaly_reason="Huge download burst",
            ),
            TrafficRecord(
                ip_address="10.0.0.1", hostname="good-host", zone_name="zone1",
                download_mb=50.0, upload_mb=10.0, total_mb=60.0,
                is_anomaly=False,
            ),
        ]

        _check_traffic_anomalies(TOKEN, CHAT_ID, tmp_path / "test.db")

        # Only one anomaly notification should be sent
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "Anomaly Detected" in text
        assert "10.0.0.5" in text
        assert "bad-host" in text
        assert "Huge download burst" in text

        # IP should now be in NOTIFIED_IPS
        assert "10.0.0.5" in NOTIFIED_IPS

    @patch("netorium.services.telegram_bot.send_telegram_message")
    @patch("netorium.services.telegram_bot.get_traffic_report")
    def test_already_notified_ip_not_re_alerted(self, mock_report, mock_send, tmp_path: Path) -> None:
        NOTIFIED_IPS.add("10.0.0.5")

        mock_report.return_value = [
            TrafficRecord(
                ip_address="10.0.0.5", hostname="bad-host", zone_name="zone1",
                download_mb=9999.0, upload_mb=500.0, total_mb=10499.0,
                is_anomaly=True, anomaly_reason="Huge download burst",
            ),
        ]

        _check_traffic_anomalies(TOKEN, CHAT_ID, tmp_path / "test.db")

        # Should NOT send any notification since IP is already in NOTIFIED_IPS
        mock_send.assert_not_called()

    @patch("netorium.services.telegram_bot.send_telegram_message")
    @patch("netorium.services.telegram_bot.get_traffic_report")
    def test_resolved_anomaly_clears_notified_ip(self, mock_report, mock_send, tmp_path: Path) -> None:
        # Simulate that 10.0.0.5 was previously notified
        NOTIFIED_IPS.add("10.0.0.5")

        # Now traffic is normal — anomaly resolved
        mock_report.return_value = [
            TrafficRecord(
                ip_address="10.0.0.5", hostname="recovered-host", zone_name="zone1",
                download_mb=50.0, upload_mb=10.0, total_mb=60.0,
                is_anomaly=False,
            ),
        ]

        _check_traffic_anomalies(TOKEN, CHAT_ID, tmp_path / "test.db")

        # Should send a resolved notification
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "Traffic Normal" in text
        assert "10.0.0.5" in text

        # IP should be removed from NOTIFIED_IPS
        assert "10.0.0.5" not in NOTIFIED_IPS

    @patch("netorium.services.telegram_bot.send_telegram_message")
    @patch("netorium.services.telegram_bot.get_traffic_report")
    def test_no_anomalies_no_notifications(self, mock_report, mock_send, tmp_path: Path) -> None:
        mock_report.return_value = [
            TrafficRecord(
                ip_address="10.0.0.1", hostname="normal-host", zone_name="zone1",
                download_mb=50.0, upload_mb=10.0, total_mb=60.0,
                is_anomaly=False,
            ),
        ]

        _check_traffic_anomalies(TOKEN, CHAT_ID, tmp_path / "test.db")
        mock_send.assert_not_called()

    @patch("netorium.services.telegram_bot.send_telegram_message")
    @patch("netorium.services.telegram_bot.get_traffic_report")
    def test_multiple_new_anomalies(self, mock_report, mock_send, tmp_path: Path) -> None:
        mock_report.return_value = [
            TrafficRecord(
                ip_address="10.0.0.2", hostname="host-a", zone_name="zone1",
                download_mb=5000.0, upload_mb=500.0, total_mb=5500.0,
                is_anomaly=True, anomaly_reason="Burst A",
            ),
            TrafficRecord(
                ip_address="10.0.0.3", hostname="host-b", zone_name="zone2",
                download_mb=8000.0, upload_mb=200.0, total_mb=8200.0,
                is_anomaly=True, anomaly_reason="Burst B",
            ),
        ]

        _check_traffic_anomalies(TOKEN, CHAT_ID, tmp_path / "test.db")

        assert mock_send.call_count == 2
        all_texts = [c[0][2] for c in mock_send.call_args_list]
        assert any("10.0.0.2" in t for t in all_texts)
        assert any("10.0.0.3" in t for t in all_texts)
        assert "10.0.0.2" in NOTIFIED_IPS
        assert "10.0.0.3" in NOTIFIED_IPS

    @patch("netorium.services.telegram_bot.send_telegram_message")
    @patch("netorium.services.telegram_bot.get_traffic_report", side_effect=RuntimeError("db error"))
    def test_report_exception_handled_gracefully(self, mock_report, mock_send, tmp_path: Path) -> None:
        """If get_traffic_report raises, _check_traffic_anomalies should not crash."""
        _check_traffic_anomalies(TOKEN, CHAT_ID, tmp_path / "test.db")
        mock_send.assert_not_called()

    @patch("netorium.services.telegram_bot.send_telegram_message")
    @patch("netorium.services.telegram_bot.get_traffic_report")
    def test_mixed_new_and_resolved(self, mock_report, mock_send, tmp_path: Path) -> None:
        """Test a cycle where one IP resolves and a new IP appears anomalous."""
        NOTIFIED_IPS.add("10.0.0.1")  # previously anomalous

        mock_report.return_value = [
            # 10.0.0.1 recovered
            TrafficRecord(
                ip_address="10.0.0.1", hostname="host-recovered", zone_name="zone1",
                download_mb=50.0, upload_mb=10.0, total_mb=60.0,
                is_anomaly=False,
            ),
            # 10.0.0.9 is newly anomalous
            TrafficRecord(
                ip_address="10.0.0.9", hostname="host-new-bad", zone_name="zone2",
                download_mb=7000.0, upload_mb=300.0, total_mb=7300.0,
                is_anomaly=True, anomaly_reason="Spike",
            ),
        ]

        _check_traffic_anomalies(TOKEN, CHAT_ID, tmp_path / "test.db")

        # Two notifications: one new anomaly, one resolved
        assert mock_send.call_count == 2
        all_texts = [c[0][2] for c in mock_send.call_args_list]
        assert any("Anomaly Detected" in t and "10.0.0.9" in t for t in all_texts)
        assert any("Traffic Normal" in t and "10.0.0.1" in t for t in all_texts)

        assert "10.0.0.9" in NOTIFIED_IPS
        assert "10.0.0.1" not in NOTIFIED_IPS
