from __future__ import annotations

import time
import requests
import logging
from pathlib import Path

from netorium.services.controller import (
    get_controller_status,
    list_agents,
    list_agent_commands,
    enqueue_agent_site_commands,
    enqueue_agent_app_commands,
    enqueue_agent_speed_commands,
)
from netorium.services.traffic import get_traffic_report

logger = logging.getLogger(__name__)

# Keep track of notified anomalous IPs to prevent alert fatigue
NOTIFIED_IPS: set[str] = set()

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
            logger.error(f"Failed to send Telegram message: HTTP {response.status_code}")
    except Exception as exc:
        logger.error(f"Telegram sendMessage error: {exc}")

def start_telegram_bot(token: str, chat_id: str, db_path: Path) -> None:
    """
    Start the Telegram bot long polling loop.
    Processes messages from the configured admin chat_id and runs periodic anomaly monitoring.
    """
    print(f"Starting Netorium Telegram bot (monitoring anomalies, authorized chat ID: {chat_id})...")
    print("Press Ctrl+C to stop the bot and exit.")
    
    # Send a startup notification
    send_telegram_message(
        token,
        chat_id,
        "🟢 <b>Netorium Telegram Bot is online.</b>\nType /help to see available commands."
    )

    offset = 0
    last_anomaly_check = 0.0

    while True:
        try:
            # 1. Periodic anomaly monitoring check (every 15 seconds)
            now = time.time()
            if now - last_anomaly_check > 15:
                last_anomaly_check = now
                _check_traffic_anomalies(token, chat_id, db_path)

            # 2. Get updates (long polling)
            url = f"https://api.telegram.org/bot{token}/getUpdates"
            try:
                response = requests.get(
                    url,
                    params={"offset": offset, "timeout": 5},
                    timeout=10,
                )
            except requests.RequestException:
                # Network glitch or timeout, just continue
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

                # Verify sender chat ID matches the configured admin chat ID
                if msg_chat_id != chat_id:
                    logger.warning(f"Unauthorized chat ID {msg_chat_id} tried to send command: {text}")
                    # Send an unauthorized response back
                    _send_unauthorized_reply(token, msg_chat_id)
                    continue

                if not text.startswith("/"):
                    continue

                _handle_bot_command(token, chat_id, text, db_path)

        except KeyboardInterrupt:
            print("\nStopping Telegram bot...")
            send_telegram_message(token, chat_id, "🔴 <b>Netorium Telegram Bot is going offline.</b>")
            break
        except Exception as exc:
            logger.error(f"Error in Telegram bot main loop: {exc}")
            time.sleep(2)

def _send_unauthorized_reply(token: str, chat_id: str) -> None:
    text = "⚠️ <b>Access Denied.</b> Your chat ID is not authorized to interact with this Netorium instance."
    send_telegram_message(token, chat_id, text)

def _check_traffic_anomalies(token: str, chat_id: str, db_path: Path) -> None:
    """Scan device traffic, notify about new anomalies, and clear resolved ones."""
    try:
        records = get_traffic_report(db_path)
    except Exception as exc:
        logger.error(f"Anomaly check failed to query traffic report: {exc}")
        return

    current_anomalies = {r.ip_address for r in records if r.is_anomaly}
    
    # Check for new anomalies
    for r in records:
        if r.is_anomaly and r.ip_address not in NOTIFIED_IPS:
            NOTIFIED_IPS.add(r.ip_address)
            msg = (
                f"🚨 <b>Traffic Anomaly Detected!</b>\n\n"
                f"<b>IP:</b> {r.ip_address}\n"
                f"<b>Hostname:</b> {r.hostname}\n"
                f"<b>Zone:</b> {r.zone_name}\n"
                f"<b>Total Usage:</b> {r.total_mb:.2f} MB\n"
                f"<b>Details:</b> {r.anomaly_reason}\n\n"
                f"<i>You can use /limit_speed or /block_site to reduce their speed or block traffic.</i>"
            )
            send_telegram_message(token, chat_id, msg)

    # Clean up resolved anomalies from notified set
    resolved_ips = NOTIFIED_IPS - current_anomalies
    for ip in resolved_ips:
        NOTIFIED_IPS.remove(ip)
        # Notify that the anomaly resolved/restored
        send_telegram_message(token, chat_id, f"✅ <b>Traffic Normal:</b> Device at {ip} has returned to normal limits.")

