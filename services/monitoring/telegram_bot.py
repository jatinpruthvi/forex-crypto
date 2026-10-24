"""
Telegram Alerting Module:
Dispatches real-time Trade Alerts, Drawdown Escalation Notices,
and 30-minute Heartbeats to Telegram.
"""
from typing import Optional, Dict, Any
import requests
import logging
import time

logger = logging.getLogger("telegram_alerts")


class TelegramAlert:
    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        self.bot_token = bot_token or ""
        self.chat_id = chat_id or ""
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        self.last_sent_time = 0.0

    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id and ":" in self.bot_token)

    def send_message(self, text: str) -> bool:
        """Send message with rate-limiting guard."""
        if not self.is_configured():
            logger.info(f"[Telegram Mock] {text}")
            return True

        # Rate limit: 1 msg per 2 seconds
        now = time.time()
        if now - self.last_sent_time < 2.0:
            time.sleep(2.0 - (now - self.last_sent_time))

        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }
        try:
            resp = requests.post(self.base_url, json=payload, timeout=5)
            self.last_sent_time = time.time()
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Failed to send telegram message: {e}")
            return False

    def send_trade_alert(
        self,
        action: str,
        symbol: str,
        price: float,
        sl: float,
        tp: float,
        confidence: int,
        reason: str = "",
    ) -> bool:
        emoji = "🟢" if action == "BUY" else "🔴"
        msg = (
            f"{emoji} *AMATS TRADE ALERT*\n"
            f"*Action:* {action} {symbol}\n"
            f"*Entry Price:* {price}\n"
            f"*Stop Loss:* {sl}\n"
            f"*Take Profit:* {tp}\n"
            f"*Confidence:* {confidence}%\n"
            f"*Reason:* {reason}"
        )
        return self.send_message(msg)

    def send_drawdown_alert(self, level: str, dd_pct: float, reason: str) -> bool:
        icons = {"YELLOW": "⚠️", "ORANGE": "🟠", "RED": "🚨", "BLACK": "💀"}
        icon = icons.get(level, "⚠️")
        msg = (
            f"{icon} *DRAWDOWN PROTOCOL: {level}*\n"
            f"*Current DD:* {dd_pct:.2f}%\n"
            f"*Action:* {reason}"
        )
        return self.send_message(msg)

    def send_heartbeat(self, equity: float, open_positions_count: int, regime: str) -> bool:
        msg = f"💓 *HEARTBEAT*: System Alive | Eq: ${equity:.2f} | Open: {open_positions_count} | Regime: {regime}"
        return self.send_message(msg)
