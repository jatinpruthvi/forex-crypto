"""
Kelly Sizing Calculator:
Computes Full, Half, and Quarter Kelly fractions for position sizing.
"""
from typing import Dict, Any


class KellyCalculator:
    def __init__(self):
        pass

    def calculate_kelly(self, win_rate: float, avg_win: float, avg_loss: float) -> Dict[str, Any]:
        """
        Kelly Criterion:
        K% = W - (1 - W) / R
        where W = win rate (0-1), R = avg_win / avg_loss
        """
        if avg_loss <= 0 or avg_win <= 0:
            return {"full_kelly": 0.0, "half_kelly": 0.0, "quarter_kelly": 0.0, "recommendation": 0.0}

        # Clamp win/loss ratio r to prevent runaway sizing on small losses
        r = min(10.0, avg_win / max(0.001, avg_loss))
        w = win_rate if win_rate <= 1.0 else win_rate / 100.0

        kelly = w - ((1.0 - w) / r)
        # Cap full Kelly at 25% max allocation to prevent catastrophic non-stationary ruin
        kelly = max(0.0, min(0.25, kelly))

        half_kelly = kelly / 2.0
        quarter_kelly = kelly / 4.0

        return {
            "win_rate": round(w * 100.0, 2),
            "win_loss_ratio": round(r, 2),
            "full_kelly": round(kelly * 100.0, 2),
            "half_kelly": round(half_kelly * 100.0, 2),
            "quarter_kelly": round(quarter_kelly * 100.0, 2),
            "recommended_crypto": round(half_kelly * 100.0, 2),
            "recommended_prop_firm": round(quarter_kelly * 100.0, 2),
        }
