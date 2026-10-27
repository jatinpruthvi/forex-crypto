"""
Discord & Telegram Webhook Notification Bridge:
Dispatches instant structured trade execution alerts, breakeven movements,
and drawdown mitigation warnings to configurable webhook URLs or mock console.
"""
import os
import json
import time
import logging
from typing import Optional, Dict, Any
import requests

logger = logging.getLogger("webhook_bridge")


class WebhookNotifier:
    """
    Lightweight, resilient webhook notifier supporting Discord & Telegram formats.
    Silently logs to console if no webhook is configured.
    """
    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url or os.getenv("DISCORD_WEBHOOK_URL", "")
        self.last_sent_ts = 0.0

    def is_configured(self) -> bool:
        return bool(self.webhook_url and self.webhook_url.startswith("http"))

    def send_notification(self, title: str, description: str, color: int = 0x3b82f6, fields: Optional[list] = None) -> bool:
        if not self.is_configured():
            logger.info(f"[Webhook Audit] {title} | {description}")
            return True

        # Rate-limiting: prevent exceeding Discord rate limits (max 1 per 500ms)
        now = time.time()
        if now - self.last_sent_ts < 0.5:
            time.sleep(0.5 - (now - self.last_sent_ts))

        payload = {
            "embeds": [
                {
                    "title": title,
                    "description": description,
                    "color": color,
                    "fields": fields or [],
                    "footer": {"text": "AMATS Institutional Execution Engine"},
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
            ]
        }

        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=4)
            self.last_sent_ts = time.time()
            return resp.status_code in (200, 204)
        except Exception as e:
            logger.debug(f"Webhook notification suppressed: {e}")
            return False

    def notify_order_opened(
        self,
        account_name: str,
        symbol: str,
        side: str,
        entry_price: float,
        size: float,
        sl: float,
        tp: float,
        ml_confidence: Optional[float] = None,
    ) -> bool:
        color = 0x10b981 if side.lower() == "long" else 0xef4444
        conf_str = f" ({ml_confidence:.1f}% ML Confidence)" if ml_confidence is not None else ""
        title = f"🚀 [{account_name}] NEW {side.upper()} ORDER{conf_str}"
        description = f"Opened position on **{symbol}** at **${entry_price:.2f}**"
        fields = [
            {"name": "Symbol", "value": symbol, "inline": True},
            {"name": "Side", "value": side.upper(), "inline": True},
            {"name": "Size", "value": f"{size:.4f}", "inline": True},
            {"name": "Stop Loss", "value": f"${sl:.2f}", "inline": True},
            {"name": "Take Profit", "value": f"${tp:.2f}", "inline": True},
        ]
        return self.send_notification(title, description, color, fields)

    def notify_breakeven_locked(self, account_name: str, symbol: str, side: str, locked_price: float) -> bool:
        title = f"🛡️ [{account_name}] BREAKEVEN LOCKED"
        description = f"Profit buffer locked for **{symbol}** {side.upper()} at **${locked_price:.2f}** (Risk eliminated)."
        return self.send_notification(title, description, color=0x3b82f6)

    def notify_order_closed(
        self,
        account_name: str,
        symbol: str,
        side: str,
        exit_price: float,
        reason: str,
        net_pnl: float,
        return_pct: float,
    ) -> bool:
        is_win = net_pnl >= 0
        color = 0x10b981 if is_win else 0xef4444
        emoji = "✅" if is_win else "❌"
        title = f"{emoji} [{account_name}] TRADE CLOSED: {reason.upper()}"
        description = f"Closed **{symbol}** {side.upper()} at **${exit_price:.2f}**"
        fields = [
            {"name": "Net PnL", "value": f"${net_pnl:+.2f}", "inline": True},
            {"name": "Return", "value": f"{return_pct:+.2f}%", "inline": True},
            {"name": "Reason", "value": reason, "inline": True},
        ]
        return self.send_notification(title, description, color, fields)
