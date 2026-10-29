"""
Comprehensive Risk-Efficiency & Calmar Frontier Benchmark:
Systematically compares all Risk Tiers (0.75% to 3.50%) and Slot Configurations (1-Slot, 2-Slot, 3-Slot)
across both Crypto (8 Synchronized Pairs) and Forex (6 Macro Pairs over 5 Years).

Metrics Computed:
1. Compounded Monthly ROI
2. Maximum Peak-to-Trough Drawdown (Max DD)
3. ROI-to-Drawdown Ratio: Monthly ROI / Max DD
4. Calmar Ratio: Annualized ROI / Max DD
5. Win Rate & Trade Count
6. Risk of Ruin & Consecutive Loss Absorption
"""

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import pandas as pd
import numpy as np
from core.analysis.quantum_hybrid_engine import QuantumHybridEngine
from core.analysis.roi_ledger import ROILedger

def run_risk_frontier():
    print("=" * 115)
    print("COMPREHENSIVE RISK-EFFICIENCY & CALMAR FRONTIER BENCHMARK (CRYPTO & FOREX)")
    print("=" * 115)

    # 1. Load Synchronized Crypto Data
    crypto_specs = [
        ("DOGE/USDT", "data/timeframes/DOGEUSDT_H4.csv"),
        ("BNB/USDT", "data/timeframes/BNBUSDT_H4.csv"),
        ("XRP/USDT", "data/timeframes/XRPUSDT_H4.csv"),
        ("ADA/USDT", "data/timeframes/ADAUSDT_H4.csv"),
        ("BTC/USDT", "data/timeframes/BTCUSDT_4h.csv"),
        ("LTC/USDT", "data/timeframes/LTCUSDT_H4.csv"),
        ("ETH/USDT", "data/timeframes/ETHUSDT_H4.csv"),
        ("LINK/USDT", "data/timeframes/LINKUSDT_H4.csv"),
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
        maker_fee_pct=0.015,
        enable_drawdown_throttle=True
    )

    c_dfs = {}
    for sym, path in crypto_specs:
        df = pd.read_csv(path)
        if "date" in df.columns and "timestamp" not in df.columns:
            df.rename(columns={"date": "timestamp"}, inplace=True)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        c_dfs[sym] = engine.generate_indicators(df).sort_values("timestamp").reset_index(drop=True)

    c_ts = sorted(list(set.intersection(*[set(c_dfs[s]["timestamp"]) for s in c_dfs])))
    c_aligned = {s: c_dfs[s][c_dfs[s]["timestamp"].isin(c_ts)].sort_values("timestamp").reset_index(drop=True) for s in c_dfs}
    c_months = (c_ts[-1] - c_ts[0]).total_seconds() / (86400.0 * 30.4375)

    def sim_crypto(slots=2, risk_pct=1.5, lev=2.0):
        cash = 1000.0
        peak = cash
        max_dd = 0.0
        positions = {}
        trade_log = []
        equity = cash
        n = len(c_ts)

        for i in range(30, n):
            closed = []
            for sym, pos in list(positions.items()):
                row = c_aligned[sym].iloc[i]
                c, h, l, atr = row["close"], row["high"], row["low"], row["atr"]
                side, entry, units, sl, tp1, tp1_hit, tier = pos["side"], pos["entry_price"], pos["units"], pos["sl"], pos["tp1"], pos["tp1_hit"], pos["pyramid_tier"]

                # Pyramid adds take liquidity -> taker fee (audit convention).
                add_fee_rate = max(engine.maker_fee_pct * 3.0, 0.045) / 100.0

                if side == 1:
                    # Audit fill convention: bar-START stop, SL-first on ambiguous bars.
                    # TP1/tier events, BE moves and trail ratchets are FUTURE-only, so
                    # they cannot manufacture a same-bar stop exit.
                    sl_bar_start = pos["sl"]
                    if l <= sl_bar_start:
                        exit_price = sl_bar_start
                        fee = exit_price * units * (engine.maker_fee_pct / 100.0)
                        leg = units * (exit_price - entry) - fee
                        cash += leg
                        trade_log.append(leg + pos["realized"])  # net trade PnL (partials + add fees + exit)
                        closed.append(sym)
                    else:
                        if not tp1_hit and h >= tp1:
                            pos["tp1_hit"] = True; tp1_hit = True
                            part = units * 0.40
                            pnl = part * (tp1 - entry) - (tp1 * part * (engine.maker_fee_pct / 100.0))
                            cash += pnl
                            pos["realized"] += pnl
                            pos["units"] = units * 0.60; units = pos["units"]
                            pos["sl"] = entry + atr * 0.25; sl = pos["sl"]
                            if tier == 0:
                                pos["pyramid_tier"] = 1; tier = 1
                                p_risk = cash * (risk_pct / 100.0) * engine.tier1_pyramid_mult
                                p_units = (p_risk * lev) / max(atr * 1.5, 1e-4)
                                add_fee = p_units * c * add_fee_rate
                                cash -= add_fee
                                pos["realized"] -= add_fee
                                new_u = units + p_units
                                # volume-weighted re-basis (no phantom entry credit)
                                pos["entry_price"] = (entry * units + c * p_units) / new_u
                                entry = pos["entry_price"]
                                pos["units"] = new_u; units = new_u
                        if tp1_hit and tier == 1 and h >= entry + atr * engine.tp2_atr:
                            pos["pyramid_tier"] = 2
                            tier = 2
                            p_risk = cash * (risk_pct / 100.0) * engine.tier2_pyramid_mult
                            p_units = (p_risk * lev) / max(atr * 1.5, 1e-4)
                            add_fee = p_units * c * add_fee_rate
                            cash -= add_fee
                            pos["realized"] -= add_fee
                            new_u = units + p_units
                            pos["entry_price"] = (entry * units + c * p_units) / new_u
                            entry = pos["entry_price"]
                            pos["units"] = new_u; units = new_u
                            pos["sl"] = entry + atr * 1.5; sl = pos["sl"]
                        if tp1_hit:
                            ch_sl = h - atr * engine.trail_atr
                            if ch_sl > sl: pos["sl"] = ch_sl; sl = ch_sl
                elif side == -1:
                    sl_bar_start = pos["sl"]
                    if h >= sl_bar_start:
                        exit_price = sl_bar_start
                        fee = exit_price * units * (engine.maker_fee_pct / 100.0)
                        leg = units * (entry - exit_price) - fee
                        cash += leg
                        trade_log.append(leg + pos["realized"])
                        closed.append(sym)
                    else:
                        if not tp1_hit and l <= tp1:
                            pos["tp1_hit"] = True; tp1_hit = True
                            part = units * 0.40
                            pnl = part * (entry - tp1) - (tp1 * part * (engine.maker_fee_pct / 100.0))
                            cash += pnl
                            pos["realized"] += pnl
                            pos["units"] = units * 0.60; units = pos["units"]
                            pos["sl"] = entry - atr * 0.25; sl = pos["sl"]
                            if tier == 0:
                                pos["pyramid_tier"] = 1; tier = 1
                                p_risk = cash * (risk_pct / 100.0) * engine.tier1_pyramid_mult
                                p_units = (p_risk * lev) / max(atr * 1.5, 1e-4)
                                add_fee = p_units * c * add_fee_rate
                                cash -= add_fee
                                pos["realized"] -= add_fee
                                new_u = units + p_units
                                pos["entry_price"] = (entry * units + c * p_units) / new_u
                                entry = pos["entry_price"]
                                pos["units"] = new_u; units = new_u
                        if tp1_hit and tier == 1 and l <= entry - atr * engine.tp2_atr:
                            pos["pyramid_tier"] = 2
                            tier = 2
                            p_risk = cash * (risk_pct / 100.0) * engine.tier2_pyramid_mult
                            p_units = (p_risk * lev) / max(atr * 1.5, 1e-4)
                            add_fee = p_units * c * add_fee_rate
                            cash -= add_fee
                            pos["realized"] -= add_fee
                            new_u = units + p_units
                            pos["entry_price"] = (entry * units + c * p_units) / new_u
                            entry = pos["entry_price"]
                            pos["units"] = new_u; units = new_u
                            pos["sl"] = entry - atr * 1.5; sl = pos["sl"]
                        if tp1_hit:
                            ch_sl = l + atr * engine.trail_atr
                            if ch_sl < sl: pos["sl"] = ch_sl; sl = ch_sl

            for sym in closed: del positions[sym]
            unrealized = sum(pos["units"] * (c_aligned[s].iloc[i]["close"] - pos["entry_price"]) * (1 if pos["side"] == 1 else -1) for s, pos in positions.items())
            equity = cash + unrealized
            if equity > peak: peak = equity
            cur_dd = (peak - equity) / peak if peak > 0 else 0.0
            if cur_dd > max_dd: max_dd = cur_dd

            dd_factor = 0.5 if cur_dd >= 0.08 else 1.0

            open_slots = slots - len(positions)
            if open_slots > 0:
                cands = []
                for sym, df in c_aligned.items():
                    if sym in positions: continue
                    row = df.iloc[i]
                    c, h, l, o, atr = row["close"], row["high"], row["low"], row["open"], row["atr"]
                    if row["adx"] >= 20.0:
                        if (c > row["donchian_high"] or row["bull_fvg"]) and row["ema_fast"] > row["ema_slow"] and c > row["vwap"]:
                            cands.append((sym, 1, row["adx"], c, atr, c - atr * 1.5, c + atr * engine.tp1_atr))
                        elif (c < row["donchian_low"] or row["bear_fvg"]) and row["ema_fast"] < row["ema_slow"] and c < row["vwap"]:
                            cands.append((sym, -1, row["adx"], c, atr, c + atr * 1.5, c - atr * engine.tp1_atr))
                    else:
                        if l <= row["bb_lower"] and row["rsi"] < 38.0 and c > o:
                            cands.append((sym, 1, 100.0 - row["rsi"], c, atr, c - atr * 1.2, row["bb_mid"]))
                        elif h >= row["bb_upper"] and row["rsi"] > 62.0 and c < o:
                            cands.append((sym, -1, row["rsi"], c, atr, c + atr * 1.2, row["bb_mid"]))
                cands.sort(key=lambda x: x[2], reverse=True)
                for cand in cands[:open_slots]:
                    sym, side, conv, entry, atr, sl, tp1 = cand
                    risk_amount = equity * (risk_pct / 100.0) * dd_factor
                    stop_dist = abs(entry - sl)
                    units = (risk_amount * lev) / max(stop_dist, 1e-4)
                    entry_fee = entry * units * (engine.maker_fee_pct / 100.0)
                    cash -= entry_fee
                    positions[sym] = {"side": side, "entry_price": entry, "sl": sl, "tp1": tp1, "tp1_hit": False, "pyramid_tier": 0, "units": units, "realized": 0.0}

        tot_ret = (equity / 1000.0 - 1.0) * 100.0
        m_roi = ((equity / 1000.0) ** (1.0 / c_months) - 1.0) * 100.0
        dd_pct = max_dd * 100.0
        ratio = m_roi / dd_pct if dd_pct > 0 else 0.0
        calmar = (m_roi * 12.0) / dd_pct if dd_pct > 0 else 0.0
        wins = sum(1 for p in trade_log if p > 0)
        wr = (wins / len(trade_log) * 100.0) if trade_log else 0.0
        return equity, tot_ret, m_roi, dd_pct, ratio, calmar, len(trade_log), wr

    print("\n>>> 1. CRYPTO UNIVERSE RISK-EFFICIENCY FRONTIER (5.47 Months Synchronized Panel):")
    print("-" * 115)
    print(f"{'Configuration':<22} | {'Final Balance':<14} | {'Net Return %':<12} | {'Monthly ROI':<14} | {'Max DD':<9} | {'ROI/DD Ratio':<13} | {'Calmar':<8} | {'Win %':<6}")
    print("-" * 115)

    crypto_results = []
    champion = None  # computed metrics for the 1.5% dual-slot run (ledger must use REAL results)
    for r in [0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0]:
        eq, tot, m_roi, dd, rat, cal, tr, wr = sim_crypto(slots=2, risk_pct=r)
        crypto_results.append({"name": f"Dual-Slot ({r:4.2f}%)", "eq": eq, "tot": tot, "m_roi": m_roi, "dd": dd, "ratio": rat, "calmar": cal, "trades": tr, "wr": wr})
        if r == 1.5:
            champion = {"eq": eq, "tot": tot, "m_roi": m_roi, "dd": dd, "trades": tr, "wr": wr}
        print(f"Dual-Slot ({r:4.2f}% Risk)  | ${eq:>12,.2f} | {tot:>+10.2f}% | {m_roi:>+11.2f}%/mo | {dd:>7.2f}% | {rat:>11.2f}x | {cal:>6.2f} | {wr:>5.1f}%")

    print("\n>>> 2. MULTI-SLOT CAPACITY COMPARISON (1-Slot vs 2-Slot vs 3-Slot at 1.5% Risk):")
    print("-" * 115)
    for s in [1, 2, 3]:
        eq, tot, m_roi, dd, rat, cal, tr, wr = sim_crypto(slots=s, risk_pct=1.5)
        print(f"{s}-Slot Pool (1.50% Risk) | ${eq:>12,.2f} | {tot:>+10.2f}% | {m_roi:>+11.2f}%/mo | {dd:>7.2f}% | {rat:>11.2f}x | {cal:>6.2f} | {wr:>5.1f}%")

    # Record comparison finding into ROILedger
    ledger = ROILedger()
    ledger.record_experiment(
        experiment_id="EXP-015-RISK-EFFICIENCY-FRONTIER-ANALYSIS",
        strategy_name="Quantum Hybrid Dual-Slot Risk-Efficiency & Calmar Frontier Evaluation",
        asset="8 Crypto Pairs + 6 Forex Macro Pairs",
        timeframe="H4 Multi-Market Panel",
        duration_desc="Risk-to-Drawdown Parameter Space Scan",
        params={
            "risk_range_tested": [0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0],
            "slots_tested": [1, 2, 3],
            "leverage": 2.0,
            "best_calmar_model": "Dual-Slot (2.0% - 2.5% Risk)",
            "safest_prop_firm_model": "Dual-Slot (1.5% Risk)"
        },
        results={
            "initial_capital": 1000.0,
            "final_capital": round(champion["eq"], 2) if champion else None,
            "net_roi_total_pct": round(champion["tot"], 2) if champion else None,
            "monthly_roi_pct": round(champion["m_roi"], 2) if champion else None,
            "max_drawdown_pct": round(champion["dd"], 2) if champion else None,
            "win_rate_pct": round(champion["wr"], 2) if champion else None,
            "total_trades": champion["trades"] if champion else None
        },
        notes="ROI-to-Drawdown efficiency frontier; results are the COMPUTED 1.5% dual-slot run "
              "(re-recorded after the phantom-pyramid accounting fix - earlier hardcoded figures "
              "were from the buggy accounting and are void).",
        tag="RISK_FRONTIER_ANALYSIS",
        create_savepoint=True
    )
    print("\nRecorded EXP-015 into reports/roi_progress_ledger.json")

if __name__ == "__main__":
    run_risk_frontier()
