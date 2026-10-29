"""
Monte Carlo Stress Simulation:
Simulates random sequence permutations of backtested trade results
to calculate 95th/99th percentile maximum drawdowns and risk of ruin.
"""
from typing import List, Dict, Any, Optional
import numpy as np


class MonteCarloSimulator:
    def __init__(self, n_simulations: int = 10000, seed: Optional[int] = None,
                 ruin_threshold_pct: float = 50.0):
        self.n_simulations = n_simulations
        # 'Ruin' here means a peak-to-trough equity drawdown beyond this
        # threshold (default -50%), NOT a prop-firm daily/total DD breach.
        self.ruin_threshold_pct = ruin_threshold_pct
        # Seeded RNG so every run is reproducible (ledger restore-point discipline).
        self.rng = np.random.default_rng(seed)

    def simulate(self, trade_returns: List[float], initial_equity: float = 10000.0) -> Dict[str, Any]:
        """
        Runs Monte Carlo bootstrap resampling (with replacement) of trade returns.
        trade_returns: list of return percentages (e.g. [+1.5, -0.8, +2.1])
        """
        if not trade_returns:
            return {
                "n_simulations": self.n_simulations,
                "max_dd_95_pct": 0.0,
                "max_dd_99_pct": 0.0,
                "probability_of_ruin_pct": 0.0,
                "ruin_threshold_pct": self.ruin_threshold_pct,
                "verdict": "SAFE",
            }

        returns_arr = np.array(trade_returns) / 100.0
        n_trades = len(returns_arr)

        max_drawdowns = []
        ruin_count = 0

        for _ in range(self.n_simulations):
            shuffled = self.rng.choice(returns_arr, size=n_trades, replace=True)
            capped_shuffled = np.maximum(-0.999, shuffled)
            equity_curve = initial_equity * np.cumprod(1.0 + capped_shuffled)
            # Peak must include the STARTING equity, otherwise an initial losing
            # streak understates the true peak-to-trough drawdown.
            peak = np.maximum.accumulate(np.maximum(equity_curve, initial_equity))
            dd = (peak - equity_curve) / peak * 100.0
            max_dd = np.max(dd)
            max_drawdowns.append(max_dd)

            if np.min(equity_curve) < initial_equity * (1.0 - self.ruin_threshold_pct / 100.0):
                ruin_count += 1

        dd_95 = float(np.percentile(max_drawdowns, 95))
        dd_99 = float(np.percentile(max_drawdowns, 99))
        ruin_prob = float(ruin_count / self.n_simulations * 100.0)

        return {
            "n_simulations": self.n_simulations,
            "max_dd_95_pct": round(dd_95, 2),
            "max_dd_99_pct": round(dd_99, 2),
            "probability_of_ruin_pct": round(ruin_prob, 2),
            "ruin_threshold_pct": self.ruin_threshold_pct,
            "verdict": "SAFE" if dd_95 < 20.0 else "TOO_RISKY",
        }
