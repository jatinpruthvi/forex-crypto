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


# ---------------------------------------------------------------------------
# Regression: audit #20 -- win counting must use NET trade PnL only, never
# "or tp1_hit". Crafted trade hits TP1 partial but nets a LOSS on fees; the
# legacy rule counted such trades as wins (inflated win rate).
# ---------------------------------------------------------------------------

def test_win_counting_uses_net_pnl_not_tp1_flag():
    import pandas as pd
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    from run_dual_slot_shared_pool_benchmark import execute_shared_pool_sim

    class _Eng:  # minimal engine attr stub; zero pyramid mults disable adds
        maker_fee_pct = 0.015
        taker_fee_pct = 0.045
        tier1_pyramid_mult = 0.0
        tier2_pyramid_mult = 0.0
        tp1_atr = 1.8
        tp2_atr = 3.0
        trail_atr = 2.0
        enable_drawdown_throttle = False

    n = 40
    ts = pd.date_range("2024-01-01", periods=n, freq="h").strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for i in range(n):
        quiet = dict(open=100.0, high=100.001, low=99.999, close=100.0,
                     atr=0.01, adx=5.0, donchian_high=200.0, donchian_low=0.0,
                     ema_fast=100.0, ema_slow=100.0, vwap=100.0,
                     bb_lower=90.0, bb_upper=110.0, bb_mid=100.0, rsi=50.0,
                     bull_fvg=False, bear_fvg=False)
        rows.append(quiet)
    # bar 31: breakout long entry at close 100, ATR 0.01 -> TP1 = 100.018
    rows[31].update(adx=30.0, donchian_high=99.9, ema_fast=100.2, ema_slow=99.8, vwap=99.9)
    # bar 32: high touches TP1 exactly (partial 40% at 100.018), no stop touch
    rows[32].update(high=100.018, close=100.01)
    # bar 33: low breaks the BE stop (entry + 0.25*ATR = 100.0025) -> taker stop exit
    rows[33].update(low=99.9, high=100.005, close=100.0)
    df = pd.DataFrame(rows)
    df.insert(0, "timestamp", ts)

    res = execute_shared_pool_sim(
        list(ts), {"TEST/USDT": df}, _Eng(), 1.0,
        gate_fn=None, max_slots=2, risk_pct=1.0, lev=2.0,
    )
    tl = res["trade_log"]
    assert len(tl) == 1
    assert tl[0]["tp1_hit"] is True        # partial TP DID fill...
    assert tl[0]["pnl"] < 0                # ...yet the net trade LOST (fees)
    # net-trade rule: zero wins. The legacy `or t["tp1_hit"]` rule would say 100%.
    assert res["win_rate"] == 0.0
    expected = 100.0 * sum(1 for t in tl if t["pnl"] > 0) / len(tl)
    assert res["win_rate"] == pytest.approx(expected)


def test_fast_backtester_no_double_count_on_partial_plus_tp_same_bar():
    """Regression: a bar that fills the 2xATR partial AND the TP must book the
    partial on half size and the TP exit on the REMAINING half -- never on the
    full (pre-partial) size."""
    import pandas as pd
    from core.analysis.fast_backtester import BacktestSimulator

    sim = BacktestSimulator(initial_capital=1000.0)  # taker mode: 0.1% slip, 0.055% fee
    df = pd.DataFrame({
        "timestamp": ["2024-01-01 00:00", "2024-01-01 04:00"],
        "open": [100.0, 100.0],
        "high": [100.5, 110.0],   # row 1 sweeps partial (104.1) AND TP (108.1)
        "low": [99.5, 97.0],      # stays above the bar-start stop (96.1)
        "close": [100.0, 109.0],
    })
    sig = pd.DataFrame({
        "timestamp": df["timestamp"],
        "signal": [1, 0],
        "atr": [2.0, 2.0],
        "conviction": [75.0, 75.0],
    })
    res = sim.run_backtest(df, sig, risk_per_trade_pct=2.0, atr_sl_mult=2.0,
                           atr_tp_mult=4.0, trailing_atr_mult=None, leverage=3.0,
                           max_open_trades=2)
    # entry: risk 1000*2%*0.75 = 15 USD / 4% stop -> size 375, fee 0.20625
    # partial @104.1 on 187.5: gain 7.4925 - fee 0.1031
    # TP exit @108.1*(1-0.001) on 187.5: 14.7825 - fee 0.1031
    expected = 1000.0 - 375.0 * 0.00055 \
        + (((104.1 - 100.1) / 100.1) * 187.5 - 187.5 * 0.00055) \
        + (((108.1 * 0.999 - 100.1) / 100.1) * 187.5 - 187.5 * 0.00055)
    assert res["final_capital"] == pytest.approx(expected, abs=0.05)
    assert len(res["closed_trades"]) == 1
    assert res["closed_trades"][0]["pnl_usd"] < 30.0  # buggy path booked ~29.4 on full size


