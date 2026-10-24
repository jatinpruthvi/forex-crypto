import pytest
import pandas as pd
import numpy as np
import os
import sqlite3
from unittest.mock import MagicMock

from core.signals.cross_asset import CrossAssetMonitor
from core.signals.fusion import SignalFusion
from core.signals.event_filter import EventFilter
from core.ml.walk_forward_learner import WalkForwardLearner
from core.analysis.kelly import KellyCalculator
from core.risk.kill_switch import KillSwitchManager
from core.analysis.backtest_analyzer import BacktestAnalyzer
from services.data_collector.sources.mexc import MEXCSource
from services.data_collector.sources.bybit import BybitSource
from services.freqtrade.user_data.strategies.OptionA_BTC_CompressedDonchian import OptionA_BTC_CompressedDonchian


def test_cross_asset_monitor_flexible_args():
    cam = CrossAssetMonitor()
    # Test with list of dicts without crashing
    open_pos = [{"symbol": "BTC/USDT"}, {"symbol": "ETH/USDT"}]
    res = cam.check_correlation_risk(open_pos)
    assert res == 1.0

    # Test with string
    res2 = cam.check_correlation_risk("BTC/USDT", candidate_symbol="ETH/USDT")
    assert res2 == 1.0


def test_signal_fusion_auto_db_migration(tmp_path):
    db_file = str(tmp_path / "sub" / "test_signals.db")
    sf = SignalFusion(db_path=db_file)
    res = sf.get_latest_signals("BTC/USDT")
    assert res["funding_rate"] == 0.0
    assert os.path.exists(db_file)


def test_kelly_calculator_clamping():
    kc = KellyCalculator()
    # Extremely small loss should not produce unbounded fraction
    res = kc.calculate_kelly(win_rate=0.6, avg_win=100.0, avg_loss=0.001)
    assert res["full_kelly"] <= 25.0
    assert res["half_kelly"] <= 12.5


def test_kill_switch_flash_crash_guard():
    ks = KillSwitchManager()
    # Zero volume tick gap should not trigger flash crash
    res = ks.check_flash_crash(candle_open=100.0, candle_close=90.0, threshold_pct=5.0, volume=0.0)
    assert res is False

    # Real volume move should trigger
    res_real = ks.check_flash_crash(candle_open=100.0, candle_close=90.0, threshold_pct=5.0, volume=500.0)
    assert res_real is True


def test_walk_forward_single_class_guard():
    wfl = WalkForwardLearner(model_path="/tmp/test_wfl.pkl")
    X = pd.DataFrame({"f1": np.random.randn(100), "f2": np.random.randn(100)})
    # All zeros (single class)
    y = pd.Series([0] * 100)
    res = wfl.evaluate_and_retrain(X, y)
    assert res["status"] == "skipped"
    assert not res["model_updated"]


def test_option_a_breakeven_stop_distance_shorts():
    strat = OptionA_BTC_CompressedDonchian()
    df = pd.DataFrame({
        "atr": [200.0],
        "close": [19800.0],
        "high": [19850.0],
        "low": [19750.0],
        "open": [19820.0],
        "volume": [1000.0]
    })
    strat.dp = MagicMock()
    strat.dp.get_analyzed_dataframe.return_value = (df, None)

    trade = MagicMock()
    trade.open_rate = 20000.0
    trade.is_short = True

    # Profit of +1.0% on short (current_rate = 19800)
    current_profit = 0.01
    sl = strat.custom_stoploss(
        pair="BTC/USDT:USDT",
        trade=trade,
        current_time=None,
        current_rate=19800.0,
        current_profit=current_profit,
        after_fill=True
    )
    # Stop distance must be negative and well within sane bounds
    assert sl is not None
    assert sl < 0.0
    assert -0.05 < sl < -0.001
