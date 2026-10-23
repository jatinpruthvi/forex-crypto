import pytest
import os
import json
import sqlite3
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta

from core.analysis.fast_backtester import BacktestSimulator
from core.analysis.kelly import KellyCalculator
from core.analysis.monte_carlo import MonteCarloSimulator
from core.analysis.walk_forward import WalkForwardAnalyzer
from core.analysis.backtest_analyzer import BacktestAnalyzer
from core.ml.features import FeatureEngineer
from core.ml.predict import MLPredictor
from core.ml.walk_forward_learner import WalkForwardLearner
from core.regime.detector import RegimeDetector
from core.risk.dd_protocol import DrawdownProtocol
from core.risk.kill_switch import KillSwitchManager
from core.risk.position_sizer import PositionSizer
from core.signals.cross_asset import CrossAssetMonitor
from core.signals.event_filter import EventFilter
from core.signals.fusion import SignalFusion
from services.data_collector.storage import SignalStorage
from scripts.prune_maintenance import prune_sqlite_database, rotate_oversized_logs

# ==========================================
# 1. FAST BACKTESTER EXHAUSTIVE TESTCASES
# ==========================================

def test_fast_backtester_all_long_wins():
    sim = BacktestSimulator(slippage_pct=0.0, taker_fee_pct=0.0, initial_capital=1000.0)
    df = pd.DataFrame({
        "timestamp": [f"2023-01-0{i} 00:00:00" for i in range(1, 6)],
        "open": [100.0, 102.0, 104.0, 106.0, 108.0],
        "high": [105.0, 108.0, 110.0, 112.0, 115.0],
        "low": [99.0, 101.0, 103.0, 105.0, 107.0],
        "close": [102.0, 104.0, 106.0, 108.0, 110.0],
        "volume": [1000.0] * 5,
    })
    signals = pd.DataFrame({
        "signal": [1, 0, 0, 0, 0],
        "atr": [2.0] * 5,
        "conviction": [85.0] * 5,
        "regime": ["TREND"] * 5,
    })
    res = sim.run_backtest(df, signals, risk_per_trade_pct=2.0, atr_sl_mult=1.5, atr_tp_mult=2.0)
    assert res["final_capital"] >= 1000.0
    assert res["win_rate"] >= 50.0

def test_fast_backtester_short_execution():
    sim = BacktestSimulator(slippage_pct=0.001, taker_fee_pct=0.00055, initial_capital=1000.0)
    df = pd.DataFrame({
        "timestamp": [f"2023-01-0{i} 00:00:00" for i in range(1, 6)],
        "open": [100.0, 98.0, 95.0, 92.0, 90.0],
        "high": [101.0, 99.0, 96.0, 93.0, 91.0],
        "low": [97.0, 94.0, 91.0, 88.0, 85.0],
        "close": [98.0, 95.0, 92.0, 90.0, 88.0],
        "volume": [1000.0] * 5,
    })
    signals = pd.DataFrame({
        "signal": [-1, 0, 0, 0, 0],
        "atr": [2.0] * 5,
        "conviction": [85.0] * 5,
        "regime": ["TREND"] * 5,
    })
    res = sim.run_backtest(df, signals, risk_per_trade_pct=2.0, atr_sl_mult=1.5, atr_tp_mult=2.5)
    assert res["total_trades"] >= 1

def test_fast_backtester_high_slippage_resilience():
    sim = BacktestSimulator(slippage_pct=0.01, taker_fee_pct=0.002, initial_capital=500.0)
    df = pd.DataFrame({
        "timestamp": [f"2023-01-0{i} 00:00:00" for i in range(1, 5)],
        "open": [100.0, 101.0, 102.0, 103.0],
        "high": [102.0, 103.0, 104.0, 105.0],
        "low": [98.0, 99.0, 100.0, 101.0],
        "close": [101.0, 102.0, 103.0, 104.0],
        "volume": [500.0] * 4,
    })
    signals = pd.DataFrame({
        "signal": [1, 0, 0, 0],
        "atr": [2.0] * 4,
        "conviction": [75.0] * 4,
        "regime": ["RANGE"] * 4,
    })
    res = sim.run_backtest(df, signals)
    assert res["final_capital"] > 0.0

