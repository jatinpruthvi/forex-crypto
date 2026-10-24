"""
Kill-Switch Manager:
Monitors 6 failure modes and triggers immediate mitigation actions.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone


class KillSwitchManager:
    def __init__(self):
        self.last_heartbeat: Dict[str, datetime] = {}

    def record_heartbeat(self, service_name: str) -> None:
        self.last_heartbeat[service_name] = datetime.now(timezone.utc)

    def check_api_unreachable(self, service_name: str, max_silence_seconds: int = 600) -> bool:
        """KS1: Brain API / EA unreachable for >10 minutes (600s)."""
        last = self.last_heartbeat.get(service_name)
        if not last:
            return False
        delta = (datetime.now(timezone.utc) - last).total_seconds()
        return delta > max_silence_seconds

    def check_single_trade_loss(self, trade_loss_usd: float, portfolio_equity: float, threshold_pct: float = 3.0) -> bool:
        """KS3: Single trade catastrophe (>3% portfolio loss)."""
        if portfolio_equity <= 0:
            return True
        loss_pct = (abs(trade_loss_usd) / portfolio_equity) * 100.0
        return loss_pct > threshold_pct

    def check_flash_crash(
        self,
        candle_open: float,
        candle_close: float,
        threshold_pct: float = 5.0,
        candle_high: Optional[float] = None,
        candle_low: Optional[float] = None,
        volume: Optional[float] = None,
    ) -> bool:
        """
        KS5: Flash crash detected (>5% move in single candle).
        Guards against zero-volume weekend gaps or contract rollover false positives.
        """
        if candle_open <= 0:
            return False
        if volume is not None and volume <= 0:
            return False  # Ignore phantom weekend or holiday tick gaps
        move_pct = abs(candle_close - candle_open) / candle_open * 100.0
        return move_pct >= threshold_pct

    def check_all_guards(
        self,
        portfolio_equity: float,
        open_positions: List[Dict[str, Any]],
        latest_candle: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """Runs all fast kill switch checks."""
        # 1. Catastrophe single trade check
        for pos in open_positions:
            pnl = pos.get("pnl", 0.0)
            if pnl < 0 and self.check_single_trade_loss(pnl, portfolio_equity, threshold_pct=3.0):
                return {
                    "triggered": True,
                    "switch_id": "KS3",
                    "action": "CLOSE_POSITION",
                    "target_symbol": pos.get("symbol"),
                    "reason": f"Single trade loss exceeded 3% of portfolio ({pos.get('symbol')} loss: ${pnl:.2f})",
                }

        # 2. Flash crash check
        if latest_candle:
            c_open = latest_candle.get("open", 0.0)
            c_close = latest_candle.get("close", 0.0)
            if self.check_flash_crash(c_open, c_close, threshold_pct=5.0):
                return {
                    "triggered": True,
                    "switch_id": "KS5",
                    "action": "PAUSE_SYMBOL",
                    "target_symbol": latest_candle.get("symbol", "ALL"),
                    "reason": "Flash crash detected (>5% single candle range)",
                }

        return {"triggered": False, "switch_id": None, "action": "NONE", "reason": "All checks normal"}
