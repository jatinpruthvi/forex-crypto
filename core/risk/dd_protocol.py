"""
Drawdown Protocol:
4-Tier Escalation Model (Green, Yellow, Orange, Red, Black/Kill Switch)
Implements hard risk limits based on monthly and daily drawdowns.
"""
from typing import Dict, Any


class DrawdownProtocol:
    def __init__(
        self,
        yellow_threshold: float = 3.0,
        orange_threshold: float = 5.0,
        red_threshold: float = 7.0,
        black_threshold: float = 8.0,
        daily_loss_limit: float = 2.0,
    ):
        self.yellow_threshold = yellow_threshold
        self.orange_threshold = orange_threshold
        self.red_threshold = red_threshold
        self.black_threshold = black_threshold
        self.daily_loss_limit = daily_loss_limit

    def evaluate(
        self,
        starting_equity: float,
        current_equity: float,
        daily_pnl_pct: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Calculates monthly drawdown and returns protocol state, actions,
        conviction minimums, and position size multipliers.
        """
        if starting_equity <= 0:
            starting_equity = max(1.0, current_equity if current_equity > 0 else 1.0)
        if current_equity < 0:
            current_equity = 0.0

        monthly_dd = max(0.0, (starting_equity - current_equity) / starting_equity * 100.0)
        daily_loss = max(0.0, -daily_pnl_pct)

        # Check Daily Stop first (Hard rule: >2% daily loss halts new entries until UTC midnight)
        daily_breached = daily_loss >= self.daily_loss_limit

        if monthly_dd >= self.black_threshold:
            return {
                "level": "BLACK",
                "action": "CLOSE_ALL",
                "size_multiplier": 0.0,
                "conviction_min": 100.0,
                "ml_threshold": 1.0,
                "allow_new_trades": False,
                "cooldown_hours": 72,
                "monthly_dd_pct": round(monthly_dd, 2),
                "daily_loss_pct": round(daily_loss, 2),
                "reason": f"BLACK Protocol Triggered: Monthly Drawdown ({monthly_dd:.2f}%) exceeded {self.black_threshold}%",
            }

        if monthly_dd >= self.red_threshold or daily_breached:
            reason = (
                f"Daily loss limit reached ({daily_loss:.2f}% >= {self.daily_loss_limit}%)"
                if daily_breached
                else f"RED Protocol Triggered: Monthly Drawdown ({monthly_dd:.2f}%) reached {self.red_threshold}%"
            )
            return {
                "level": "RED",
                "action": "HALT_NEW_TRADES",
                "size_multiplier": 0.0,
                "conviction_min": 100.0,
                "ml_threshold": 1.0,
                "allow_new_trades": False,
                "cooldown_hours": 24,
                "monthly_dd_pct": round(monthly_dd, 2),
                "daily_loss_pct": round(daily_loss, 2),
                "reason": reason,
            }

        if monthly_dd >= self.orange_threshold:
            return {
                "level": "ORANGE",
                "action": "DEFENSIVE_TRADING",
                "size_multiplier": 0.25,
                "conviction_min": 85.0,
                "ml_threshold": 0.70,
                "allow_new_trades": True,
                "cooldown_hours": 0,
                "monthly_dd_pct": round(monthly_dd, 2),
                "daily_loss_pct": round(daily_loss, 2),
                "reason": f"ORANGE Protocol: DD ({monthly_dd:.2f}%). Reduced size to 25%, conviction min 85.",
            }

        if monthly_dd >= self.yellow_threshold:
            return {
                "level": "YELLOW",
                "action": "REDUCED_RISK",
                "size_multiplier": 0.50,
                "conviction_min": 75.0,
                "ml_threshold": 0.65,
                "allow_new_trades": True,
                "cooldown_hours": 0,
                "monthly_dd_pct": round(monthly_dd, 2),
                "daily_loss_pct": round(daily_loss, 2),
                "reason": f"YELLOW Protocol: DD ({monthly_dd:.2f}%). Reduced size to 50%, conviction min 75.",
            }

        # GREEN: Normal operation
        return {
            "level": "GREEN",
            "action": "NORMAL",
            "size_multiplier": 1.0,
            "conviction_min": 60.0,
            "ml_threshold": 0.55,
            "allow_new_trades": True,
            "cooldown_hours": 0,
            "monthly_dd_pct": round(monthly_dd, 2),
            "daily_loss_pct": round(daily_loss, 2),
            "reason": "GREEN Protocol: Normal operating conditions.",
        }
