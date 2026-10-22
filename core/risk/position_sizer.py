"""
Position Sizing Module:
Calculates ATR-based stops and lot sizes according to account equity, risk percent,
and fractional Kelly criterion constraints.
"""
from typing import Dict, Any, Optional


class PositionSizer:
    def __init__(self, default_risk_pct: float = 0.5):
        self.default_risk_pct = default_risk_pct

    def calculate_lot_size(
        self,
        account_equity: float,
        sl_distance_pips: float,
        pip_value: float = 10.0,
        risk_pct_override: Optional[float] = None,
        size_multiplier: float = 1.0,
        max_lot: float = 1.0,
        min_lot: float = 0.01,
    ) -> Dict[str, Any]:
        """
        Forex / Index Lot Sizing formula:
        risk_amount = account_equity * (risk_pct / 100) * size_multiplier
        lot_size = risk_amount / (sl_distance_pips * pip_value)
        """
        risk_pct = risk_pct_override if risk_pct_override is not None else self.default_risk_pct
        risk_amount = account_equity * (risk_pct / 100.0) * max(0.0, size_multiplier)

        if sl_distance_pips <= 0 or pip_value <= 0:
            return {"lots": 0.0, "risk_amount": 0.0, "sl_distance_pips": sl_distance_pips}

        raw_lots = risk_amount / (sl_distance_pips * pip_value)
        lots = round(max(min_lot, min(raw_lots, max_lot)), 2)

        return {
            "lots": lots,
            "raw_lots": round(raw_lots, 4),
            "risk_amount": round(risk_amount, 2),
            "sl_distance_pips": round(sl_distance_pips, 1),
            "risk_pct_effective": round(risk_pct * size_multiplier, 3),
        }

    def calculate_crypto_stake(
        self,
        account_equity: float,
        entry_price: float,
        stop_loss_price: float,
        leverage: float = 3.0,
        risk_pct: float = 1.0,
        size_multiplier: float = 1.0,
    ) -> float:
        """
        Crypto Perpetual Stake Amount in USDT.
        """
        if entry_price <= 0 or stop_loss_price <= 0:
            return 10.0

        sl_distance_pct = abs(entry_price - stop_loss_price) / entry_price
        if sl_distance_pct < 0.001:
            sl_distance_pct = 0.02

        risk_usd = account_equity * (risk_pct / 100.0) * size_multiplier
        target_position_usd = risk_usd / sl_distance_pct
        # Cap with leverage limit
        max_position = account_equity * leverage
        position_usd = min(target_position_usd, max_position)
        return max(10.0, round(position_usd, 2))
