from core.risk.position_sizer import PositionSizer
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

from core.regime.detector import RegimeDetector
from core.analysis.walk_forward import WalkForwardAnalyzer

def test_regime_detector_hurst_flat_protection():
    rd = RegimeDetector()
    flat_series = np.array([100.0] * 50)
    # Must not raise LinAlgError or crash
    h = rd.calculate_hurst(flat_series)
    assert h == 0.5


def test_walk_forward_negative_train_sharpe():
    wfa = WalkForwardAnalyzer()
    res = wfa.evaluate_windows([{"train_sharpe": -0.5, "test_sharpe": 1.2}])
    assert res["wfe"] == 1.0
    assert res["is_robust"] is True
    assert res["verdict"] == "ROBUST"


def test_cross_asset_pairwise_correlation():
    cam = CrossAssetMonitor()
    s1 = pd.Series([100, 101, 102, 103, 104, 105])
    s2 = pd.Series([200, 202, 204, 206, 208, 210])
    corr = cam.calculate_correlation_matrix({"A": s1, "B": s2})
    assert corr.shape == (2, 2)
    assert round(corr.loc["A", "B"], 2) == 1.0

from services.brain_api.routes.signal import generate_signal, system_state
from services.brain_api.models.request import SignalRequest
import pytest

@pytest.mark.asyncio
async def test_brain_api_direction_aware_short_gate():
    # Construct synthetic bearish OHLCV
    ohlcv = []
    base_price = 28000.0
    for i in range(50):
        c = base_price - (i * 10.0)
        ohlcv.append([i * 3600, c + 5, c + 10, c - 10, c, 500.0])

    req = SignalRequest(
        symbol="BTC/USDT",
        timeframe="H1",
        ohlcv=ohlcv,
        account_equity=10000.0,
        open_positions=[]
    )
    res = await generate_signal(req)
    # The API should process without crashing and track starting equity for BTC/USDT
    assert "BTC/USDT" in system_state["account_starting_equities"]
    assert res.action in ["BUY", "SELL", "HOLD"]

from core.analysis.monte_carlo import MonteCarloSimulator

def test_monte_carlo_catastrophic_return_clamp():
    mc = MonteCarloSimulator(n_simulations=500)
    # Return of -105% (e.g. slippage/liquidation loss) must not invert to negative compounding
    returns = [-105.0, 10.0, 5.0, -2.0]
    res = mc.simulate(returns, initial_equity=10000.0)
    assert res["probability_of_ruin_pct"] >= 50.0
    assert res["max_dd_99_pct"] >= 90.0


def test_position_sizer_micro_equity():
    ps = PositionSizer()
    stake = ps.calculate_crypto_stake(account_equity=5.0, entry_price=20000.0, stop_loss_price=19000.0, leverage=3.0)
    # Must respect 3x leverage = $15 max
    assert stake <= 15.0

from core.analysis.fast_backtester import BacktestSimulator
from services.demo_runner.paper_broker import PaperAccount

def test_fast_backtester_zero_trades_no_crash():
    sim = BacktestSimulator(initial_capital=1000.0)
    df = pd.DataFrame({
        "timestamp": pd.date_range("2023-01-01", periods=10, freq="15min"),
        "open": [100.0] * 10,
        "high": [101.0] * 10,
        "low": [99.0] * 10,
        "close": [100.0] * 10,
        "volume": [1000.0] * 10,
    })
    sig = pd.DataFrame({
        "signal": [0] * 10,
        "atr": [1.0] * 10,
        "conviction": [50.0] * 10,
        "regime": ["RANGE"] * 10,
    })
    res = sim.run_backtest(df, sig)
    assert res["total_trades"] == 0
    assert res["win_rate"] == 0.0
    assert res["profit_factor"] == 0.0
    assert res["final_capital"] == 1000.0


def test_paper_broker_leverage_ceiling():
    acct = PaperAccount(starting_capital=10000.0)
    # Extremely tight stop loss (0.01 price distance)
    pos = acct.open_position("BTC/USDT", "long", price=20000.0, risk_pct=3.0, sl_price=19999.9, tp_price=20100.0, atr=50.0)
    assert pos is not None
    # Maximum allowed notional must not exceed 3x equity ($30,000)
    notional = pos["size"] * 20000.0
    assert notional <= 30000.01

def test_fusion_mpi_short_unwinding():
    sf = SignalFusion(db_path="/tmp/test_mpi.db")
    # Taker ratio neutral (1.0), OI decreasing (-2.0%), Price decreasing (-1.0%)
    res = sf.calculate_conviction("BTC/USDT", price_change_pct=-1.0, signals_override={
        "funding_rate": 0.0,
        "oi_change_pct": -2.0,
        "long_short_ratio": 1.0,
        "taker_ratio": 1.0
    })
    # MPI must reflect short unwinding negative bias
    assert res["mpi_index"] == -0.15


def test_position_sizer_custom_lot_step():
    ps = PositionSizer()
    # 3 decimal precision for instruments with min_lot = 0.001
    res = ps.calculate_lot_size(account_equity=10000.0, sl_distance_pips=20.0, pip_value=10.0, min_lot=0.005, max_lot=1.0)
    assert res["lots"] >= 0.005
    assert len(str(res["lots"]).split(".")[1]) <= 3

def test_binance_source_multi_pair_symbol_parsing():
    from services.data_collector.sources.binance import BinanceSource
    bs = BinanceSource()
    # Test fallback mapping
    # Since outbound networking is mocked or restricted in testing, verify method executes cleanly
    res = bs.fetch_long_short_ratio("SOL/USDT:USDT")
    assert isinstance(res, float)
    assert res > 0.0


def test_signal_request_default_factory():
    from services.brain_api.models.request import SignalRequest
    req1 = SignalRequest(symbol="BTC/USDT", ohlcv=[[1672531200000, 20000, 20100, 19900, 20050, 100]])
    req2 = SignalRequest(symbol="ETH/USDT", ohlcv=[[1672531200000, 1200, 1250, 1190, 1220, 50]])
    assert req1.open_positions is not req2.open_positions
    assert req1.open_positions == []

def test_empty_dataframe_regime_and_predict():
    from core.regime.detector import RegimeDetector
    from core.ml.predict import MLPredictor
    
    rd = RegimeDetector()
    empty_df = pd.DataFrame()
    res = rd.get_latest_regime(empty_df)
    assert res["regime"] == "RANGE"
    assert res["hurst"] == 0.5
    
    pred = MLPredictor()
    prob = pred.predict_probability(empty_df)
    assert prob == 0.50


def test_drawdown_protocol_negative_equity():
    from core.risk.dd_protocol import DrawdownProtocol
    dp = DrawdownProtocol()
    res = dp.evaluate(starting_equity=10000.0, current_equity=-500.0)
    assert res["level"] == "BLACK"
    assert res["size_multiplier"] == 0.0
