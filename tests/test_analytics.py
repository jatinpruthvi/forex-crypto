import pytest
from core.analysis.kelly import KellyCalculator
from core.analysis.monte_carlo import MonteCarloSimulator
from core.analysis.walk_forward import WalkForwardAnalyzer


def test_kelly_calculation():
    calc = KellyCalculator()
    res = calc.calculate_kelly(win_rate=55.0, avg_win=150.0, avg_loss=100.0)

    # W = 0.55, R = 1.5 -> Kelly = 0.55 - (0.45 / 1.5) = 0.55 - 0.30 = 0.25 (25%)
    assert abs(res["full_kelly"] - 25.0) < 0.5
    assert abs(res["half_kelly"] - 12.5) < 0.5
    assert abs(res["quarter_kelly"] - 6.25) < 0.5


def test_monte_carlo():
    mc = MonteCarloSimulator(n_simulations=100)
    # Balanced trades
    trades = [1.5, -1.0, 2.0, -1.2, 0.8, -0.9, 1.4, 2.5, -1.1]
    res = mc.simulate(trades, initial_equity=10000.0)

    assert "max_dd_95_pct" in res
    assert res["n_simulations"] == 100
    assert 0.0 <= res["probability_of_ruin_pct"] <= 100.0


def test_walk_forward_evaluation():
    wfa = WalkForwardAnalyzer()
    windows = [
        {"train_sharpe": 1.8, "test_sharpe": 1.2},
        {"train_sharpe": 1.5, "test_sharpe": 0.9},
        {"train_sharpe": 2.0, "test_sharpe": 1.4},
    ]
    res = wfa.evaluate_windows(windows)
    # Average train: 1.767, Average test: 1.167 -> WFE ~ 0.66 (>0.50 robust)
    assert res["wfe"] > 0.5
    assert res["is_robust"] is True
    assert res["verdict"] == "ROBUST"
