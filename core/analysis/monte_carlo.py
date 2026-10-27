"""
Monte Carlo Stress Simulation:
Simulates random sequence permutations of backtested trade results
to calculate 95th/99th percentile maximum drawdowns and risk of ruin.
"""
from typing import List, Dict, Any
import numpy as np


class MonteCarloSimulator:
    def __init__(self, n_simulations: int = 10000):
        self.n_simulations = n_simulations

    def simulate(self, trade_returns: List[float], initial_equity: float = 10000.0) -> Dict[str, Any]:
        """
        Runs Monte Carlo trade order shuffles.
        trade_returns: list of return percentages (e.g. [+1.5, -0.8, +2.1])
        """
        if not trade_returns:
            return {
                "n_simulations": self.n_simulations,
                "max_dd_95_pct": 0.0,
                "max_dd_99_pct": 0.0,
                "probability_of_ruin_pct": 0.0,
                "verdict": "SAFE",
            }

        returns_arr = np.array(trade_returns) / 100.0
        n_trades = len(returns_arr)

        max_drawdowns = []
        ruin_count = 0

        for _ in range(self.n_simulations):
            shuffled = np.random.choice(returns_arr, size=n_trades, replace=True)
            capped_shuffled = np.maximum(-0.999, shuffled)
            equity_curve = initial_equity * np.cumprod(1.0 + capped_shuffled)
            peak = np.maximum.accumulate(equity_curve)
            dd = (peak - equity_curve) / peak * 100.0
            max_dd = np.max(dd)
            max_drawdowns.append(max_dd)

            if np.min(equity_curve) < initial_equity * 0.5:
                ruin_count += 1

        dd_95 = float(np.percentile(max_drawdowns, 95))
        dd_99 = float(np.percentile(max_drawdowns, 99))
        ruin_prob = float(ruin_count / self.n_simulations * 100.0)

        return {
            "n_simulations": self.n_simulations,
            "max_dd_95_pct": round(dd_95, 2),
            "max_dd_99_pct": round(dd_99, 2),
            "probability_of_ruin_pct": round(ruin_prob, 2),
            "verdict": "SAFE" if dd_95 < 20.0 else "TOO_RISKY",
        }