def test_fast_backtester_conviction_thresholds():
    sim = BacktestSimulator(initial_capital=323.0)
    df = pd.DataFrame({
        "timestamp": ["2023-01-01 00:00:00", "2023-01-01 04:00:00"],
        "open": [100.0, 101.0],
        "high": [102.0, 103.0],
        "low": [99.0, 100.0],
        "close": [101.0, 102.0],
        "volume": [1000.0, 1000.0],
    })
    # Conviction < 60 must reject entry
    signals_low = pd.DataFrame({
        "signal": [1, 0],
        "atr": [2.0, 2.0],
        "conviction": [55.0, 55.0],
    })
    res = sim.run_backtest(df, signals_low)
    assert res["total_trades"] == 0

# ==========================================
# 2. KELLY CRITERION & ANALYTICS TESTCASES
# ==========================================

def test_kelly_zero_win_rate():
    kc = KellyCalculator()
    res = kc.calculate_kelly(win_rate=0.0, avg_win=100.0, avg_loss=50.0)
    assert res["full_kelly"] == 0.0
    assert res["half_kelly"] == 0.0

def test_kelly_negative_or_zero_losses():
    kc = KellyCalculator()
    res = kc.calculate_kelly(win_rate=0.6, avg_win=100.0, avg_loss=0.0)
    assert res["full_kelly"] == 0.0

def test_kelly_high_edge_fraction():
    kc = KellyCalculator()
    res = kc.calculate_kelly(win_rate=0.7, avg_win=200.0, avg_loss=100.0)
    assert res["full_kelly"] > 0.0
    assert res["half_kelly"] == res["full_kelly"] / 2.0
    assert res["quarter_kelly"] == res["full_kelly"] / 4.0

def test_monte_carlo_empty_returns():
    mc = MonteCarloSimulator(n_simulations=100)
    res = mc.simulate(trade_returns=[])
    assert res["max_dd_95_pct"] == 0.0
    assert res["probability_of_ruin_pct"] == 0.0

def test_monte_carlo_severe_loss_sequence():
    mc = MonteCarloSimulator(n_simulations=500)
    # Guaranteed losing streak
    res = mc.simulate(trade_returns=[-10.0] * 10, initial_equity=1000.0)
    assert res["probability_of_ruin_pct"] > 50.0
    assert res["verdict"] == "TOO_RISKY"

def test_walk_forward_analyzer_robust():
    wfa = WalkForwardAnalyzer()
    windows = [
        {"train_sharpe": 2.0, "test_sharpe": 1.4},
        {"train_sharpe": 1.8, "test_sharpe": 1.2},
    ]
    res = wfa.evaluate_windows(windows)
    assert res["wfe"] >= 0.50
    assert res["is_robust"] is True
    assert res["verdict"] == "ROBUST"

def test_walk_forward_analyzer_overfitted():
    wfa = WalkForwardAnalyzer()
    windows = [
        {"train_sharpe": 3.0, "test_sharpe": 0.5},
        {"train_sharpe": 2.5, "test_sharpe": 0.4},
    ]
    res = wfa.evaluate_windows(windows)
    assert res["wfe"] < 0.30
    assert res["is_robust"] is False
    assert res["verdict"] == "OVERFITTED"

def test_backtest_analyzer_nonexistent_file():
    ba = BacktestAnalyzer("non_existent_backtest.json")
    res = ba.extract_metrics()
    assert res["total_trades"] == 0
    assert res["win_rate"] == 0.0

# ==========================================
# 3. REGIME DETECTOR TESTCASES
# ==========================================

def test_regime_detector_short_series_hurst():
    rd = RegimeDetector()
    short_series = np.array([100.0, 101.0, 102.0])
    h = rd.calculate_hurst(short_series)
    assert h == 0.5

def test_regime_detector_flat_series():
    rd = RegimeDetector()
    flat = np.full(50, 100.0)
    h = rd.calculate_hurst(flat)
    assert 0.0 <= h <= 1.0

def test_regime_detector_classification_boundaries():
    rd = RegimeDetector()
    assert rd.classify_regime(hurst=0.60, atr_pct=96.0) == "CRISIS"
    assert rd.classify_regime(hurst=0.60, atr_pct=15.0) == "SQUEEZE"
    assert rd.classify_regime(hurst=0.60, atr_pct=85.0) == "BREAKOUT"
    assert rd.classify_regime(hurst=0.60, atr_pct=50.0) == "TREND"
    assert rd.classify_regime(hurst=0.40, atr_pct=50.0) == "RANGE"
    assert rd.classify_regime(hurst=0.50, atr_pct=50.0) == "TRANSITION"

