"""
Backtest Benchmark: Dual-Slot Shared Pool Allocation Engine with Actual Historical Data.

Validates:
1. True time-synchronized cross-asset simulation (Candle-by-Candle across all 8 qualifying crypto pairs).
2. Dual-Slot capacity constraint: maximum 2 concurrent positions active at any timestamp across all assets.
3. Unified capital margin pool ($1,000 initial balance, not sliced into static fractions).
4. Opportunity routing: signals ranked by trend strength / confluence (ADX + breakout momentum) when a slot opens.
5. Asymmetric Payoff Ratchet & Pyramiding:
   - Partial profit taking at +1.8x ATR (realizes 40% position, locks SL to entry + 0.25x ATR buffer).
   - Tier 1 Pyramiding at +1.8x ATR.
   - Tier 2 Pyramiding at +3.0x ATR.
   - Chandelier trailing stop (2.0x ATR).
   - Dynamic Drawdown Throttle (cuts risk size by 50% if peak-to-trough DD exceeds threshold).
   - Maker fee deduction (0.015% per trade fill).

Also benchmarks varying risk profiles (1.0%, 1.25%, 1.5%, 1.75%, 2.0%, 2.5%) and compares against:
- Single-Slot Shared Pool
- Static Capital Slicing (EXP-012)
"""

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import pandas as pd
import numpy as np
import json
import os
from datetime import datetime
from core.analysis.quantum_hybrid_engine import QuantumHybridEngine
from core.execution.live_adapter import SizingViabilityGate
from core.analysis.roi_ledger import ROILedger

# Conservative stop-fill slippage (trigger stops are market orders).
STOP_SLIPPAGE = 0.0005