def _handle_bot_command(token: str, chat_id: str, text: str, db_path: Path) -> None:
    parts = text.split()
    command = parts[0].lower()

    if command in ("/start", "/help"):
        help_text = (
            "🤖 <b>Netorium Admin Bot Commands:</b>\n\n"
            "📊 <b>Status & Monitoring:</b>\n"
            "/status - View Controller status\n"
            "/agents - List enrolled endpoint agents\n"
            "/policies - List queued and completed commands\n"
            "/traffic - Get current traffic report\n"
            "/anomalies - View active traffic anomalies\n\n"
            "🛡️ <b>Access Policies:</b>\n"
            "/block_site <code>&lt;target&gt;</code> <code>&lt;domain&gt;</code> - Block site (e.g. <code>/block_site pc-acc-01 youtube.com</code>)\n"
            "/unblock_site <code>&lt;target&gt;</code> <code>&lt;domain&gt;</code> - Unblock site\n"
            "/block_game <code>&lt;target&gt;</code> <code>&lt;exe&gt;</code> - Block application (e.g. <code>/block_game all dota2.exe</code>)\n"
            "/unblock_game <code>&lt;target&gt;</code> <code>&lt;exe&gt;</code> - Unblock application\n"
            "/limit_speed <code>&lt;target&gt;</code> <code>&lt;down&gt;</code> <code>&lt;up&gt;</code> - Limit speed in kbps\n"
            "/clear_speed <code>&lt;target&gt;</code> - Clear speed limit\n"
        )
        send_telegram_message(token, chat_id, help_text)

    elif command == "/status":
        try:
            status = get_controller_status(db_path)
            status_text = (
                f"ℹ️ <b>Netorium Status:</b>\n\n"
                f"<b>Listen URL:</b> http://{status.host}:{status.port}\n"
                f"<b>Active Tokens:</b> {status.active_tokens}\n"
                f"<b>Enrolled Agents:</b> {len(list_agents(db_path))}"
            )
            send_telegram_message(token, chat_id, status_text)
        except Exception as exc:
            send_telegram_message(token, chat_id, f"❌ Error retrieving status: {exc}")

    elif command == "/agents":
        try:
            agents = list_agents(db_path)
            if not agents:
                send_telegram_message(token, chat_id, "ℹ️ No agents enrolled yet.")
                return
            
            lines = ["👥 <b>Enrolled Agents:</b>"]
            for a in agents:
                last_seen = a.last_seen_at or "never"
                lines.append(f"• <code>{a.agent_id}</code> | <b>{a.hostname}</b> | Zone: {a.zone} | Last seen: {last_seen}")
            send_telegram_message(token, chat_id, "\n".join(lines))
        except Exception as exc:
            send_telegram_message(token, chat_id, f"❌ Error: {exc}")

    elif command == "/policies":
        try:
            commands = list_agent_commands(db_path)
            if not commands:
                send_telegram_message(token, chat_id, "ℹ️ No policy commands queued or completed.")
                return
            
            lines = ["📋 <b>Recent Policy Commands:</b>"]
            # Show last 10 commands to keep message size reasonable
            for cmd in commands[-10:]:
                lines.append(f"• ID: <code>{cmd.command_id}</code> | Agent: <code>{cmd.agent_id}</code> | {cmd.command_type} | <b>{cmd.status}</b>")
            send_telegram_message(token, chat_id, "\n".join(lines))
        except Exception as exc:
            send_telegram_message(token, chat_id, f"❌ Error: {exc}")

    elif command == "/traffic":
        try:
            records = get_traffic_report(db_path)
            if not records:
                send_telegram_message(token, chat_id, "ℹ️ No traffic data available.")
                return
            
            lines = ["📊 <b>Traffic Report:</b>"]
            for r in records:
                traffic_status = "⚠️ Anomaly" if r.is_anomaly else "OK"
                lines.append(f"• <b>{r.hostname}</b> ({r.ip_address}) | Down: {r.download_mb:.1f} MB | Up: {r.upload_mb:.1f} MB | {traffic_status}")
            send_telegram_message(token, chat_id, "\n".join(lines))
        except Exception as exc:
            send_telegram_message(token, chat_id, f"❌ Error: {exc}")

    elif command == "/anomalies":
        try:
            records = get_traffic_report(db_path)
            anomalies = [r for r in records if r.is_anomaly]
            if not anomalies:
                send_telegram_message(token, chat_id, "✅ No active traffic anomalies detected.")
                return
            
            lines = ["🚨 <b>Active Traffic Anomalies:</b>"]
            for r in anomalies:
                lines.append(f"• <b>{r.hostname}</b> | {r.zone_name} | {r.total_mb:.1f} MB | {r.anomaly_reason}")
            send_telegram_message(token, chat_id, "\n".join(lines))
        except Exception as exc:
            send_telegram_message(token, chat_id, f"❌ Error: {exc}")

    elif command == "/block_site":
        if len(parts) < 3:
            send_telegram_message(token, chat_id, "❌ Usage: /block_site &lt;target&gt; &lt;domain&gt;")
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
                f"✅ Site block command queued for {len(result.targets)} agents (target: {target}, domain: {domain})."
            )
        except Exception as exc:
            send_telegram_message(token, chat_id, f"❌ Command failed: {exc}")

    elif command == "/unblock_site":
        if len(parts) < 3:
            send_telegram_message(token, chat_id, "❌ Usage: /unblock_site &lt;target&gt; &lt;domain&gt;")
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
                f"✅ Site unblock command queued for {len(result.targets)} agents (target: {target}, domain: {domain})."
            )
        except Exception as exc:
            send_telegram_message(token, chat_id, f"❌ Command failed: {exc}")

    elif command == "/block_game":
        if len(parts) < 3:
            send_telegram_message(token, chat_id, "❌ Usage: /block_game &lt;target&gt; &lt;exe&gt;")
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
                f"✅ Game/App block command queued for {len(result.targets)} agents (target: {target}, exe: {exe})."
            )
        except Exception as exc:
            send_telegram_message(token, chat_id, f"❌ Command failed: {exc}")

    elif command == "/unblock_game":
        if len(parts) < 3:
            send_telegram_message(token, chat_id, "❌ Usage: /unblock_game &lt;target&gt; &lt;exe&gt;")
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
                f"✅ Game/App unblock command queued for {len(result.targets)} agents (target: {target}, exe: {exe})."
            )
        except Exception as exc:
            send_telegram_message(token, chat_id, f"❌ Command failed: {exc}")

    elif command == "/limit_speed":
        if len(parts) < 4:
            send_telegram_message(token, chat_id, "❌ Usage: /limit_speed &lt;target&gt; &lt;down_kbps&gt; &lt;upload_kbps&gt;")
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
                f"✅ Speed limit ({down}/{up} kbps) command queued for {len(result.targets)} agents (target: {target})."
            )
        except Exception as exc:
            send_telegram_message(token, chat_id, f"❌ Command failed: {exc}")

    elif command == "/clear_speed":
        if len(parts) < 2:
            send_telegram_message(token, chat_id, "❌ Usage: /clear_speed &lt;target&gt;")
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
                f"✅ Speed limit clear command queued for {len(result.targets)} agents (target: {target})."
            )
        except Exception as exc:
            send_telegram_message(token, chat_id, f"❌ Command failed: {exc}")

    else:
        send_telegram_message(token, chat_id, "❓ Unknown command. Type /help to see list of valid commands.")
