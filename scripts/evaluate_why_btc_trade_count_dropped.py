import pandas as pd
import numpy as np

# Let's inspect why BTC standalone in the script took 105 trades vs 398 trades earlier
# Earlier script: ran fast_backtester on df_m15 directly with signals
from core.analysis.fast_backtester import BacktestSimulator

df_h4 = pd.read_csv("data/timeframes/BTCUSD_H4.csv")
df_m15 = pd.read_csv("data/timeframes/BTCUSD_M15.csv")

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

h_12 = high.rolling(12).max().shift(1)
l_12 = low.rolling(12).min().shift(1)

bull = (macro == 1) & (close > open_p) & (close > rolling_vwap) & (ema20 > ema50) & (high >= h_12)
bear = (macro == -1) & (close < open_p) & (close < rolling_vwap) & (ema20 < ema50) & (low <= l_12)

sig = pd.DataFrame(index=df_m15.index)
sig["signal"] = 0
sig["atr"] = atr
sig["conviction"] = 85.0
sig["regime"] = "TREND"
sig.loc[bull, "signal"] = 1
sig.loc[bear, "signal"] = -1

sim = BacktestSimulator(slippage_pct=0.03, taker_fee_pct=0.02, initial_capital=1000.0, order_execution_mode="maker")
# max_open_trades=2 in fast_backtester vs max_open_trades=1
res_2 = sim.run_backtest(df_m15, sig, risk_per_trade_pct=3.0, atr_sl_mult=1.3, atr_tp_mult=2.0, max_open_trades=2)
res_1 = sim.run_backtest(df_m15, sig, risk_per_trade_pct=3.0, atr_sl_mult=1.3, atr_tp_mult=2.0, max_open_trades=1)

print(f"BTC Standalone (Max 2 Open Trades): Final ${res_2['final_capital']} | Comp Monthly: +{res_2['monthly_roi_pct']}% | Total: +{res_2['net_roi_total_pct']}% | Trades: {res_2['total_trades']}")
print(f"BTC Standalone (Max 1 Open Trade ): Final ${res_1['final_capital']} | Comp Monthly: +{res_1['monthly_roi_pct']}% | Total: +{res_1['net_roi_total_pct']}% | Trades: {res_1['total_trades']}")