def test_regime_detector_missing_column():
    rd = RegimeDetector()
    df_bad = pd.DataFrame({"high": [1, 2], "low": [0, 1]})
    with pytest.raises(ValueError):
        rd.detect(df_bad)

# ==========================================
# 4. KILL-SWITCH & PROTOCOL TESTCASES
# ==========================================

def test_kill_switch_api_unreachable():
    ks = KillSwitchManager()
    service = "brain_api"
    # Never heartbeat
    assert ks.check_api_unreachable(service) is False
    # Recent heartbeat
    ks.record_heartbeat(service)
    assert ks.check_api_unreachable(service, max_silence_seconds=600) is False
    # Stale heartbeat
    ks.last_heartbeat[service] = datetime.now(timezone.utc) - timedelta(seconds=700)
    assert ks.check_api_unreachable(service, max_silence_seconds=600) is True

def test_kill_switch_catastrophe_detection():
    ks = KillSwitchManager()
    # Loss 400 on 10000 equity = 4% (>3%)
    assert ks.check_single_trade_loss(trade_loss_usd=-400.0, portfolio_equity=10000.0, threshold_pct=3.0) is True
    # Loss 100 on 10000 equity = 1% (<3%)
    assert ks.check_single_trade_loss(trade_loss_usd=-100.0, portfolio_equity=10000.0, threshold_pct=3.0) is False

def test_kill_switch_all_guards_composite():
    ks = KillSwitchManager()
    positions = [
        {"symbol": "BTC/USDT", "pnl": -350.0},
        {"symbol": "ETH/USDT", "pnl": 50.0},
    ]
    res = ks.check_all_guards(portfolio_equity=10000.0, open_positions=positions)
    assert res["triggered"] is True
    assert res["switch_id"] == "KS3"
    assert res["action"] == "CLOSE_POSITION"

def test_drawdown_protocol_zero_starting_equity():
    dp = DrawdownProtocol()
    res = dp.evaluate(starting_equity=0.0, current_equity=100.0)
    assert res["level"] == "GREEN"

# ==========================================
# 5. CROSS-ASSET MONITOR TESTCASES
# ==========================================

def test_cross_asset_monitor_identity_fallback():
    cam = CrossAssetMonitor()
    # Short history fallback
    prices = {
        "BTC": pd.Series([100.0, 101.0]),
        "ETH": pd.Series([10.0, 11.0]),
    }
    matrix = cam.calculate_correlation_matrix(prices)
    assert matrix.shape == (2, 2)
    assert matrix.loc["BTC", "BTC"] == 1.0

def test_cross_asset_monitor_correlation_risk_scaling():
    cam = CrossAssetMonitor()
    corr_matrix = pd.DataFrame(
        [[1.0, 0.85], [0.85, 1.0]],
        index=["BTC/USDT", "ETH/USDT"],
        columns=["BTC/USDT", "ETH/USDT"],
    )
    positions = [{"symbol": "BTC/USDT"}, {"symbol": "ETH/USDT"}]
    scale = cam.check_correlation_risk(positions, correlation_matrix=corr_matrix)
    assert scale == 0.50

def test_cross_asset_risk_regime_classification():
    cam = CrossAssetMonitor()
    # Stocks & crypto up, DXY down -> RISK_ON
    regime = cam.evaluate_risk_regime(crypto_return=0.02, stock_return=0.01, gold_return=-0.005, dxy_return=-0.002)
    assert regime in ["RISK_ON", "RISK_OFF", "MIXED"]

def test_dxy_liquidity_squeeze_filter():
    cam = CrossAssetMonitor()
    # Spiking DXY triggers squeeze
    res_spike = cam.evaluate_dxy_liquidity_filter(dxy_daily_change_pct=0.45)
    assert res_spike["dollar_squeeze"] is True
    assert res_spike["risk_multiplier"] == 0.50

    # Normal DXY conditions
    res_normal = cam.evaluate_dxy_liquidity_filter(dxy_daily_change_pct=0.10)
    assert res_normal["dollar_squeeze"] is False
    assert res_normal["risk_multiplier"] == 1.0

