"""
Unit and Integration Tests for NautilusTrader Execution Architecture
"""
import pytest
import pandas as pd
import numpy as np

from services.nautilus.adapters.data_loader import NautilusDataLoader
from services.nautilus.strategies.donchian_breakout import DonchianBreakoutConfig, DonchianBreakoutStrategy
from services.nautilus.backtest_runner import NautilusSimulationRunner


def test_nautilus_data_loader_conversion():
    df = pd.DataFrame({
        "timestamp": [
            "2023-01-01 00:00:00",
            "2023-01-01 00:15:00",
            "2023-01-01 00:30:00",
        ],
        "open": [20000.0, 20100.0, 20150.0],
        "high": [20200.0, 20250.0, 20300.0],
        "low": [19900.0, 20050.0, 20100.0],
        "close": [20100.0, 20150.0, 20250.0],
        "volume": [50.0, 60.0, 75.0],
    })

    bars = NautilusDataLoader.dataframe_to_bars(df, "BTCUSDT-PERP.BYBIT", timeframe_minutes=15)
    assert len(bars) == 3
    assert float(bars[0].open) == 20000.0
    assert float(bars[0].close) == 20100.0
    assert float(bars[2].high) == 20300.0
    assert bars[0].bar_type.spec.step == 15


def test_nautilus_donchian_breakout_simulation():
    # Construct a valid date range to avoid invalid hour 24
    dates = pd.date_range("2023-01-01", periods=30, freq="15min")
    prices = [20000.0 + (i * 25.0) for i in range(30)]
    df = pd.DataFrame({
        "timestamp": dates,
        "open": prices,
        "high": [p + 30.0 for p in prices],
        "low": [p - 20.0 for p in prices],
        "close": [p + 15.0 for p in prices],
        "volume": [100.0] * 30,
    })

    runner = NautilusSimulationRunner("BTCUSDT-PERP.BYBIT")
    res = runner.run_strategy_simulation(df)

    assert res["status"] == "completed"
    assert res["total_bars_processed"] == 30
    assert res["total_trades_initiated"] >= 1
    assert any(ev["event"] == "ENTRY" for ev in res["trade_events"])


def test_nautilus_multi_instrument_simulation():
    dates = pd.date_range("2023-01-01", periods=35, freq="15min")
    btc_prices = [25000.0 + (i * 30.0) for i in range(35)]
    sol_prices = [100.0 + (i * 1.5) for i in range(35)]

    df_btc = pd.DataFrame({
        "timestamp": dates,
        "open": btc_prices,
        "high": [p + 40.0 for p in btc_prices],
        "low": [p - 20.0 for p in btc_prices],
        "close": [p + 20.0 for p in btc_prices],
        "volume": [100.0] * 35,
    })

    df_sol = pd.DataFrame({
        "timestamp": dates,
        "open": sol_prices,
        "high": [p + 2.0 for p in sol_prices],
        "low": [p - 1.0 for p in sol_prices],
        "close": [p + 1.0 for p in sol_prices],
        "volume": [500.0] * 35,
    })

    runner = NautilusSimulationRunner()
    res = runner.run_multi_instrument_simulation({
        "BTCUSDT-PERP.BYBIT": df_btc,
        "SOLUSDT-PERP.BYBIT": df_sol,
    })

    assert res["status"] == "completed"
    assert res["total_bars_processed"] == 70
    assert "BTCUSDT-PERP.BYBIT" in res["instruments"]
    assert "SOLUSDT-PERP.BYBIT" in res["instruments"]
    assert res["total_trades"] >= 1
