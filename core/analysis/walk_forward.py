"""
Walk-Forward Validation Calculator:
Computes Walk-Forward Efficiency (WFE = Out-of-Sample Sharpe / In-Sample Sharpe).
A system with WFE > 0.5 is considered robust and non-overfitted.
"""
from typing import List, Dict, Any
import numpy as np


class WalkForwardAnalyzer:
    def __init__(self):
        pass

    def evaluate_windows(self, window_results: List[Dict[str, float]]) -> Dict[str, Any]:
        """
        Expects list of dicts: [{'train_sharpe': 1.8, 'test_sharpe': 1.1, ...}, ...]
        """
        if not window_results:
            return {"wfe": 0.0, "is_robust": False}

        train_sharpes = [w.get("train_sharpe", 0.0) for w in window_results]
        test_sharpes = [w.get("test_sharpe", 0.0) for w in window_results]

        avg_train = float(np.mean(train_sharpes)) if train_sharpes else 0.0
        avg_test = float(np.mean(test_sharpes)) if test_sharpes else 0.0

        if avg_train > 0:
            wfe = avg_test / avg_train
        elif avg_train <= 0 and avg_test > 0:
            wfe = 1.0  # Test is profitable despite difficult training period
        else:
            wfe = 0.0

        is_robust = wfe >= 0.50 and avg_test > 0.0
        verdict = "ROBUST" if is_robust else ("BORDERLINE" if wfe >= 0.30 and avg_test >= 0.0 else "OVERFITTED")

        return {
            "avg_train_sharpe": round(avg_train, 2),
            "avg_test_sharpe": round(avg_test, 2),
            "wfe": round(wfe, 3),
            "is_robust": is_robust,
            "verdict": verdict,
        }
