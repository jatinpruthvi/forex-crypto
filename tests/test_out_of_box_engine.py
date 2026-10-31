import pytest
import os
import pandas as pd
from core.analysis.out_of_box_engine import OutOfTheBoxAlphaEngine, MomentumCarouselAllocator

@pytest.fixture
def sample_df():
    dates = pd.date_range("2024-01-01", periods=150, freq="4h")
    price = 40000.0 + (pd.Series(range(150)) * 50.0).values
    df = pd.DataFrame({
        "timestamp": dates,
        "open": price,
        "high": price + 100.0,
        "low": price - 100.0,
        "close": price + 25.0,
        "volume": [1000.0] * 150
    })
    return df

def test_out_of_box_engine_simulation(sample_df):
    engine = OutOfTheBoxAlphaEngine(
        initial_capital=1000.0,
        base_risk_pct=2.5,
        leverage=2.0,
        enable_pyramiding=True,
        enable_dual_regime=True,
        enable_drawdown_throttle=True
    )
    res = engine.run_simulation(sample_df, "BTC_TEST", 1.0)
    assert "net_roi_total_pct" in res
    assert "monthly_roi_pct" in res
    assert "max_drawdown_pct" in res
    assert res["initial_capital"] == 1000.0

def test_momentum_carousel_allocator(sample_df):
    allocator = MomentumCarouselAllocator()
    mom = allocator.calculate_asset_momentum(sample_df)
    assert len(mom) == len(sample_df)

    scores = {"BTC": 1.5, "BNB": 2.1, "ETH": 0.8, "LINK": -0.2}
    weights = allocator.allocate_weights(scores)
    assert weights["BNB"] == 0.35
    assert weights["BTC"] == 0.35
    assert abs(sum(weights.values()) - 1.0) < 1e-4
