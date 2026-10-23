import pandas as pd
import numpy as np
from core.analysis.fast_backtester import BacktestSimulator

# Load BTC M15 and H4
df_h4 = pd.read_csv("data/timeframes/BTCUSD_H4.csv")
df_m15 = pd.read_csv("data/timeframes/BTCUSD_M15.csv")

df_h4["timestamp"] = pd.to_datetime(df_h4["timestamp"])
df_m15["timestamp"] = pd.to_datetime(df_m15["timestamp"])

df_h4["ema50_h4"] = df_h4["close"].ewm(span=50).mean()
df_h4["macro_trend"] = np.where(df_h4["close"] > df_h4["ema50_h4"], 1, -1)

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

h_12 = high.rolling(12).max().shift(1)
l_12 = low.rolling(12).min().shift(1)

bull = (macro == 1) & (close > open_p) & (close > rolling_vwap) & (ema20 > ema50) & (high >= h_12)
bear = (macro == -1) & (close < open_p) & (close < rolling_vwap) & (ema20 < ema50) & (low <= l_12)

sig_all = pd.DataFrame(index=df_m15.index)
sig_all["signal"] = 0
sig_all["atr"] = atr
sig_all["conviction"] = 85.0
sig_all["regime"] = "TREND"
sig_all.loc[bull, "signal"] = 1
sig_all.loc[bear, "signal"] = -1

df_m15["year"] = df_m15["timestamp"].dt.year
sim = BacktestSimulator(slippage_pct=0.03, taker_fee_pct=0.02, initial_capital=1000.0, order_execution_mode="maker")

print("=== YEAR-BY-YEAR ROLLING PERFORMANCE ACROSS FULL HISTORY (2017 - 2023) ===")
print("Year | Duration (Mo) | Bars   | Final Capital | Net Return | Comp Monthly | Max Drawdown | Trades | Win Rate | Profit Factor")
print("---------------------------------------------------------------------------------------------------------------------------")

for yr in sorted(df_m15["year"].unique()):
    mask = df_m15["year"] == yr
    sub_df = df_m15[mask].reset_index(drop=True)
    sub_sig = sig_all[mask].reset_index(drop=True)
    
    if len(sub_df) < 500:
        continue

    res = sim.run_backtest(sub_df, sub_sig, risk_per_trade_pct=3.0, atr_sl_mult=1.3, atr_tp_mult=2.0)
    fc = res["final_capital"]
    tot = res["net_roi_total_pct"]
    cm = res["monthly_roi_pct"]
    mo = res["months_elapsed"]
    dd = res["max_drawdown_pct"]
    tc = res["total_trades"]
    wr = res["win_rate"]
    pf = res["profit_factor"]
    print(f"{yr} |    {mo:4.1f} mo   | {len(sub_df):6d} | ${fc:13.2f} | +{tot:8.2f}% | +{cm:10.2f}%/mo | {dd:11.2f}% | {tc:6d} | {wr:7.2f}% | {pf:13.2f}")
