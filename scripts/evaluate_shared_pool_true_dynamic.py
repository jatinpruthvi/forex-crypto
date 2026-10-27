import pandas as pd
import numpy as np

# Let's test the TRUE shared pool dynamics:
# The user asked:
# "what happen if we have multiple strategy without dedicated allocation and accept multiple open position."
# Here:
# - There is NO dedicated sub-account allocation ($1,000 pooled together).
# - We allow up to N concurrent open positions (e.g., 2, 3, 4, 6 positions).
# - Any strategy that fires an entry takes a slot dynamically sized from the FULL current account balance!
# - If BTC Donchian fires twice on consecutive waves, it can hold 2 concurrent BTC positions.
# - If SOL or LINK also fires, it takes slot 3 or 4.

assets_config = [
    ("BTC_Donchian", "BTC", "data/timeframes/BTCUSD_H4.csv", "data/timeframes/BTCUSD_M15.csv", "donchian_12", 1.3, 2.0, "TREND"),
    ("BTC_SMC",      "BTC", "data/timeframes/BTCUSD_H4.csv", "data/timeframes/BTCUSD_M15.csv", "smc",          1.3, 2.0, "TREND"),
    ("SOL_Reversal",  "SOL", "data/timeframes/SOLUSDT_H4.csv", "data/timeframes/SOLUSDT_M15.csv", "reversal",     1.2, 1.8, "RANGE"),
    ("BNB_Reversal",  "BNB", "data/timeframes/BNBUSDT_H4.csv", "data/timeframes/BNBUSDT_M15.csv", "reversal",     1.2, 1.8, "RANGE"),
    ("LINK_Trendline","LINK","data/timeframes/LINKUSDT_H4.csv","data/timeframes/LINKUSDT_M15.csv","trendline",    1.3, 2.0, "TREND"),
]

streams = []
for strat_id, sym, h4_path, m15_path, strat_type, sl_mult, tp_mult, regime in assets_config:
    df_h4 = pd.read_csv(h4_path)
    df_m15 = pd.read_csv(m15_path)
    df_h4["timestamp"] = pd.to_datetime(df_h4["timestamp"])
    df_m15["timestamp"] = pd.to_datetime(df_m15["timestamp"])

    df_h4["ema50_h4"] = df_h4["close"].ewm(span=50).mean()
    df_h4["macro_trend"] = np.where(df_h4["close"] > df_h4["ema50_h4"], 1, -1)

    df_m15 = pd.merge_asof(df_m15.sort_values("timestamp"), df_h4[["timestamp", "macro_trend"]].sort_values("timestamp"), on="timestamp", direction="backward")
    df_m15["macro_trend"] = df_m15["macro_trend"].fillna(1)
    
    if len(df_m15) > 20000:
        df_m15 = df_m15.iloc[-20000:].reset_index(drop=True)

    close = df_m15["close"]
    high = df_m15["high"]
    low = df_m15["low"]
    open_p = df_m15["open"]
    vol = df_m15["volume"]
    macro = df_m15["macro_trend"]

    tr = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
    atr = tr.rolling(14).mean().bfill()
    ema20 = close.ewm(span=20).mean()
    ema50 = close.ewm(span=50).mean()
    typical_p = (high + low + close) / 3.0
    rolling_vwap = (typical_p * vol).rolling(30).sum() / vol.rolling(30).sum().replace(0, 1)

    if strat_type == "donchian_12":
        h_12 = high.rolling(12).max().shift(1)
        l_12 = low.rolling(12).min().shift(1)
        bull = (macro == 1) & (close > open_p) & (close > rolling_vwap) & (ema20 > ema50) & (high >= h_12)
        bear = (macro == -1) & (close < open_p) & (close < rolling_vwap) & (ema20 < ema50) & (low <= l_12)
    elif strat_type == "smc":
        sw_h = high.rolling(10).max().shift(1)
        sw_l = low.rolling(10).min().shift(1)
        bull = (macro == 1) & (low.shift(1) < sw_l.shift(1)) & (close > open_p) & (close > rolling_vwap)
        bear = (macro == -1) & (high.shift(1) > sw_h.shift(1)) & (close < open_p) & (close < rolling_vwap)
    elif strat_type == "reversal":
        bb_mid = close.rolling(20).mean()
        bb_std = close.rolling(20).std()
        bb_lower = bb_mid - 2.0 * bb_std
        bb_upper = bb_mid + 2.0 * bb_std
        bull = (macro == 1) & (low <= bb_lower) & (close > open_p)
        bear = (macro == -1) & (high >= bb_upper) & (close < open_p)
    elif strat_type == "trendline":
        pivot_h = high.rolling(8).max().shift(1)
        pivot_l = low.rolling(8).min().shift(1)
        atr_expanding = tr > (atr * 1.15)
        bull = (macro == 1) & (high > pivot_h) & atr_expanding & (close > rolling_vwap)
        bear = (macro == -1) & (low < pivot_l) & atr_expanding & (close < rolling_vwap)

    s_df = pd.DataFrame({
        "timestamp": df_m15["timestamp"],
        "strategy_id": strat_id,
        "symbol": sym,
        "open": open_p, "high": high, "low": low, "close": close, "volume": vol, "atr": atr,
        "signal": np.where(bull, 1, np.where(bear, -1, 0)),
        "sl_mult": sl_mult, "tp_mult": tp_mult, "regime": regime
    })
    streams.append(s_df)

