import pytest
import pandas as pd
import numpy as np

from core.signals.alpha_enhancements import SmartMoneyStructureFilter
from core.ml.features import FeatureEngineer
from services.data_collector.tv_ingestion import TvDatafeedClient
from services.demo_runner.real_paper_engine import RealPaperAccount


def test_smart_money_structure_filter():
    n = 60
    prices = np.linspace(50000, 55000, n)
    df = pd.DataFrame({
        "open": prices - 20.0,
        "high": prices + 50.0,
        "low": prices - 50.0,
        "close": prices,
        "volume": [1000.0] * n,
    })
    res = SmartMoneyStructureFilter.detect_fvg_and_order_blocks(df, swing_length=3)
    assert "has_bullish_fvg" in res
    assert "has_bullish_ob" in res
    assert "bos_confirmed" in res
    assert "smc_bias" in res


def test_ta_and_smc_feature_expansion():
    n = 120
    prices = np.linspace(60000, 65000, n)
    df = pd.DataFrame({
        "open": prices - 10.0,
        "high": prices + 30.0,
        "low": prices - 30.0,
        "close": prices,
        "volume": [2000.0] * n,
        "timestamp": pd.date_range("2026-10-26", periods=n, freq="15min"),
    })
    fe = FeatureEngineer()
    feats = fe.create_features(df)
    
    # Check that new TA & SMC features are present
    assert "ta_rsi_14" in feats.columns
    assert "ta_mfi_14" in feats.columns
    assert "ta_adx_14" in feats.columns
    assert "ta_bb_pband" in feats.columns
    assert "ta_bb_wband" in feats.columns
    assert "smc_bias" in feats.columns
    assert len(feats.columns) == 30


def test_smc_entry_discount_execution():
    acct = RealPaperAccount("Test SMC Discount", initial_capital=10000.0)
    # Entry at market: 60,000, but SMC discount limit fill: 59,800
    acct.open_trade(
        timestamp="2026-10-26 12:00:00",
        side="long",
        entry_price=60000.0,
        atr=500.0,
        smc_entry_discount=59800.0,
    )
    assert acct.position is not None
    # Entry price must match the discounted institutional level
    assert acct.position["entry_price"] == 59800.0
    # Stop loss must be tightened using 1.0x ATR instead of 1.3x ATR
    assert acct.position["sl_price"] == 59800.0 - (1.0 * 500.0)


def test_tvdatafeed_client_initialization():
    client = TvDatafeedClient()
    assert client is not None
    # Verifies graceful fallback without crashing
    df = client.fetch_historical_bars(symbol="BTCUSDT", n_bars=10)
    # df is either DataFrame or None (if offline/no credentials)
    assert df is None or isinstance(df, pd.DataFrame)