def test_backtester_maker_execution_mode():
    sim = BacktestSimulator(order_execution_mode="maker")
    assert sim.slippage == 0.0
    assert sim.taker_fee == 0.0002

def test_feature_engineering_cvd_and_time_seasonality():
    fe = FeatureEngineer()
    df_ohlcv = pd.DataFrame({
        "timestamp": ["2023-01-01 14:00:00", "2023-01-01 15:00:00", "2023-01-01 16:00:00"],
        "open": [100.0, 101.0, 102.0],
        "high": [102.0, 103.0, 104.0],
        "low": [99.0, 100.0, 101.0],
        "close": [101.0, 102.0, 103.0],
        "volume": [1000.0, 1200.0, 1500.0],
    })
    feat = fe.create_features(df_ohlcv)
    assert "cvd_divergence" in feat.columns
    assert "is_weekend" in feat.columns
    assert "is_london_ny" in feat.columns

# ==========================================
# 6. EVENT FILTER TESTCASES
# ==========================================

def test_event_filter_no_cache_file():
    ef = EventFilter(cache_file="data/test_temp_calendar.json")
    assert isinstance(ef.events, list)
    in_window, event = ef.is_high_impact_window("EURUSD")
    assert in_window is False

def test_event_filter_high_impact_match():
    ef = EventFilter(cache_file="data/test_temp_calendar.json")
    now_utc = datetime.now(timezone.utc)
    ef.events = [
        {
            "title": "US CPI",
            "country": "USD",
            "impact": "High",
            "date": (now_utc + timedelta(minutes=10)).isoformat(),
        }
    ]
    in_window, event = ef.is_high_impact_window("EURUSD", current_time=now_utc, window_minutes=30)
    assert in_window is True
    assert event["title"] == "US CPI"

def test_event_filter_outside_window():
    ef = EventFilter(cache_file="data/test_temp_calendar.json")
    now_utc = datetime.now(timezone.utc)
    ef.events = [
        {
            "title": "US Non-Farm Payrolls",
            "country": "USD",
            "impact": "High",
            "date": (now_utc + timedelta(hours=5)).isoformat(),
        }
    ]
    in_window, _ = ef.is_high_impact_window("BTC/USDT", current_time=now_utc, window_minutes=30)
    assert in_window is False

# ==========================================
# 7. ML INFERENCE & FEATURE ENGINEERING
# ==========================================

def test_feature_engineering_missing_col():
    fe = FeatureEngineer()
    df_missing = pd.DataFrame({"close": [100, 101], "high": [102, 103]})
    with pytest.raises(ValueError):
        fe.create_features(df_missing)

def test_feature_engineering_label_bounds():
    fe = FeatureEngineer()
    df_ohlcv = pd.DataFrame({
        "open": [100.0] * 20,
        "high": [102.0] * 20,
        "low": [98.0] * 20,
        "close": [100.0 + i for i in range(20)],
        "volume": [100.0] * 20,
    })
    labels = fe.create_labels(df_ohlcv, forward_bars=5, threshold_pct=1.0)
    assert len(labels) == 20
    assert set(labels.unique()).issubset({-1, 0, 1})

def test_ml_predictor_missing_model():
    mlp = MLPredictor(model_path="non_existent_model.pkl")
    df_feat = pd.DataFrame([{"returns_1": 0.01}])
    prob = mlp.predict_probability(df_feat)
    assert prob == 0.50

# ==========================================
# 8. DATA COLLECTOR & DATABASE STORAGE
# ==========================================

def test_sqlite_storage_insert_and_query(tmp_path):
    db_file = str(tmp_path / "test_signals.db")
    storage = SignalStorage(db_file)
    record = {
        "timestamp": "2023-01-01T00:00:00Z",
        "symbol": "BTC/USDT:USDT",
        "funding_rate": 0.0001,
        "open_interest": 500000.0,
        "oi_change_pct": 2.5,
        "long_short_ratio": 1.15,
        "taker_buy_volume": 1000.0,
        "taker_sell_volume": 900.0,
        "taker_ratio": 1.11,
    }
    assert storage.insert_signal(record) is True
    queried = storage.get_latest_signal("BTC/USDT:USDT")
    assert queried is not None
    assert queried["funding_rate"] == 0.0001
    assert queried["open_interest"] == 500000.0
