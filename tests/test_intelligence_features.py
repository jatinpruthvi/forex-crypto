import pytest
import pandas as pd
import numpy as np
from core.ml.walk_forward_learner import WalkForwardLearner
from core.signals.fusion import SignalFusion
from core.risk.position_sizer import PositionSizer
from core.analysis.fast_backtester import BacktestSimulator

def test_walk_forward_learner_fallback(tmp_path):
    learner = WalkForwardLearner(model_path=str(tmp_path / "model_test.pkl"), history_window_bars=50, validation_window_bars=20)
    # Synthetic feature and labels
    df_feat = pd.DataFrame(np.random.randn(80, 5), columns=[f"f_{i}" for i in range(5)])
    y = pd.Series(np.random.choice([0, 1], size=80))
    res = learner.evaluate_and_retrain(df_feat, y)
    assert res["status"] in ["success", "fallback_retained", "skipped"]

def test_signal_fusion_mpi_calculation():
    fusion = SignalFusion()
    bullish_signals = {
        "funding_rate": -0.0004,
        "oi_change_pct": 5.0,
        "long_short_ratio": 0.45,
        "taker_ratio": 1.25,
    }
    res = fusion.calculate_conviction("BTC/USDT", price_change_pct=1.0, signals_override=bullish_signals)
    assert "mpi_index" in res
    assert -1.0 <= res["mpi_index"] <= 1.0
    assert res["mpi_index"] > 0.0  # Taker buyers + OI expansion should be positive MPI

def test_position_sizer_covariance_deflation():
    sizer = PositionSizer(default_risk_pct=0.5)
    # Sizing without deflation
    normal = sizer.calculate_lot_size(account_equity=10000.0, sl_distance_pips=20.0, pip_value=10.0, covariance_deflation_factor=1.0)
    # Sizing with 0.50x deflation
    deflated = sizer.calculate_lot_size(account_equity=10000.0, sl_distance_pips=20.0, pip_value=10.0, covariance_deflation_factor=0.50)
    assert deflated["lots"] <= normal["lots"]
    assert deflated["risk_amount"] == normal["risk_amount"] * 0.50

def test_regime_adaptive_fast_backtester():
    sim = BacktestSimulator(initial_capital=323.0)
    df = pd.DataFrame({
        "timestamp": [f"2023-01-0{i} 00:00:00" for i in range(1, 10)],
        "open": [20000.0 + i*50 for i in range(9)],
        "high": [20100.0 + i*50 for i in range(9)],
        "low": [19900.0 + i*50 for i in range(9)],
        "close": [20050.0 + i*50 for i in range(9)],
        "volume": [100.0 for _ in range(9)],
    })
    signals = pd.DataFrame({
        "signal": [1, 0, 0, 0, 0, 0, 0, 0, 0],
        "atr": [200.0 for _ in range(9)],
        "conviction": [85.0 for _ in range(9)],
        "regime": ["TREND" for _ in range(9)],
    })
    res = sim.run_backtest(df, signals, trailing_atr_mult=2.5)
    assert res["final_capital"] > 0.0