def run_true_shared_pool(streams, max_open_pos=4, max_per_symbol=2, risk_pct_per_pos=2.0, leverage=3.0):
    all_timestamps = sorted(list(set.intersection(*[set(df["timestamp"]) for df in streams])))
    t_first = all_timestamps[0]
    t_last = all_timestamps[-1]
    months_elapsed = max(0.1, abs((t_last - t_first).total_seconds()) / (86400.0 * 30.4375))

    ts_data = {t: {} for t in all_timestamps}
    for df in streams:
        df_indexed = df[df["timestamp"].isin(all_timestamps)].set_index("timestamp")
        for t, row in df_indexed.iterrows():
            ts_data[t][row["strategy_id"]] = row

    initial_capital = 1000.0
    capital = initial_capital
    peak_capital = capital
    max_drawdown = 0.0
    open_positions = []
    closed_trades = []
    prev_signals = {df["strategy_id"].iloc[0]: 0 for df in streams}
    fee = 0.0002

    concurrent_history = []

    for t in all_timestamps:
        bar_map = ts_data[t]
        
        # 1. Manage active positions with exact fast_backtester partial TP & Trailing
        remaining = []
        for pos in open_positions:
            sid = pos["strategy_id"]
            if sid not in bar_map:
                remaining.append(pos)
                continue
            b = bar_map[sid]
            c_high, c_low, c_close, c_atr = b["high"], b["low"], b["close"], b["atr"]
            direction = pos["direction"]
            entry_p = pos["entry_price"]
            sl = pos["sl"]
            tp = pos["tp"]
            size_usd = pos["size_usd"]
            peak_p = pos["peak_p"]
            partial = pos["partial_taken"]

            exit_now = False
            exit_price = c_close

            trail_mult = 3.0 if pos["regime"] == "TREND" else 1.8

            if direction == 1:
                if c_high > peak_p:
                    pos["peak_p"] = c_high
                    peak_p = c_high
                cand = peak_p - (c_atr * trail_mult)
                if cand > sl:
                    pos["sl"] = cand
                    sl = cand
                
                # Partial TP at 2.0x ATR with BE profit buffer (+0.25x ATR)
                if not partial and c_high >= entry_p + (c_atr * 2.0):
                    pos["partial_taken"] = True
                    gain = ((entry_p + c_atr * 2.0) - entry_p) / entry_p * (size_usd * 0.5)
                    capital += gain - (size_usd * 0.5 * fee)
                    pos["size_usd"] *= 0.5
                    size_usd = pos["size_usd"]
                    pos["sl"] = max(sl, entry_p + (c_atr * 0.25))
                    sl = pos["sl"]

                if c_high >= tp:
                    exit_now = True
                    exit_price = tp
                elif c_low <= sl:
                    exit_now = True
                    exit_price = sl
            else:
                if c_low < peak_p:
                    pos["peak_p"] = c_low
                    peak_p = c_low
                cand = peak_p + (c_atr * trail_mult)
                if cand < sl:
                    pos["sl"] = cand
                    sl = cand

                if not partial and c_low <= entry_p - (c_atr * 2.0):
                    pos["partial_taken"] = True
                    gain = (entry_p - (entry_p - c_atr * 2.0)) / entry_p * (size_usd * 0.5)
                    capital += gain - (size_usd * 0.5 * fee)
                    pos["size_usd"] *= 0.5
                    size_usd = pos["size_usd"]
                    pos["sl"] = min(sl, entry_p - (c_atr * 0.25))
                    sl = pos["sl"]

                if c_low <= tp:
                    exit_now = True
                    exit_price = tp
                elif c_high >= sl:
                    exit_now = True
                    exit_price = sl

            if exit_now:
                pnl_pct = (exit_price - entry_p) / entry_p if direction == 1 else (entry_p - exit_price) / entry_p
                trade_pnl = (pnl_pct * size_usd) - (size_usd * fee)
                capital += trade_pnl
                closed_trades.append({
                    "strategy_id": sid,
                    "symbol": pos["symbol"],
                    "pnl_usd": trade_pnl,
                    "pnl_pct": pnl_pct * 100.0
                })
            else:
                remaining.append(pos)
        open_positions = remaining

        concurrent_history.append(len(open_positions))

        # 2. Dynamic Drawdown Guard
        cur_dd = (peak_capital - capital) / peak_capital * 100.0 if peak_capital > 0 else 0.0
        dd_mult = 1.0 if cur_dd < 4.0 else (0.75 if cur_dd < 6.5 else (0.25 if cur_dd < 8.0 else 0.0))

        # 3. Enter new signals on first-come first-served from shared pool
        for sid, b in bar_map.items():
            sig = b["signal"]
            p_s = prev_signals[sid]
            prev_signals[sid] = sig

            is_new = (sig != 0) and (sig != p_s)
            
            # Check limits
            strat_already_open = any(p["strategy_id"] == sid for p in open_positions)
            sym_count = sum(1 for p in open_positions if p["symbol"] == b["symbol"])

            if is_new and len(open_positions) < max_open_pos and not strat_already_open and sym_count < max_per_symbol and dd_mult > 0:
                c_close, c_atr = b["close"], b["atr"]
                risk_usd = capital * (risk_pct_per_pos / 100.0) * dd_mult
                sl_dist = c_atr * b["sl_mult"]
                sl_pct = sl_dist / c_close

                if sl_pct > 0.001:
                    target_sz = risk_usd / sl_pct
                    max_allowed = (capital * leverage) / max_open_pos
                    sz = min(target_sz, max_allowed)

                    entry_p = c_close
                    sl_p = entry_p - sl_dist if sig == 1 else entry_p + sl_dist
                    tp_p = entry_p + (c_atr * b["tp_mult"]) if sig == 1 else entry_p - (c_atr * b["tp_mult"])

                    capital -= sz * fee
                    open_positions.append({
                        "strategy_id": sid,
                        "symbol": b["symbol"],
                        "direction": sig,
                        "entry_price": entry_p,
                        "sl": sl_p,
                        "tp": tp_p,
                        "peak_p": entry_p,
                        "size_usd": sz,
                        "partial_taken": False,
                        "regime": b["regime"]
                    })

        peak_capital = max(peak_capital, capital)
        cur_dd = (peak_capital - capital) / peak_capital * 100.0
        max_drawdown = max(max_drawdown, cur_dd)

    tot_roi = (capital - initial_capital) / initial_capital * 100.0
    comp_monthly = ((1.0 + (tot_roi / 100.0)) ** (1.0 / months_elapsed) - 1.0) * 100.0
    linear_monthly = tot_roi / months_elapsed
    wins = [t for t in closed_trades if t["pnl_usd"] > 0]
    wr = len(wins) / len(closed_trades) * 100.0 if closed_trades else 0.0
    losses = [t for t in closed_trades if t["pnl_usd"] <= 0]
    total_prof = sum(t["pnl_usd"] for t in wins)
    total_loss = abs(sum(t["pnl_usd"] for t in losses)) if losses else 1e-6
    pf = (total_prof / total_loss) if total_loss > 0 else (99.9 if total_prof > 0 else 0.0)

    return {
        "final_capital": round(capital, 2),
        "total_roi": round(tot_roi, 2),
        "comp_monthly": round(comp_monthly, 2),
        "linear_monthly": round(linear_monthly, 2),
        "max_drawdown": round(max_drawdown, 2),
        "total_trades": len(closed_trades),
        "win_rate": round(wr, 2),
        "profit_factor": round(pf, 2),
        "months": round(months_elapsed, 1),
        "avg_concurrent": round(np.mean(concurrent_history), 2),
        "max_concurrent": max(concurrent_history) if concurrent_history else 0,
        "trades_by_strategy": pd.Series([t["strategy_id"] for t in closed_trades]).value_counts().to_dict()
    }

