import pytest
import pandas as pd
import numpy as np


@pytest.fixture
def sample_ohlcv_df():
    np.random.seed(42)
    n = 250
    dates = pd.date_range("2025-01-01", periods=n, freq="1h")
    # Generate trending price series
    trend = np.linspace(50000, 60000, n)
    noise = np.random.normal(0, 200, n)
    close = trend + noise
    high = close + np.random.uniform(50, 150, n)
    low = close - np.random.uniform(50, 150, n)
    open_p = close + np.random.normal(0, 50, n)
    volume = np.random.uniform(100, 1000, n)

    return pd.DataFrame({
        "timestamp": dates,
        "open": open_p,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


@pytest.fixture
def sample_ranging_df():
    np.random.seed(123)
    n = 250
    dates = pd.date_range("2025-01-01", periods=n, freq="1h")
    # Mean-reverting sine wave
    base = 1.0800 + 0.0050 * np.sin(np.linspace(0, 10 * np.pi, n))
    noise = np.random.normal(0, 0.0005, n)
    close = base + noise
    high = close + 0.0008
    low = close - 0.0008
    open_p = close + np.random.normal(0, 0.0002, n)
    volume = np.random.uniform(500, 2000, n)

    return pd.DataFrame({
        "timestamp": dates,
        "open": open_p,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })
