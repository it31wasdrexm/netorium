from __future__ import annotations

import logging
import time
from pathlib import Path

import requests

from netorium.core.settings import MonitoringSettings, default_config_path, read_config_data
from netorium.services.controller import (
    get_controller_status,
    list_agents,
    list_agent_commands,
    enqueue_agent_site_commands,
    enqueue_agent_app_commands,
    enqueue_agent_speed_commands,
)
from netorium.services.traffic_monitor import (
    TrafficMonitorError,
    detect_traffic_anomalies,
    format_bytes,
    list_recent_traffic_usage,
)

logger = logging.getLogger(__name__)

_ANOMALY_COOLDOWN_SECONDS = 300


def send_telegram_message(token: str, chat_id: str, text: str) -> None:
    """Send a message to a specific chat ID using the bot token."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        response = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        if response.status_code != 200:
            logger.error("Failed to send Telegram message: HTTP %s", response.status_code)
    except Exception as exc:
        logger.error("Telegram sendMessage error: %s", exc)


def start_telegram_bot(token: str, chat_id: str, db_path: Path) -> None:
    """Start Telegram long polling and periodic traffic anomaly monitoring."""
    monitoring = _load_monitoring_settings(db_path)
    print(f"Starting Netorium Telegram bot (authorized chat ID: {chat_id})...")
    print("Press Ctrl+C to stop the bot and exit.")

    send_telegram_message(
        token,
        chat_id,
        "<b>Netorium Telegram Bot is online.</b>\n"
        "Type /help to see available commands.\n"
        f"Traffic anomaly threshold: {monitoring.traffic_anomaly_threshold_mb} MB.",
    )

    offset = 0
    last_anomaly_check = 0.0
    notified_anomalies: dict[str, float] = {}

    while True:
        try:
            now = time.monotonic()
            if now - last_anomaly_check >= monitoring.traffic_check_interval_seconds:
                _check_traffic_anomalies(
                    token,
                    chat_id,
                    db_path,
                    monitoring=monitoring,
                    notified_anomalies=notified_anomalies,
                    now=now,
                )
                last_anomaly_check = now

            url = f"https://api.telegram.org/bot{token}/getUpdates"
            try:
                response = requests.get(
                    url,
                    params={"offset": offset, "timeout": 5},
                    timeout=10,
                )
            except requests.RequestException:
                time.sleep(1)
                continue

            if response.status_code != 200:
                time.sleep(2)
                continue

            payload = response.json()
            if not payload.get("ok"):
                time.sleep(2)
                continue

            for update in payload.get("result", []):
                update_id = update["update_id"]
                offset = update_id + 1

                message = update.get("message")
                if not message:
                    continue

                msg_chat = message.get("chat", {})
                msg_chat_id = str(msg_chat.get("id", ""))
                text = message.get("text", "").strip()

                if msg_chat_id != chat_id:
                    logger.warning("Unauthorized chat ID %s tried to send command: %s", msg_chat_id, text)
                    _send_unauthorized_reply(token, msg_chat_id)
                    continue

                if not text.startswith("/"):
                    continue

                _handle_bot_command(token, chat_id, text, db_path)

        except KeyboardInterrupt:
            print("\nStopping Telegram bot...")
            send_telegram_message(token, chat_id, "<b>Netorium Telegram Bot is going offline.</b>")
            break
        except Exception as exc:
            logger.error("Error in Telegram bot main loop: %s", exc)
            time.sleep(2)


def _load_monitoring_settings(db_path: Path) -> MonitoringSettings:
    config_path = default_config_path()
    try:
        data = read_config_data(config_path)
    except Exception:
        return MonitoringSettings()
    monitoring = data.get("monitoring")
    if not isinstance(monitoring, dict):
        return MonitoringSettings()
    try:
        return MonitoringSettings.model_validate(monitoring)
    except Exception:
        return MonitoringSettings()


def _check_traffic_anomalies(
    token: str,
    chat_id: str,
    db_path: Path,
    *,
    monitoring: MonitoringSettings,
    notified_anomalies: dict[str, float],
    now: float,
) -> None:
    try:
        anomalies = detect_traffic_anomalies(
            db_path,
            threshold_mb=monitoring.traffic_anomaly_threshold_mb,
            window_minutes=monitoring.traffic_window_minutes,
        )
    except TrafficMonitorError as exc:
        logger.error("Traffic anomaly check failed: %s", exc)
        return

    for anomaly in anomalies:
        last_notified = notified_anomalies.get(anomaly.agent_id)
        if last_notified is not None and now - last_notified < _ANOMALY_COOLDOWN_SECONDS:
            continue
        notified_anomalies[anomaly.agent_id] = now
        send_telegram_message(
            token,
            chat_id,
            "<b>Traffic anomaly detected</b>\n"
            f"Agent: <code>{anomaly.agent_id}</code>\n"
            f"Host: <b>{anomaly.hostname}</b>\n"
            f"Usage: <b>{format_bytes(anomaly.total_bytes)}</b> "
            f"(threshold {format_bytes(anomaly.threshold_bytes)})\n"
            f"Window: {anomaly.window_start} -> {anomaly.window_end}\n"
            "Possible large download or upload activity.",
        )


def _send_unauthorized_reply(token: str, chat_id: str) -> None:
    text = "<b>Access Denied.</b> Your chat ID is not authorized to interact with this Netorium instance."
    send_telegram_message(token, chat_id, text)


def _handle_bot_command(token: str, chat_id: str, text: str, db_path: Path) -> None:
    parts = text.split()
    command = parts[0].lower()

    if command in ("/start", "/help"):
        help_text = (
            "<b>Netorium Admin Bot Commands</b>\n\n"
            "<b>Status and monitoring</b>\n"
            "/status - Controller status\n"
            "/agents - Enrolled endpoint agents\n"
            "/policies - Recent policy commands\n"
            "/traffic - Recent traffic usage\n\n"
            "<b>Access policies</b>\n"
            "/block_site <code>&lt;target&gt;</code> <code>&lt;domain&gt;</code>\n"
            "/unblock_site <code>&lt;target&gt;</code> <code>&lt;domain&gt;</code>\n"
            "/block_game <code>&lt;target&gt;</code> <code>&lt;exe&gt;</code>\n"
            "/unblock_game <code>&lt;target&gt;</code> <code>&lt;exe&gt;</code>\n"
            "/limit_speed <code>&lt;target&gt;</code> <code>&lt;down&gt;</code> <code>&lt;up&gt;</code>\n"
            "/clear_speed <code>&lt;target&gt;</code>\n\n"
            "Use <code>all</code> as target to apply to every enrolled agent."
        )
        send_telegram_message(token, chat_id, help_text)

    elif command == "/status":
        try:
            status = get_controller_status(db_path)
            listen_url = status.listen_url or "not configured"
            send_telegram_message(
                token,
                chat_id,
                "<b>Netorium Status</b>\n\n"
                f"<b>Listen URL:</b> {listen_url}\n"
                f"<b>Active Tokens:</b> {status.active_tokens}\n"
                f"<b>Enrolled Agents:</b> {len(list_agents(db_path))}",
            )
        except Exception as exc:
            send_telegram_message(token, chat_id, f"Error retrieving status: {exc}")

    elif command == "/agents":
        try:
            agents = list_agents(db_path)
            if not agents:
                send_telegram_message(token, chat_id, "No agents enrolled yet.")
                return

            lines = ["<b>Enrolled Agents</b>"]
            for agent in agents:
                last_seen = agent.last_seen_at or "never"
                lines.append(
                    f"- <code>{agent.agent_id}</code> | <b>{agent.hostname}</b> | "
                    f"Zone: {agent.zone or '-'} | Last seen: {last_seen}"
                )
            send_telegram_message(token, chat_id, "\n".join(lines))
        except Exception as exc:
            send_telegram_message(token, chat_id, f"Error: {exc}")

    elif command == "/traffic":
        try:
            monitoring = _load_monitoring_settings(db_path)
            rows = list_recent_traffic_usage(
                db_path,
                window_minutes=monitoring.traffic_window_minutes,
            )
            if not rows:
                send_telegram_message(token, chat_id, "No traffic samples yet.")
                return
            lines = [f"<b>Traffic ({monitoring.traffic_window_minutes} min)</b>"]
            for row in rows[:10]:
                lines.append(
                    f"- <b>{row.hostname}</b>: down {format_bytes(row.bytes_received)}, "
                    f"up {format_bytes(row.bytes_sent)}, total {format_bytes(row.total_bytes)}"
                )
            send_telegram_message(token, chat_id, "\n".join(lines))
        except Exception as exc:
            send_telegram_message(token, chat_id, f"Error: {exc}")

    elif command == "/policies":
        try:
            commands = list_agent_commands(db_path)
            if not commands:
                send_telegram_message(token, chat_id, "No policy commands queued or completed.")
                return

            lines = ["<b>Recent Policy Commands</b>"]
            for cmd in commands[-10:]:
                lines.append(
                    f"- ID: <code>{cmd.command_id}</code> | Agent: <code>{cmd.agent_id}</code> | "
                    f"{cmd.command_type} | <b>{cmd.status}</b>"
                )
            send_telegram_message(token, chat_id, "\n".join(lines))
        except Exception as exc:
            send_telegram_message(token, chat_id, f"Error: {exc}")

    elif command == "/block_site":
        if len(parts) < 3:
            send_telegram_message(token, chat_id, "Usage: /block_site &lt;target&gt; &lt;domain&gt;")
            return
        target, domain = parts[1], parts[2]
        try:
            result = enqueue_agent_site_commands(
                db_path,
                agent_selector=target,
                action="block",
                domain=domain,
                reason="Blocked via Telegram Bot",
                dry_run=False,
            )
            send_telegram_message(
                token,
                chat_id,
                f"Site block queued for {len(result.targets)} agent(s) "
                f"(target: {target}, domain: {domain}).",
            )
        except Exception as exc:
            send_telegram_message(token, chat_id, f"Command failed: {exc}")

    elif command == "/unblock_site":
        if len(parts) < 3:
            send_telegram_message(token, chat_id, "Usage: /unblock_site &lt;target&gt; &lt;domain&gt;")
            return
        target, domain = parts[1], parts[2]
        try:
            result = enqueue_agent_site_commands(
                db_path,
                agent_selector=target,
                action="unblock",
                domain=domain,
                reason="Unblocked via Telegram Bot",
                dry_run=False,
            )
            send_telegram_message(
                token,
                chat_id,
                f"Site unblock queued for {len(result.targets)} agent(s) "
                f"(target: {target}, domain: {domain}).",
            )
        except Exception as exc:
            send_telegram_message(token, chat_id, f"Command failed: {exc}")

    elif command == "/block_game":
        if len(parts) < 3:
            send_telegram_message(token, chat_id, "Usage: /block_game &lt;target&gt; &lt;exe&gt;")
            return
        target, exe = parts[1], parts[2]
        try:
            result = enqueue_agent_app_commands(
                db_path,
                agent_selector=target,
                action="block",
                executable=exe,
                reason="Blocked via Telegram Bot",
                dry_run=False,
            )
            send_telegram_message(
                token,
                chat_id,
                f"App block queued for {len(result.targets)} agent(s) "
                f"(target: {target}, exe: {exe}).",
            )
        except Exception as exc:
            send_telegram_message(token, chat_id, f"Command failed: {exc}")

    elif command == "/unblock_game":
        if len(parts) < 3:
            send_telegram_message(token, chat_id, "Usage: /unblock_game &lt;target&gt; &lt;exe&gt;")
            return
        target, exe = parts[1], parts[2]
        try:
            result = enqueue_agent_app_commands(
                db_path,
                agent_selector=target,
                action="unblock",
                executable=exe,
                reason="Unblocked via Telegram Bot",
                dry_run=False,
            )
            send_telegram_message(
                token,
                chat_id,
                f"App unblock queued for {len(result.targets)} agent(s) "
                f"(target: {target}, exe: {exe}).",
            )
        except Exception as exc:
            send_telegram_message(token, chat_id, f"Command failed: {exc}")

    elif command == "/limit_speed":
        if len(parts) < 4:
            send_telegram_message(
                token,
                chat_id,
                "Usage: /limit_speed &lt;target&gt; &lt;down_kbps&gt; &lt;upload_kbps&gt;",
            )
            return
        target, down, up = parts[1], parts[2], parts[3]
        try:
            result = enqueue_agent_speed_commands(
                db_path,
                agent_selector=target,
                download_kbps=int(down),
                upload_kbps=int(up),
                reason="Speed limit set via Telegram Bot",
                dry_run=False,
            )
            send_telegram_message(
                token,
                chat_id,
                f"Speed limit ({down}/{up} kbps) queued for {len(result.targets)} agent(s).",
            )
        except Exception as exc:
            send_telegram_message(token, chat_id, f"Command failed: {exc}")

    elif command == "/clear_speed":
        if len(parts) < 2:
            send_telegram_message(token, chat_id, "Usage: /clear_speed &lt;target&gt;")
            return
        target = parts[1]
        try:
            result = enqueue_agent_speed_commands(
                db_path,
                agent_selector=target,
                download_kbps=None,
                upload_kbps=None,
                clear=True,
                reason="Speed limit cleared via Telegram Bot",
                dry_run=False,
            )
            send_telegram_message(
                token,
                chat_id,
                f"Speed limit clear queued for {len(result.targets)} agent(s).",
            )
        except Exception as exc:
            send_telegram_message(token, chat_id, f"Command failed: {exc}")

    else:
        send_telegram_message(token, chat_id, "Unknown command. Type /help to see valid commands.")