print("\n=== BENCHMARK: SHARED POOL WITHOUT DEDICATED ALLOCATION (MULTIPLE OPEN POSITIONS) ===")
print("Configuration                              | Max Pos | Risk/Pos | Final Capital | Total Return | Comp Monthly | Linear Monthly | Max DD | Win Rate | Trades | Trades/Mo")
print("-------------------------------------------------------------------------------------------------------------------------------------------------------------------------")

experiments = [
    ("BTC Only (Max 2 Trades)", 2, 1, 3.0, [streams[0]]),
    ("Shared Pool (BTC+SOL, Max 2 Pos)", 2, 1, 2.5, [streams[0], streams[2]]),
    ("Shared Pool (BTC+SOL+LINK, Max 3 Pos)", 3, 1, 2.2, [streams[0], streams[2], streams[4]]),
    ("Shared Pool (All 5 Strats, Max 3 Pos)", 3, 2, 2.0, streams),
    ("Shared Pool (All 5 Strats, Max 4 Pos)", 4, 2, 1.8, streams),
    ("Shared Pool Aggressive (Max 4 Pos)", 4, 2, 2.5, streams),
]

for label, max_p, max_sym, rk, stream_input in experiments:
    res = run_true_shared_pool(stream_input, max_open_pos=max_p, max_per_symbol=max_sym, risk_pct_per_pos=rk, leverage=3.0)
    fc = res["final_capital"]
    tot = res["total_roi"]
    cm = res["comp_monthly"]
    lm = res["linear_monthly"]
    dd = res["max_drawdown"]
    wr = res["win_rate"]
    tc = res["total_trades"]
    mo = res["months"]
    print(f"{label:<42} |  {max_p:2d} pos  |   {rk:4.1f}%  | ${fc:13.2f} | +{tot:8.2f}% | +{cm:10.2f}%/mo | +{lm:12.2f}%/mo | {dd:5.2f}% | {wr:6.2f}% | {tc:6d} |  {tc/mo:5.1f}")
    if "All 5 Strats, Max 4 Pos" in label:
        print(f"   --> Detailed Trade Breakdown: {res['trades_by_strategy']}")