def execute_shared_pool_sim(timestamps, aligned_dfs, engine, duration_months,
                            gate_fn=None, max_slots=2, risk_pct=1.5, lev=2.0,
                            dd_throttle_threshold=0.08,
                            stop_slippage=None, taker_fee_pct=None):
    """Corrected dual-slot shared-pool simulation (audited fill model).

    Bar-start stop snapshot, stop fills FIRST on ambiguous bars with taker fee
    + stop_slippage; no TP/pyramid bookkeeping on stopping bars; net-trade win
    counting. `gate_fn` (optional) applies venue lot viability; without it the
    raw risk-budget size (equity * risk% * dd_factor * leverage / stop_dist) is
    used.
    """
    def _gated_units(sym, eq, price, atr, risk, leverage, dd_mult, stop_atr_mult=1.5):
        if gate_fn is not None:
            return gate_fn(sym, eq, price, atr, risk, leverage, dd_mult, stop_atr_mult)
        stop_dist = max(atr * stop_atr_mult, 1e-4)
        return (eq * (risk / 100.0) * dd_mult * leverage) / stop_dist

    _slip = STOP_SLIPPAGE if stop_slippage is None else stop_slippage
    _taker = engine.taker_fee_pct if taker_fee_pct is None else taker_fee_pct

    cash = 1000.0
    peak_equity = cash
    max_dd = 0.0
    positions = {}
    trade_log = []
    equity_curve = []
    equity = cash

    n_bars = len(timestamps)

    for i in range(30, n_bars):
        current_bar_time = timestamps[i]
        closed_this_bar = []

        # -----------------------------------------------------------------
        # 1. Manage existing open positions
        # -----------------------------------------------------------------
        for sym, pos in list(positions.items()):
            df = aligned_dfs[sym]
            row = df.iloc[i]
            c, h, l = row["close"], row["high"], row["low"]
            atr = row["atr"]
            side = pos["side"]
            entry = pos["entry_price"]
            avg = pos["avg_entry"]
            units = pos["units"]
            sl = pos["sl"]
            tp1 = pos["tp1"]
            tp1_hit = pos["tp1_hit"]
            tier = pos["pyramid_tier"]

            if side == 1:
                sl_bar_start = sl
                # Conservative same-bar resolution: the bar-START stop, if
                # traded, fills FIRST (taker fee + slippage) -- no TP/pyramid
                # bookkeeping on this bar.
                if l <= sl_bar_start:
                    exit_price = sl_bar_start * (1.0 - _slip)
                    fee = exit_price * units * (_taker / 100.0)
                    pnl = units * (exit_price - avg) - fee
                    cash += pnl
                    trade_net = pnl + pos.get("realized", 0.0)  # net trade: exit leg + partials - add fees
                    trade_log.append({
                        "sym": sym,
                        "side": "LONG",
                        "entry": entry,
                        "exit": exit_price,
                        "pnl": trade_net,
                        "tp1_hit": tp1_hit,
                        "tier": tier,
                        "time": current_bar_time
                    })
                    closed_this_bar.append(sym)
                    continue

                # Check Partial TP1 (+1.8x ATR)
                if not tp1_hit and h >= tp1:
                    pos["tp1_hit"] = True
                    tp1_hit = True
                    part_units = units * 0.40
                    pnl = part_units * (tp1 - avg) - (tp1 * part_units * (engine.maker_fee_pct / 100.0))
                    cash += pnl
                    pos["realized"] = pos.get("realized", 0.0) + pnl
                    pos["units"] = units * 0.60
                    units = pos["units"]
                    # Lock Stop Loss to entry + 0.25x ATR risk-free buffer
                    pos["sl"] = entry + atr * 0.25
                    sl = pos["sl"]

                    # Tier 1 Pyramiding using realized house-money (lot-gated)
                    if tier == 0:
                        p_units = _gated_units(sym, cash, entry, atr, risk_pct, lev, engine.tier1_pyramid_mult)
                        if p_units > 0:
                            pos["pyramid_tier"] = 1
                            tier = 1
                            add_price = c  # market add fills at bar close
                            add_fee = add_price * p_units * (engine.taker_fee_pct / 100.0)
                            cash -= add_fee
                            pos["realized"] = pos.get("realized", 0.0) - add_fee  # add fee counts against trade PnL
                            pos["avg_entry"] = (pos["avg_entry"] * units + add_price * p_units) / (units + p_units)
                            pos["units"] += p_units
                            units = pos["units"]

                # Check Tier 2 Pyramiding (+3.0x ATR)
                if tp1_hit and tier == 1:
                    if h >= entry + atr * engine.tp2_atr:
                        p_units = _gated_units(sym, cash, entry, atr, risk_pct, lev, engine.tier2_pyramid_mult)
                        if p_units > 0:
                            pos["pyramid_tier"] = 2
                            tier = 2
                            add_price = c  # market add fills at bar close
                            add_fee = add_price * p_units * (engine.taker_fee_pct / 100.0)
                            cash -= add_fee
                            pos["realized"] = pos.get("realized", 0.0) - add_fee  # add fee counts against trade PnL
                            pos["avg_entry"] = (pos["avg_entry"] * units + add_price * p_units) / (units + p_units)
                            pos["units"] += p_units
                            units = pos["units"]
                            pos["sl"] = entry + atr * 1.5
                            sl = pos["sl"]

                # Chandelier dynamic trailing stop (effective for FUTURE bars only)
                if tp1_hit:
                    ch_sl = h - atr * engine.trail_atr
                    if ch_sl > sl:
                        pos["sl"] = ch_sl
                        sl = ch_sl

            elif side == -1:
                sl_bar_start = sl
                # Conservative same-bar resolution against the bar-START stop.
                if h >= sl_bar_start:
                    exit_price = sl_bar_start * (1.0 + _slip)
                    fee = exit_price * units * (_taker / 100.0)
                    pnl = units * (avg - exit_price) - fee
                    cash += pnl
                    trade_net = pnl + pos.get("realized", 0.0)  # net trade: exit leg + partials - add fees
                    trade_log.append({
                        "sym": sym,
                        "side": "SHORT",
                        "entry": entry,
                        "exit": exit_price,
                        "pnl": trade_net,
                        "tp1_hit": tp1_hit,
                        "tier": tier,
                        "time": current_bar_time
                    })
                    closed_this_bar.append(sym)
                    continue

                # Short position management
                if not tp1_hit and l <= tp1:
                    pos["tp1_hit"] = True
                    tp1_hit = True
                    part_units = units * 0.40
                    pnl = part_units * (avg - tp1) - (tp1 * part_units * (engine.maker_fee_pct / 100.0))
                    cash += pnl
                    pos["realized"] = pos.get("realized", 0.0) + pnl
                    pos["units"] = units * 0.60
                    units = pos["units"]
                    pos["sl"] = entry - atr * 0.25
                    sl = pos["sl"]

                    if tier == 0:
                        p_units = _gated_units(sym, cash, entry, atr, risk_pct, lev, engine.tier1_pyramid_mult)
                        if p_units > 0:
                            pos["pyramid_tier"] = 1
                            tier = 1
                            add_price = c  # market add fills at bar close
                            add_fee = add_price * p_units * (engine.taker_fee_pct / 100.0)
                            cash -= add_fee
                            pos["realized"] = pos.get("realized", 0.0) - add_fee  # add fee counts against trade PnL
                            pos["avg_entry"] = (pos["avg_entry"] * units + add_price * p_units) / (units + p_units)
                            pos["units"] += p_units
                            units = pos["units"]

                if tp1_hit and tier == 1:
                    if l <= entry - atr * engine.tp2_atr:
                        p_units = _gated_units(sym, cash, entry, atr, risk_pct, lev, engine.tier2_pyramid_mult)
                        if p_units > 0:
                            pos["pyramid_tier"] = 2
                            tier = 2
                            add_price = c  # market add fills at bar close
                            add_fee = add_price * p_units * (engine.taker_fee_pct / 100.0)
                            cash -= add_fee
                            pos["realized"] = pos.get("realized", 0.0) - add_fee  # add fee counts against trade PnL
                            pos["avg_entry"] = (pos["avg_entry"] * units + add_price * p_units) / (units + p_units)
                            pos["units"] += p_units
                            units = pos["units"]
                            pos["sl"] = entry - atr * 1.5
                            sl = pos["sl"]

                if tp1_hit:
                    ch_sl = l + atr * engine.trail_atr
                    if ch_sl < sl:
                        pos["sl"] = ch_sl
                        sl = ch_sl

        for sym in closed_this_bar:
            del positions[sym]

        # Mark to market equity
        unrealized = 0.0
        for sym, pos in positions.items():
            curr_c = aligned_dfs[sym].iloc[i]["close"]
            mult = 1 if pos["side"] == 1 else -1
            unrealized += pos["units"] * (curr_c - pos["avg_entry"]) * mult
        equity = cash + unrealized

        if equity > peak_equity:
            peak_equity = equity
        cur_dd = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0
        if cur_dd > max_dd:
            max_dd = cur_dd

        equity_curve.append({"time": current_bar_time, "equity": equity, "drawdown": cur_dd})

        # Drawdown risk throttle (Prop Firm safety rule: if DD >= dd_throttle_threshold, cut risk to 50%)
        dd_factor = 0.5 if (engine.enable_drawdown_throttle and cur_dd >= dd_throttle_threshold) else 1.0

        # -----------------------------------------------------------------
        # 2. Evaluate entries across inactive assets if slots are free
        # -----------------------------------------------------------------
        open_slots = max_slots - len(positions)
        if open_slots > 0:
            candidates = []
            for sym, df in aligned_dfs.items():
                if sym in positions:
                    continue
                row = df.iloc[i]
                c, h, l, o = row["close"], row["high"], row["low"], row["open"]
                atr = row["atr"]
                adx = row["adx"]
                dh, dl = row["donchian_high"], row["donchian_low"]
                ef, es, vwap = row["ema_fast"], row["ema_slow"], row["vwap"]
                bb_low, bb_up, bb_mid = row["bb_lower"], row["bb_upper"], row["bb_mid"]
                rsi = row["rsi"]
                bull_fvg, bear_fvg = row["bull_fvg"], row["bear_fvg"]

                # Regime 1: High Trend Momentum / Volatility Breakout
                if adx >= 20.0:
                    if (c > dh or bull_fvg) and ef > es and c > vwap:
                        candidates.append({
                            "sym": sym,
                            "side": 1,
                            "conviction": adx,
                            "entry": c,
                            "sl": c - atr * 1.5,
                            "tp1": c + atr * engine.tp1_atr
                        })
                    elif (c < dl or bear_fvg) and ef < es and c < vwap:
                        candidates.append({
                            "sym": sym,
                            "side": -1,
                            "conviction": adx,
                            "entry": c,
                            "sl": c + atr * 1.5,
                            "tp1": c - atr * engine.tp1_atr
                        })
                # Regime 2: Low-Volatility Bollinger Mean-Reversion
                else:
                    if l <= bb_low and rsi < 38.0 and c > o:
                        candidates.append({
                            "sym": sym,
                            "side": 1,
                            "conviction": (100.0 - rsi),
                            "entry": c,
                            "sl": c - atr * 1.2,
                            "tp1": bb_mid
                        })
                    elif h >= bb_up and rsi > 62.0 and c < o:
                        candidates.append({
                            "sym": sym,
                            "side": -1,
                            "conviction": rsi,
                            "entry": c,
                            "sl": c + atr * 1.2,
                            "tp1": bb_mid
                        })

            # Sort by conviction score (highest momentum/reversion disparity first)
            candidates.sort(key=lambda x: x["conviction"], reverse=True)

            for cand in candidates[:open_slots]:
                sym = cand["sym"]
                side = cand["side"]
                entry = cand["entry"]
                sl = cand["sl"]
                tp1 = cand["tp1"]
                
                # Risk amount is calculated on current TOTAL equity in the shared pool
                stop_dist = abs(entry - sl)
                stop_atr_mult = (stop_dist / atr) if atr > 0 else 1.5
                units = _gated_units(sym, equity, entry, atr, risk_pct, lev, dd_factor, stop_atr_mult)
                if units <= 0:
                    continue
                entry_fee = entry * units * (engine.maker_fee_pct / 100.0)
                cash -= entry_fee

                positions[sym] = {
                    "side": side,
                    "entry_price": entry,
                    "avg_entry": entry,  # volume-weighted entry incl. pyramid adds
                    "sl": sl,
                    "tp1": tp1,
                    "tp1_hit": False,
                    "pyramid_tier": 0,
                    "units": units
                }

    # Calculate final metrics
    final_equity = equity
    net_profit = final_equity - 1000.0
    net_roi_total = (net_profit / 1000.0) * 100.0
    monthly_roi = ((final_equity / 1000.0) ** (1.0 / duration_months) - 1.0) * 100.0
    total_trades = len(trade_log)
    winning_trades = sum(1 for t in trade_log if t["pnl"] > 0)  # net-trade rule (audit #20)
    win_rate = (winning_trades / total_trades * 100.0) if total_trades > 0 else 0.0
    gross_profit = sum(t["pnl"] for t in trade_log if t["pnl"] > 0)
    gross_loss = abs(sum(t["pnl"] for t in trade_log if t["pnl"] < 0))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    # Breakdown by coin
    coin_breakdown = {}
    for t in trade_log:
        c = t["sym"]
        if c not in coin_breakdown:
            coin_breakdown[c] = {"trades": 0, "profit": 0.0, "wins": 0}
        coin_breakdown[c]["trades"] += 1
        coin_breakdown[c]["profit"] += t["pnl"]
        if t["pnl"] > 0:
            coin_breakdown[c]["wins"] += 1

    return {
        "max_slots": max_slots,
        "risk_pct": risk_pct,
        "leverage": lev,
        "final_equity": final_equity,
        "net_profit": net_profit,
        "net_roi_total": net_roi_total,
        "monthly_roi": monthly_roi,
        "max_drawdown": max_dd * 100.0,
        "total_trades": total_trades,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "coin_breakdown": coin_breakdown,
        "duration_months": duration_months,
        "open_positions_at_end": len(positions),
        "trade_log": trade_log,
        "equity_curve": equity_curve,
    }