def test_pyramid_add_rebases_avg_entry_and_pays_taker_fee():
    """Pyramid adds must re-basis avg_entry (volume-weighted) and pay taker fee.

    Regression for the phantom-profit bug: exit PnL was computed vs the
    ORIGINAL entry for the whole basket, crediting each pyramid unit a fake
    +1.8 ATR move it never had, and no add fee was charged.
    """
    import pandas as pd
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    from run_dual_slot_shared_pool_benchmark import execute_shared_pool_sim

    class _Eng:  # tier1 enabled; adds must charge fee and re-basis avg_entry
        maker_fee_pct = 0.015
        taker_fee_pct = 0.045
        tier1_pyramid_mult = 1.0
        tier2_pyramid_mult = 0.0
        tp1_atr = 1.8
        tp2_atr = 3.0
        trail_atr = 2.0
        enable_drawdown_throttle = False

    n = 40
    ts = pd.date_range("2024-01-01", periods=n, freq="h").strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for i in range(n):
        rows.append(dict(open=100.0, high=100.001, low=99.999, close=100.0,
                         atr=2.0, adx=5.0, donchian_high=200.0, donchian_low=0.0,
                         ema_fast=100.0, ema_slow=100.0, vwap=100.0,
                         bb_lower=90.0, bb_upper=110.0, bb_mid=100.0, rsi=50.0,
                         bull_fvg=False, bear_fvg=False))
    # bar 31: breakout long entry at close 100, ATR 2.0 -> sl 97.0, TP1 = 103.6
    rows[31].update(adx=30.0, donchian_high=99.9, ema_fast=100.2, ema_slow=99.8, vwap=99.9)
    # bar 32: TP1 partial @103.6 (40%), BE stop -> 100.25, tier1 add fills at close 101.0
    rows[32].update(high=103.6, low=99.5, close=101.0)
    # bar 33: low breaks the BE stop -> exit at 100.25 x (1 - slip)
    rows[33].update(high=100.5, low=98.0, close=98.5)
    df = pd.DataFrame(rows)
    df.insert(0, "timestamp", ts)

    res = execute_shared_pool_sim(
        list(ts), {"TEST/USDT": df}, _Eng(), 1.0,
        gate_fn=None, max_slots=2, risk_pct=1.0, lev=2.0,
    )
    assert res["total_trades"] == 1

    # --- hand-computed chain (independent of the engine code paths) ---
    maker, taker, slip = 0.00015, 0.00045, 0.0005
    atr, entry_px, cash = 2.0, 100.0, 1000.0
    units = cash * 0.01 * 1.0 * 2.0 / (atr * 1.5)              # 6.666667
    entry_fee = entry_px * units * maker                         # sim charges maker on entries
    cash -= entry_fee
    tp1 = entry_px + 1.8 * atr                                  # 103.6
    part = units * 0.40
    part_pnl = part * (tp1 - entry_px) - tp1 * part * maker
    cash += part_pnl
    rem = units * 0.60
    sl_be = entry_px + 0.25 * atr                               # 100.25
    p_units = cash * 0.01 * 1.0 * 2.0 / (atr * 1.5)             # tier1_mult via dd slot
    add_price = 101.0                                           # add fills at bar close
    add_fee = p_units * add_price * taker
    cash -= add_fee
    avg = (entry_px * rem + add_price * p_units) / (rem + p_units)
    exit_px = sl_be * (1 - slip)                                # stop fill = sl x (1 - slip)
    exit_pnl = (rem + p_units) * (exit_px - avg) - exit_px * (rem + p_units) * taker
    expected_trade_net = part_pnl - add_fee + exit_pnl
    expected_final = cash + exit_pnl

    got = res["trade_log"][0]["pnl"]
    assert got == pytest.approx(expected_trade_net, rel=1e-6), f"trade_net {got} vs {expected_trade_net}"
    assert res["final_equity"] == pytest.approx(expected_final, rel=1e-6), \
        f"final {res['final_equity']} vs {expected_final}"

    # The phantom model (exit vs original entry, no add fee) must decisively differ
    phantom_trade_net = part_pnl + (rem + p_units) * (exit_px - entry_px) - exit_px * (rem + p_units) * taker
    assert abs(got - phantom_trade_net) > 0.5 * abs(expected_trade_net)
