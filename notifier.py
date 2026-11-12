"""
CC TV — Notification System
Handles real-time notifications via:
1. WebSocket (Live browser updates)
2. Telegram Bot (Photos & Alerts direct to your phone)
3. WhatsApp (Twilio or Meta Cloud API)
4. Custom Webhooks (Home Assistant, Pushover, N8N, etc.)
"""
import os
import json
import time
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    import urllib.request
    import urllib.error
    HAS_URLLIB = True
except ImportError:
    HAS_URLLIB = False

logger = logging.getLogger(__name__)


class Notifier:
    """Manages multi-channel real-time notifications."""

    def __init__(self, socketio=None, config=None):
        self.socketio = socketio
        self.config = config
        self.webhook_urls = []
        self._history = []  # Recent notifications for the dashboard
        self._max_history = 100
        self._lock = threading.Lock()

    def set_socketio(self, socketio):
        """Set the SocketIO instance (called after app creation)."""
        self.socketio = socketio

    def set_config(self, config):
        """Set or update app config."""
        self.config = config

    def add_webhook(self, url: str):
        """Add a custom webhook URL."""
        if url and url not in self.webhook_urls:
            self.webhook_urls.append(url)

    def remove_webhook(self, url: str):
        """Remove a custom webhook URL."""
        if url in self.webhook_urls:
            self.webhook_urls.remove(url)

    def notify(self, event_type: str, camera_id: int, camera_name: str,
               confidence: float = 0.0, snapshot_path: Optional[str] = None,
               details: Optional[str] = None, track_id: Optional[int] = None,
               snapshot_url: Optional[str] = None):
        """
        Send a notification across all enabled channels:
        WebSocket, Telegram, WhatsApp, and Webhooks.
        """
        # Resolve snapshot link: public URL (Supabase) or local path
        display_snapshot = snapshot_url or snapshot_path

        notification = {
            "type": event_type,
            "track_id": track_id,
            "camera_id": camera_id,
            "camera_name": camera_name,
            "confidence": round(confidence, 3),
            "snapshot_path": display_snapshot,
            "details": details,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Store in local history
        with self._lock:
            self._history.insert(0, notification)
            if len(self._history) > self._max_history:
                self._history = self._history[:self._max_history]

        # 1. WebSocket broadcast (real-time in dashboard)
        if self.socketio:
            try:
                self.socketio.emit("detection_event", notification)
            except Exception as e:
                logger.error(f"WebSocket notification error: {e}")

        # 2. Telegram Bot notification (async)
        if self.config and getattr(self.config, "TELEGRAM_ENABLED", False):
            threading.Thread(
                target=self._send_telegram,
                args=(notification, snapshot_path, snapshot_url),
                daemon=True
            ).start()

        # 3. WhatsApp notification (async)
        if self.config and getattr(self.config, "WHATSAPP_ENABLED", False):
            threading.Thread(
                target=self._send_whatsapp,
                args=(notification, snapshot_url),
                daemon=True
            ).start()

        # 4. Custom Webhooks (async)
        if self.webhook_urls:
            threading.Thread(
                target=self._fire_webhooks,
                args=(notification,),
                daemon=True
            ).start()

        track_str = f" [Track #{track_id}]" if track_id else ""
        logger.info(
            f"Notification sent: {event_type}{track_str} on {camera_name} "
            f"({confidence:.0%})"
        )

    def _send_telegram(self, notification: dict, local_snapshot_path: Optional[str],
                       remote_snapshot_url: Optional[str]):
        """Deliver alert to Telegram with photo snapshot."""
        if not HAS_REQUESTS:
            logger.warning("Requests library not available for Telegram notification.")
            return

        token = getattr(self.config, "TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = getattr(self.config, "TELEGRAM_CHAT_ID", "").strip()

        if not token or not chat_id:
            logger.debug("Telegram credentials not configured; skipping.")
            return

        event_type = notification["type"].upper()
        cam_name = notification["camera_name"]
        track_info = f" (ID #{notification['track_id']})" if notification.get("track_id") else ""
        conf = f"{notification['confidence']:.0%}"
        now_str = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")

        caption = (
            f"🚨 *CCTV ALERT: {event_type}{track_info}*\n"
            f"📹 *Camera:* {cam_name}\n"
            f"🎯 *Confidence:* {conf}\n"
            f"🕒 *Time:* {now_str}"
        )

        # Try sending photo first
        photo_sent = False

        # Case A: Remote Supabase URL
        if remote_snapshot_url and remote_snapshot_url.startswith("http"):
            try:
                url = f"https://api.telegram.org/bot{token}/sendPhoto"
                payload = {
                    "chat_id": chat_id,
                    "photo": remote_snapshot_url,
                    "caption": caption,
                    "parse_mode": "Markdown",
                }
                resp = requests.post(url, data=payload, timeout=12)
                if resp.status_code == 200:
                    photo_sent = True
                    logger.info("Telegram photo alert sent via public URL.")
            except Exception as e:
                logger.warning(f"Failed to send Telegram photo via URL: {e}")

        # Case B: Local snapshot file
        if not photo_sent and local_snapshot_path:
            # Resolve full local path if relative
            full_path = local_snapshot_path
            if not os.path.isabs(full_path) and hasattr(self.config, "SNAPSHOTS_DIR"):
                full_path = os.path.join(self.config.SNAPSHOTS_DIR, local_snapshot_path)

            if os.path.exists(full_path):
                try:
                    url = f"https://api.telegram.org/bot{token}/sendPhoto"
                    with open(full_path, "rb") as photo_file:
                        files = {"photo": photo_file}
                        data = {
                            "chat_id": chat_id,
                            "caption": caption,
                            "parse_mode": "Markdown",
                        }
                        resp = requests.post(url, data=data, files=files, timeout=15)
                        if resp.status_code == 200:
                            photo_sent = True
                            logger.info("Telegram photo alert sent via file upload.")
                except Exception as e:
                    logger.warning(f"Failed to upload Telegram photo file: {e}")

        # Fallback to text message if photo couldn't be sent
        if not photo_sent:
            try:
                url = f"https://api.telegram.org/bot{token}/sendMessage"
                payload = {
                    "chat_id": chat_id,
                    "text": caption,
                    "parse_mode": "Markdown",
                }
                requests.post(url, json=payload, timeout=10)
                logger.info("Telegram text alert sent.")
            except Exception as e:
                logger.error(f"Failed to send Telegram message: {e}")

    def _send_whatsapp(self, notification: dict, snapshot_url: Optional[str]):
        """Deliver alert to WhatsApp via Twilio or Meta Cloud API."""
        if not HAS_REQUESTS:
            return

        provider = getattr(self.config, "WHATSAPP_PROVIDER", "twilio").lower()
        event_type = notification["type"].capitalize()
        cam_name = notification["camera_name"]
        track_info = f" (ID #{notification['track_id']})" if notification.get("track_id") else ""
        conf = f"{notification['confidence']:.0%}"
        now_str = datetime.now().strftime("%I:%M %p")

        message = (
            f"🚨 *CCTV Alert*: {event_type}{track_info} detected on *{cam_name}* "
            f"at {now_str} (Confidence: {conf})"
        )

        if provider == "twilio":
            account_sid = getattr(self.config, "TWILIO_ACCOUNT_SID", "").strip()
            auth_token = getattr(self.config, "TWILIO_AUTH_TOKEN", "").strip()
            from_number = getattr(self.config, "TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886").strip()
            to_number = getattr(self.config, "WHATSAPP_TO", "").strip()

            if not account_sid or not auth_token or not to_number:
                logger.debug("Twilio WhatsApp credentials missing; skipping.")
                return

            if not from_number.startswith("whatsapp:"):
                from_number = f"whatsapp:{from_number}"
            if not to_number.startswith("whatsapp:"):
                to_number = f"whatsapp:{to_number}"

            try:
                url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
                data = {
                    "From": from_number,
                    "To": to_number,
                    "Body": message,
                }
                # Attach public image URL if available (e.g. from Supabase Storage)
                if snapshot_url and snapshot_url.startswith("http"):
                    data["MediaUrl"] = snapshot_url

                resp = requests.post(url, data=data, auth=(account_sid, auth_token), timeout=12)
                if resp.status_code in (200, 201):
                    logger.info("WhatsApp notification delivered via Twilio.")
                else:
                    logger.warning(f"Twilio WhatsApp failed ({resp.status_code}): {resp.text}")
            except Exception as e:
                logger.error(f"Twilio WhatsApp dispatch error: {e}")

        elif provider == "meta":
            token = getattr(self.config, "META_WHATSAPP_TOKEN", "").strip()
            phone_id = getattr(self.config, "META_WHATSAPP_PHONE_ID", "").strip()
            to_number = getattr(self.config, "WHATSAPP_TO", "").replace("whatsapp:", "").replace("+", "").strip()

            if not token or not phone_id or not to_number:
                logger.debug("Meta WhatsApp credentials missing; skipping.")
                return

            try:
                url = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "messaging_product": "whatsapp",
                    "to": to_number,
                    "type": "text",
                    "text": {"body": message}
                }
                resp = requests.post(url, headers=headers, json=payload, timeout=12)
                if resp.status_code == 200:
                    logger.info("WhatsApp notification delivered via Meta Cloud API.")
                else:
                    logger.warning(f"Meta WhatsApp failed ({resp.status_code}): {resp.text}")
            except Exception as e:
                logger.error(f"Meta WhatsApp dispatch error: {e}")

    def _fire_webhooks(self, notification: dict):
        """Send notification to all custom webhook URLs."""
        if not HAS_URLLIB and not HAS_REQUESTS:
            return

        payload = json.dumps(notification).encode("utf-8")

        for url in self.webhook_urls:
            try:
                req = urllib.request.Request(
                    url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    logger.debug(f"Webhook delivered to {url}: {resp.status}")
            except Exception as e:
                logger.warning(f"Webhook failed for {url}: {e}")

    def get_recent(self, limit: int = 20):
        """Get recent notifications."""
        with self._lock:
            return self._history[:limit]

    def clear_history(self):
        """Clear notification history."""
        with self._lock:
            self._history.clear()
