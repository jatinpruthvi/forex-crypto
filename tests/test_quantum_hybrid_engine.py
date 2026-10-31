import pytest
import pandas as pd
from core.analysis.quantum_hybrid_engine import QuantumHybridEngine

@pytest.fixture
def sample_ohlcv():
    dates = pd.date_range("2024-01-01", periods=120, freq="4h")
    price = 2000.0 + (pd.Series(range(120)) * 10.0).values
    df = pd.DataFrame({
        "timestamp": dates,
        "open": price,
        "high": price + 25.0,
        "low": price - 25.0,
        "close": price + 5.0,
        "volume": [500.0] * 120
    })
    return df

def test_quantum_hybrid_engine_simulation(sample_ohlcv):
    engine = QuantumHybridEngine(
        initial_capital=1000.0,
        base_risk_pct=2.0,
        leverage=2.0,
        tier1_pyramid_mult=1.0,
        tier2_pyramid_mult=0.8,
        tp1_atr=1.8,
        tp2_atr=3.0,
        trail_atr=2.0,
        enable_drawdown_throttle=True
    )
    res = engine.run_simulation(sample_ohlcv, "TEST_PAIR", 1.0)
    assert "net_roi_total_pct" in res
    assert "monthly_roi_pct" in res
    assert "max_drawdown_pct" in res
    assert res["initial_capital"] == 1000.0
    assert isinstance(res["total_trades"], int)
