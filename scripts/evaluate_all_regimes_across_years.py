

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import pandas as pd
import numpy as np
from core.analysis.fast_backtester import BacktestSimulator

df_h4 = pd.read_csv("data/timeframes/BTCUSD_H4.csv")
df_m15 = pd.read_csv("data/timeframes/BTCUSD_M15.csv")

df_h4["timestamp"] = pd.to_datetime(df_h4["timestamp"])
df_m15["timestamp"] = pd.to_datetime(df_m15["timestamp"])

df_h4["ema50_h4"] = df_h4["close"].ewm(span=50).mean()
df_h4["macro_trend"] = np.where(df_h4["close"] > df_h4["ema50_h4"], 1, -1)

df_m15 = pd.merge_asof(df_m15.sort_values("timestamp"), df_h4[["timestamp", "macro_trend"]].sort_values("timestamp"), on="timestamp", direction="backward")
df_m15["macro_trend"] = df_m15["macro_trend"].fillna(1)
df_m15["year"] = df_m15["timestamp"].dt.year

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

# 1. Trend Breakout (Donchian 12)
h_12 = high.rolling(12).max().shift(1)
l_12 = low.rolling(12).min().shift(1)
bull_trend = pd.Series((macro == 1) & (close > open_p) & (close > rolling_vwap) & (ema20 > ema50) & (high >= h_12), index=df_m15.index)
bear_trend = pd.Series((macro == -1) & (close < open_p) & (close < rolling_vwap) & (ema20 < ema50) & (low <= l_12), index=df_m15.index)

# 2. Mean Reversion
bb_mid = close.rolling(20).mean()
bb_std = close.rolling(20).std()
bb_lower = bb_mid - 2.0 * bb_std
bb_upper = bb_mid + 2.0 * bb_std
bull_range = pd.Series((low <= bb_lower) & (close > open_p), index=df_m15.index)
bear_range = pd.Series((high >= bb_upper) & (close < open_p), index=df_m15.index)

# 3. Dynamic ADX Trend Filter
plus_dm = high.diff().where((high.diff() > low.diff().abs()) & (high.diff() > 0), 0)
minus_dm = (-low.diff()).where(((-low.diff()) > high.diff().abs()) & (-low.diff() > 0), 0)
tr_14 = tr.rolling(14).mean().replace(0, 1e-6)
plus_di = 100 * (plus_dm.rolling(14).mean() / tr_14)
minus_di = 100 * (minus_dm.rolling(14).mean() / tr_14)
dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, 1e-6)
adx = dx.rolling(14).mean().bfill()

is_trending = pd.Series(adx >= 22.0, index=df_m15.index)
bull_hybrid = pd.Series(np.where(is_trending, bull_trend, bull_range), index=df_m15.index)
bear_hybrid = pd.Series(np.where(is_trending, bear_trend, bear_range), index=df_m15.index)

# Warmup honesty: ATR is .bfill()'d through bar 12 and ADX through ~bar 27, and the
# first possible Donchian signal is bar 12 - zero ALL strategy signals through bar 29
# so no entry (or regime tag) can use future-filled indicators.
for _s in (bull_trend, bear_trend, bull_range, bear_range, bull_hybrid, bear_hybrid):
    _s.iloc[:30] = False

sim = BacktestSimulator(slippage_pct=0.03, taker_fee_pct=0.02, initial_capital=1000.0, order_execution_mode="maker")

print("=== TESTING STRATEGIES ACROSS DIFFERENT HISTORICAL REGIMES ===")

for strat_name, (b_sig, s_sig, reg_tag) in [
    ("Pure Trend Breakout (Donchian 12)", (bull_trend, bear_trend, "TREND")),
    ("Pure Mean-Reversion (RSI/BB)", (bull_range, bear_range, "RANGE")),
    ("Adaptive Hybrid (Regime-Switched)", (bull_hybrid, bear_hybrid, "ADAPTIVE"))
]:
    print(f"\n--- Strategy: {strat_name} ---")
    print("Year | Duration | Net Return | Comp Monthly | Max Drawdown | Trades | Win Rate | Profit Factor")
    print("---------------------------------------------------------------------------------------------")
    
    for yr in sorted(df_m15["year"].unique()):
        mask = df_m15["year"] == yr
        sub_df = df_m15[mask].reset_index(drop=True)
        if len(sub_df) < 500:
            continue
            
        sub_b = b_sig[mask].reset_index(drop=True)
        sub_s = s_sig[mask].reset_index(drop=True)
        
        sig = pd.DataFrame(index=sub_df.index)
        sig["signal"] = 0
        sig["atr"] = atr[mask].reset_index(drop=True)
        sig["conviction"] = 85.0
        sig["regime"] = "TREND" if reg_tag == "TREND" else ("RANGE" if reg_tag == "RANGE" else np.where(is_trending[mask].reset_index(drop=True), "TREND", "RANGE"))
        sig.loc[sub_b, "signal"] = 1
        sig.loc[sub_s, "signal"] = -1
        
        sl_m = 1.3 if reg_tag != "RANGE" else 1.2
        tp_m = 2.0 if reg_tag != "RANGE" else 1.8
        
        res = sim.run_backtest(sub_df, sig, risk_per_trade_pct=2.5, atr_sl_mult=sl_m, atr_tp_mult=tp_m)
        tot = res["net_roi_total_pct"]
        cm = res["monthly_roi_pct"]
        mo = res["months_elapsed"]
        dd = res["max_drawdown_pct"]
        tc = res["total_trades"]
        wr = res["win_rate"]
        pf = res["profit_factor"]
        print(f"{yr} |  {mo:4.1f} mo | {tot:+9.2f}% | {cm:+11.2f}%/mo | {dd:11.2f}% | {tc:6d} | {wr:6.2f}% | {pf:13.2f}")
