

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import pandas as pd
import numpy as np
from core.analysis.fast_backtester import BacktestSimulator

# Load the ENTIRE multi-year intraday history: 156,779 15-minute bars (2017 to 2023, 6.3 Years, 75.6 Months)
df_h4 = pd.read_csv("data/timeframes/BTCUSD_H4.csv")
df_m15 = pd.read_csv("data/timeframes/BTCUSD_M15.csv")

df_h4["timestamp"] = pd.to_datetime(df_h4["timestamp"])
df_m15["timestamp"] = pd.to_datetime(df_m15["timestamp"])

print(f"Total H4 bars: {len(df_h4):,d} ({df_h4['timestamp'].iloc[0]} to {df_h4['timestamp'].iloc[-1]})")
print(f"Total M15 bars: {len(df_m15):,d} ({df_m15['timestamp'].iloc[0]} to {df_m15['timestamp'].iloc[-1]})")

# Calculate 4H Macro Trend across full history
df_h4["ema50_h4"] = df_h4["close"].ewm(span=50).mean()
df_h4["macro_trend"] = np.where(df_h4["close"] > df_h4["ema50_h4"], 1, -1)

# As-of merge to align 4H trend to 15M candles
df_m15 = pd.merge_asof(df_m15.sort_values("timestamp"), df_h4[["timestamp", "macro_trend"]].sort_values("timestamp"), on="timestamp", direction="backward")
df_m15["macro_trend"] = df_m15["macro_trend"].fillna(1)

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

# Test 12-Bar vs 14-Bar across the FULL 156,779 BARS
for lb in [12, 14]:
    h_lb = high.rolling(lb).max().shift(1)
    l_lb = low.rolling(lb).min().shift(1)

    bull = (macro == 1) & (close > open_p) & (close > rolling_vwap) & (ema20 > ema50) & (high >= h_lb)
    bear = (macro == -1) & (close < open_p) & (close < rolling_vwap) & (ema20 < ema50) & (low <= l_lb)

    sig = pd.DataFrame(index=df_m15.index)
    sig["signal"] = 0
    sig["atr"] = atr
    sig["conviction"] = 85.0
    sig["regime"] = "TREND"
    sig.loc[bull, "signal"] = 1
    sig.loc[bear, "signal"] = -1

    # ATR above is .bfill()'d over its 14-bar warmup while h_lb/l_lb first signal
    # at bar 12 - zero signals through bar 13 so no entry uses future-filled ATR.
    sig.loc[:13, "signal"] = 0

    sim = BacktestSimulator(slippage_pct=0.03, taker_fee_pct=0.02, initial_capital=1000.0, order_execution_mode="maker")
    res = sim.run_backtest(df_m15, sig, risk_per_trade_pct=2.5, atr_sl_mult=1.3, atr_tp_mult=2.0)

    mo = res["months_elapsed"]
    fc = res["final_capital"]
    tot = res["net_roi_total_pct"]
    cm = res["monthly_roi_pct"]
    lm = tot / mo
    dd = res["max_drawdown_pct"]
    wr = res["win_rate"]
    pf = res["profit_factor"]
    tc = res["total_trades"]
    print(f"\nDonchian {lb:2d}-Bar Full History ({len(df_m15):,d} bars / {mo:.1f} months / {mo/12.0:.1f} years):")
    print(f"  Final Capital: ${fc:,.2f} | Total ROI: {tot:+.2f}%")
    print(f"  Compounded Monthly ROI: {cm:+.2f}% / mo | Linear Monthly ROI: {lm:+.2f}% / mo")
    print(f"  Max Drawdown: {dd:.2f}% | Win Rate: {wr:.2f}% | Profit Factor: {pf:.2f} | Total Trades: {tc}")
