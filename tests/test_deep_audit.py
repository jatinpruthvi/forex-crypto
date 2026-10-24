import pytest
import pandas as pd
import numpy as np
from core.analysis.fast_backtester import BacktestSimulator
from core.risk.dd_protocol import DrawdownProtocol
from core.risk.kill_switch import KillSwitchManager
from core.risk.position_sizer import PositionSizer
from core.signals.fusion import SignalFusion
from core.regime.detector import RegimeDetector
from scripts.prune_maintenance import prune_sqlite_database, rotate_oversized_logs

def test_fast_backtester_zero_trades_edge_case():
    sim = BacktestSimulator(initial_capital=323.0)
    df = pd.DataFrame({
        "timestamp": ["2023-01-01 00:00:00", "2023-01-01 04:00:00"],
        "open": [20000.0, 20050.0],
        "high": [20100.0, 20150.0],
        "low": [19900.0, 19950.0],
        "close": [20050.0, 20100.0],
        "volume": [100.0, 150.0],
    })
    signals = pd.DataFrame({
        "signal": [0, 0],
        "atr": [200.0, 200.0],
        "conviction": [50.0, 50.0],
    })
    res = sim.run_backtest(df, signals)
    assert res["total_trades"] == 0
    assert res["win_rate"] == 0.0
    assert res["profit_factor"] == 0.0
    assert res["max_drawdown_pct"] == 0.0
    assert res["final_capital"] == 323.0

def test_drawdown_kill_switch_protocol():
    proto = DrawdownProtocol(yellow_threshold=3.0, orange_threshold=5.0, red_threshold=7.0, black_threshold=8.0)
    
    # Normal Green
    res_green = proto.evaluate(starting_equity=1000.0, current_equity=990.0)
    assert res_green["level"] == "GREEN"
    assert res_green["size_multiplier"] == 1.0

    # Yellow
    res_yellow = proto.evaluate(starting_equity=1000.0, current_equity=965.0)
    assert res_yellow["level"] == "YELLOW"
    assert res_yellow["size_multiplier"] == 0.50

    # Orange
    res_orange = proto.evaluate(starting_equity=1000.0, current_equity=945.0)
    assert res_orange["level"] == "ORANGE"
    assert res_orange["size_multiplier"] == 0.25

    # Red
    res_red = proto.evaluate(starting_equity=1000.0, current_equity=925.0)
    assert res_red["level"] == "RED"
    assert res_red["size_multiplier"] == 0.0
    assert res_red["allow_new_trades"] is False

    # Black (Total Hard Liquidation)
    res_black = proto.evaluate(starting_equity=1000.0, current_equity=910.0)
    assert res_black["level"] == "BLACK"
    assert res_black["action"] == "CLOSE_ALL"
    assert res_black["size_multiplier"] == 0.0

def test_kill_switch_flash_crash():
    ks = KillSwitchManager()
    assert ks.check_flash_crash(100.0, 94.0, threshold_pct=5.0) is True
    assert ks.check_flash_crash(100.0, 97.0, threshold_pct=5.0) is False
    assert ks.check_flash_crash(0.0, 100.0) is False

def test_position_sizer_boundaries():
    sizer = PositionSizer(default_risk_pct=0.5)
    # Zero or negative SL pips
    res = sizer.calculate_lot_size(account_equity=10000.0, sl_distance_pips=0.0)
    assert res["lots"] == 0.0
    
    # Normal sizing within min/max lot constraints
    res2 = sizer.calculate_lot_size(account_equity=10000.0, sl_distance_pips=20.0, pip_value=10.0, max_lot=2.0)
    assert res2["lots"] == 0.25
    assert res2["risk_amount"] == 50.0

def test_maintenance_script_resilience(tmp_path):
    # Ensure pruning on non-existent path handles gracefully without exception
    prune_sqlite_database(str(tmp_path / "non_existent.db"))
    # Ensure log rotation on empty dir handles gracefully
    rotate_oversized_logs(str(tmp_path / "empty_logs"))
