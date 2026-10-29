"""
Regression tests for the repo-wide Top-50 bug audit fixes:
- conservative bar-start-stop resolution (no same-bar ratchet-then-trigger,
  no partial TP on bars that stop the position out)
- taker fee + slippage on trigger/stop exits
- win-rate counted on net trades
- ledger result-key normalization, Monte Carlo ruin threshold, VaR length guard
"""
import pytest

from core.analysis.fast_backtester import BacktestSimulator
from core.analysis.roi_ledger import normalize_results
from core.analysis.monte_carlo import MonteCarloSimulator
from core.risk.institutional_guards import ValueAtRiskGuard
from services.demo_runner.dual_slot_paper_engine import DualSlotSharedPoolAccount
from services.demo_runner.real_paper_engine import RealPaperAccount
from services.demo_runner.multi_asset_engine import MultiAssetPortfolioAccount


# ---------------------------------------------------------------------------
# Conservative same-bar fill resolution
# ---------------------------------------------------------------------------
def test_ambiguous_bar_fills_stop_not_tp():
    """A bar that trades through BOTH the bar-start stop and the TP must fill
    the stop first (conservative), never the profit."""
    import pandas as pd
    sim = BacktestSimulator(slippage_pct=0.0, taker_fee_pct=0.0, initial_capital=1000.0)
    df = pd.DataFrame({
        "timestamp": ["2023-01-01 00:00:00", "2023-01-02 00:00:00"],
        "open": [100.0, 100.0],
        "high": [101.0, 103.0],   # bar 2 trades through TP (102) ...
        "low": [99.5, 98.0],      # ... and through the bar-start stop (98.5)
        "close": [100.0, 101.0],
        "volume": [1000.0, 1000.0],
    })
    signals = pd.DataFrame({
        "signal": [1, 0], "atr": [1.0, 1.0], "conviction": [85.0, 85.0],
        "regime": ["TREND", "TREND"],
    })
    res = sim.run_backtest(df, signals, risk_per_trade_pct=2.0, atr_sl_mult=1.5, atr_tp_mult=2.0)
    closed = res["closed_trades"][0]
    assert closed["exit_reason"] == "SL"
    assert closed["exit_price"] == pytest.approx(98.5)
    assert closed["pnl_usd"] < 0  # the stop, not the TP profit


def test_no_partial_tp_on_stopping_bar():
    """The 2x-ATR partial must NOT be credited on a bar that hit the stop."""
    import pandas as pd
    sim = BacktestSimulator(slippage_pct=0.0, taker_fee_pct=0.0, initial_capital=1000.0)
    df = pd.DataFrame({
        "timestamp": ["2023-01-01 00:00:00", "2023-01-02 00:00:00"],
        "open": [100.0, 100.0],
        "high": [101.0, 104.0],   # reaches partial target entry+2*atr = 102
        "low": [99.5, 98.0],      # but also trades through the bar-start stop
        "close": [100.0, 101.0],
        "volume": [1000.0, 1000.0],
    })
    signals = pd.DataFrame({
        "signal": [1, 0], "atr": [1.0, 1.0], "conviction": [85.0, 85.0],
        "regime": ["RANGE", "RANGE"],
    })
    res = sim.run_backtest(df, signals, risk_per_trade_pct=2.0, atr_sl_mult=1.5, atr_tp_mult=3.0)
    closed = res["closed_trades"][0]
    assert closed["exit_reason"] == "SL"
    # full size exited at the stop -- no 50% partial was banked.
    # size = risk_usd / sl_pct = (1000 * 2%) / 1.5%
    size_usd = 1000.0 * 0.02 / 0.015
    assert closed["pnl_usd"] == pytest.approx((98.5 - 100.0) / 100.0 * size_usd, rel=1e-6)


# ---------------------------------------------------------------------------
# Taker fee + slippage on trigger exits
# ---------------------------------------------------------------------------
def test_dual_slot_stop_exit_uses_taker_fee_and_slippage():
    acc = DualSlotSharedPoolAccount(
        initial_capital=1000.0, maker_fee=0.0001, taker_fee=0.003, stop_slippage=0.01,
    )
    assert acc.open_trade("2026-01-01T00:00", "BTC/USDT", "long", 100.0, atr=2.0) is True
    pos = acc.positions["BTC/USDT"]
    stop = pos["stop_loss"]
    size = pos["size"]
    acc.on_asset_candle("2026-01-01T04:00", "BTC/USDT", high=100.5, low=stop - 0.05, close=100.0)
    rec = acc.closed_trades[0]
    exit_price = stop * (1.0 - 0.01)  # long stop fills below the trigger
    entry_fee = 100.0 * size * acc.maker_fee
    expected = (exit_price - 100.0) * size - (exit_price * size * 0.003) - entry_fee
    assert rec["net_pnl"] == pytest.approx(round(expected, 2), abs=0.01)  # record rounds to cents
    assert rec["exit_reason"] == "TRAILING_STOP_LOCK_HIT"


def test_real_paper_stop_exit_uses_taker_fee():
    acct = RealPaperAccount(
        "Fee Test", initial_capital=10000.0, maker_fee=0.0002,
        taker_fee=0.005, stop_slippage=0.0, laddered_tp=False,
    )
    acct.open_trade(timestamp="2026-01-01 00:00:00", side="long",
                    entry_price=100.0, atr=2.0, base_risk_pct=2.0)
    pos = acct.position
    sl = pos["sl_price"]
    fee_before_exit = pos["fee_paid"]
    rem = pos["remaining_size"]
    acct.on_candle("2026-01-01 00:15:00", high=100.5, low=sl - 0.05, close=100.0)
    closed = acct.closed_trades[0]
    # exit fee portion must be taker-rate (0.5%), not maker-rate (0.02%)
    exit_fee = closed["fee"] - fee_before_exit
    assert exit_fee == pytest.approx(sl * rem * 0.005, rel=1e-3)


def test_multi_asset_default_taker_floor_for_zero_maker():
    """Zero-maker-fee accounts must still pay a realistic taker rate on stops."""
    port = MultiAssetPortfolioAccount("ZeroMaker", initial_capital=10000.0, maker_fee=0.0)
    assert port.taker_fee == pytest.approx(0.00045)


# ---------------------------------------------------------------------------
# Ledger / Monte Carlo / VaR hardening
# ---------------------------------------------------------------------------
def test_normalize_results_maps_aliases():
    out = normalize_results({"duration_months": 5.47, "win_rate": 55.0,
                             "net_roi_total_pct": 200.0, "monthly_roi_pct": 25.0})
    assert out["months_elapsed"] == 5.47
    assert out["win_rate_pct"] == 55.0
    assert out["net_total_roi_pct"] == 200.0
    assert out["monthly_roi_pct"] == 25.0


def test_monte_carlo_ruin_threshold_parameter():
    mc = MonteCarloSimulator(n_simulations=50, seed=1, ruin_threshold_pct=5.0)
    res = mc.simulate([-10.0, 2.0, 2.0, -3.0])
    assert res["ruin_threshold_pct"] == 5.0
    assert res["probability_of_ruin_pct"] > 0.0  # -10% drawdown breaches 5%


def test_var_guard_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        ValueAtRiskGuard.calculate_var(10000.0, [1000.0, 2000.0], [0.02])