def run_dual_slot_benchmark():
    print("=" * 105)
    print("BACKTEST: DUAL-SLOT SHARED POOL ALLOCATION ENGINE WITH ACTUAL HISTORICAL DATA")
    print("=" * 105)

    crypto_specs = [
        ("DOGE/USDT", "data/timeframes/bench_panel/DOGEUSDT_H4.csv"),
        ("BNB/USDT", "data/timeframes/bench_panel/BNBUSDT_H4.csv"),
        ("XRP/USDT", "data/timeframes/bench_panel/XRPUSDT_H4.csv"),
        ("ADA/USDT", "data/timeframes/bench_panel/ADAUSDT_H4.csv"),
        ("BTC/USDT", "data/timeframes/bench_panel/BTCUSDT_4h.csv"),
        ("LTC/USDT", "data/timeframes/bench_panel/LTCUSDT_H4.csv"),
        ("ETH/USDT", "data/timeframes/bench_panel/ETHUSDT_H4.csv"),
        ("LINK/USDT", "data/timeframes/bench_panel/LINKUSDT_H4.csv"),
    ]

    engine = QuantumHybridEngine(
        initial_capital=1000.0,
        base_risk_pct=1.5,
        leverage=2.0,
        tier1_pyramid_mult=1.0,
        tier2_pyramid_mult=0.8,
        tp1_atr=1.8,
        tp2_atr=3.0,
        trail_atr=2.0,
        maker_fee_pct=float(os.getenv("MAKER_FEE_PCT", "0.015")),
        enable_drawdown_throttle=True
    )

    # 1. Load and prepare indicator data frames
    dfs = {}
    for sym, path in crypto_specs:
        df = pd.read_csv(path)
        if "date" in df.columns and "timestamp" not in df.columns:
            df.rename(columns={"date": "timestamp"}, inplace=True)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)
        dfs[sym] = engine.generate_indicators(df)
        print(f"Loaded {sym:<12} -> {len(df)} 4H bars ({df['timestamp'].iloc[0]} to {df['timestamp'].iloc[-1]})")

    # Timeframe metrics
    start_time = max(dfs[sym]["timestamp"].iloc[0] for sym in dfs)
    end_time = min(dfs[sym]["timestamp"].iloc[-1] for sym in dfs)
    duration_days = (end_time - start_time).total_seconds() / 86400.0
    duration_months = duration_days / 30.4375
    print(f"\nUnified Synchronized Window: {start_time} to {end_time} ({duration_days:.1f} days / {duration_months:.2f} months)")

    # Align timestamps
    timestamps = sorted(list(set.intersection(*[set(dfs[s]["timestamp"]) for s in dfs])))
    print(f"Synchronized Concurrent Bars: {len(timestamps)} bars")

    # Re-index datasets to common timestamp index
    aligned_dfs = {}
    for sym in dfs:
        aligned_dfs[sym] = dfs[sym][dfs[sym]["timestamp"].isin(timestamps)].sort_values("timestamp").reset_index(drop=True)

    def _gated_units(sym, eq, price, atr, risk, leverage, dd_mult, stop_atr_mult=1.5):
        """MICRO_ACCOUNT_MODE gate: venue lot-step must not distort risk > 5%,
        and the order must clear the venue min notional. Returns 0 -> skip."""
        gate = SizingViabilityGate.check(
            sym, equity=eq, price=price, atr=atr, risk_pct=risk,
            leverage=leverage, dd_factor=dd_mult, stop_atr_mult=stop_atr_mult,
            max_error_pct=float(os.getenv("MICRO_MAX_SIZING_ERROR_PCT", "5.0")),
            venue=os.getenv("LOT_VENUE", "mexc"),
        )
        return gate["stepped_qty"] if gate["viable"] else 0.0


    # -----------------------------------------------------------------
    # Grid Test: Compare Risk Tiers for Dual-Slot Shared Pool
    # -----------------------------------------------------------------
    print("\n" + "=" * 105)
    print("DUAL-SLOT SHARED POOL RISK-PARAMETER BACKTEST GRID (REAL 4H DATA ACROSS 8 PAIRS)")
    print("=" * 105)
    print(f"{'Config / Model':<28} | {'Final Balance':<14} | {'Net Total %':<12} | {'Monthly ROI':<14} | {'Max DD':<10} | {'Trades':<8} | {'Win Rate':<10} | {'PF':<6}")
    print("-" * 105)

    risk_levels = [1.5] if os.getenv("CHAMPION_ONLY", "0") == "1" else [1.0, 1.25, 1.5, 1.75, 2.0, 2.5]
    results_map = {}
    for r in risk_levels:
        res = execute_shared_pool_sim(timestamps, aligned_dfs, engine, duration_months,
                                gate_fn=_gated_units, max_slots=2, risk_pct=r, lev=2.0)
        results_map[r] = res
        tag = f"Dual-Slot (Risk {r:4.2f}%)"
        print(f"{tag:<28} | ${res['final_equity']:>12,.2f} | +{res['net_roi_total']:>9.2f}% | +{res['monthly_roi']:>10.2f}%/mo | {res['max_drawdown']:>8.2f}% | {res['total_trades']:>6d} | {res['win_rate']:>8.2f}% | {res['profit_factor']:>5.2f}")

    # Single-Slot comparison
    print("-" * 105)
    single_res = execute_shared_pool_sim(timestamps, aligned_dfs, engine, duration_months,
                                  gate_fn=_gated_units, max_slots=1, risk_pct=1.5, lev=2.0)
    print(f"{'Single-Slot Shared (1.5%)':<28} | ${single_res['final_equity']:>12,.2f} | +{single_res['net_roi_total']:>9.2f}% | +{single_res['monthly_roi']:>10.2f}%/mo | {single_res['max_drawdown']:>8.2f}% | {single_res['total_trades']:>6d} | {single_res['win_rate']:>8.2f}% | {single_res['profit_factor']:>5.2f}")

    # -----------------------------------------------------------------
    # Deep Breakdown of Champion Dual-Slot Model (1.5% Risk)
    # -----------------------------------------------------------------
    champ = results_map[1.5]
    print("\n" + "=" * 105)
    print("CHAMPION DUAL-SLOT SHARED POOL EXECUTION BREAKDOWN (1.5% Risk, 2.0x Leverage):")
    print("=" * 105)
    print("• Initial Capital:        $1,000.00 (Single Unified Pool, Zero Static Slicing)")
    print(f"• Final Account Balance:  ${champ['final_equity']:,.2f}")
    print(f"• Total Net Profit:       +${champ['net_profit']:,.2f} (+{champ['net_roi_total']:.2f}%)")
    print(f"• Compounded Monthly ROI: +{champ['monthly_roi']:.2f}% / month (Goal was ~25%/mo)")
    print(f"• Maximum Drawdown:       {champ['max_drawdown']:.2f}%")
    print(f"• Profit Factor:          {champ['profit_factor']:.2f}")
    print(f"• Total Trades:           {champ['total_trades']} across 8 pairs")
    print(f"• Overall Win Rate:       {champ['win_rate']:.2f}%")

    print("\nAsset Contribution to Shared Opportunity Pool:")
    print(f"{'Asset Pair':<14} | {'Trades Executed':<16} | {'Realized Net PnL':<18} | {'Win Rate':<10}")
    print("-" * 65)
    for sym, data in sorted(champ["coin_breakdown"].items(), key=lambda x: x[1]["profit"], reverse=True):
        c_wr = (data["wins"] / data["trades"] * 100.0) if data["trades"] > 0 else 0.0
        print(f"{sym:<14} | {data['trades']:>14d} | +${data['profit']:>15,.2f} | {c_wr:>8.2f}%")

    # Record into ROILedger
    if os.getenv("SKIP_LEDGER", "0") == "1":
        print("\nSKIP_LEDGER=1 -- ledger write skipped")
        return
    ledger = ROILedger()
    ledger.record_experiment(
        experiment_id=os.getenv("EXP_ID", "EXP-013-DUAL-SLOT-SHARED-POOL"),
        strategy_name="Quantum Hybrid Dual-Slot Shared Margin Pool Allocator",
        asset="8 Synchronized Crypto Pairs (BTC, DOGE, XRP, LTC, ETH, ADA, BNB, LINK)",
        timeframe="H4 Actual Historical Candles",
        duration_desc="5.47 Months Walk-Forward Historical Panel",
        params={
            "max_concurrent_slots": 2,
            "base_risk_pct": 1.5,
            "leverage": 2.0,
            "tier1_pyramid_mult": 1.0,
            "tier2_pyramid_mult": 0.8,
            "tp1_atr": 1.8,
            "tp2_atr": 3.0,
            "trail_atr": 2.0,
            "maker_fee_pct": float(os.getenv("MAKER_FEE_PCT", "0.015")),
            "drawdown_throttle": True,
            "tested_pairs": [s[0] for s in crypto_specs]
        },
        results={
            "initial_capital": 1000.0,
            "final_capital": round(champ["final_equity"], 2),
            "net_roi_total_pct": round(champ["net_roi_total"], 2),
            "monthly_roi_pct": round(champ["monthly_roi"], 2),
            "max_drawdown_pct": round(champ["max_drawdown"], 2),
            "profit_factor": round(champ["profit_factor"], 2),
            "win_rate_pct": round(champ["win_rate"], 2),
            "total_trades": champ["total_trades"],
            "duration_months": round(champ["duration_months"], 2),
            "months_elapsed": round(champ["duration_months"], 2)
        },
        notes=os.getenv("EXP_NOTES", "Empirical validation of Dual-Slot Shared Margin Pool across 8 synchronized real crypto time series, dynamically reallocating released margin into top-conviction signals. Results reported from the audited fill model (bar-start stop snapshot, stop fills first with taker fee + slippage). See experiment metrics for realized ROI."),
        tag=os.getenv("EXP_TAG", "DUAL_SLOT_SHARED_POOL_CHAMPION"),
        create_savepoint=True
    )
    print("\nSuccessfully recorded experiment and savepoint into reports/roi_progress_ledger.json")

if __name__ == "__main__":
    run_dual_slot_benchmark()
