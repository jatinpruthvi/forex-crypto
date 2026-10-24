import pandas as pd
import numpy as np
from core.analysis.fast_backtester import BacktestSimulator

# Load 10-year daily BTC (2014 - 2024, 3,608 daily bars)
df_10y = pd.read_csv("data/btc_10yr_daily.csv")
df_10y["timestamp"] = pd.to_datetime(df_10y["timestamp"])

close = df_10y["close"]
high = df_10y["high"]
low = df_10y["low"]
open_p = df_10y["open"]
vol = df_10y["volume"]

tr = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
atr = tr.rolling(14).mean().bfill()
ema20 = close.ewm(span=20).mean()
ema50 = close.ewm(span=50).mean()
typical_p = (high + low + close) / 3.0
rolling_vwap = (typical_p * vol).rolling(30).sum() / vol.rolling(30).sum().replace(0, 1)

high_14 = high.rolling(14).max().shift(1)
low_14 = low.rolling(14).min().shift(1)

# Spot Strategy (Long Only)
bull = (close > open_p) & (close > ema50) & (close > rolling_vwap) & (ema20 > ema50) & (high >= high_14)
# Futures Strategy (Long & Short)
bear = (close < open_p) & (close < ema50) & (close < rolling_vwap) & (ema20 < ema50) & (low <= low_14)

sig_spot = pd.DataFrame(index=df_10y.index)
sig_spot["signal"] = 0
sig_spot["atr"] = atr
sig_spot["conviction"] = 85.0
sig_spot["regime"] = "TREND"
sig_spot.loc[bull, "signal"] = 1

sig_fut = pd.DataFrame(index=df_10y.index)
sig_fut["signal"] = 0
sig_fut["atr"] = atr
sig_fut["conviction"] = 85.0
sig_fut["regime"] = "TREND"
sig_fut.loc[bull, "signal"] = 1
sig_fut.loc[bear, "signal"] = -1

sim = BacktestSimulator(slippage_pct=0.03, taker_fee_pct=0.02, initial_capital=1000.0, order_execution_mode="maker")
r_spot = sim.run_backtest(df_10y, sig_spot, risk_per_trade_pct=3.0, atr_sl_mult=1.6, atr_tp_mult=2.4)
r_fut = sim.run_backtest(df_10y, sig_fut, risk_per_trade_pct=3.0, atr_sl_mult=1.6, atr_tp_mult=2.4)

months = r_spot["months_elapsed"]

print("=== 10-YEAR HISTORICAL VALIDATION (2014 - 2024 / 3,608 BARS / 118.5 MONTHS) ===")
print("Strategy Horizon | Final Capital | Total Return | Comp Monthly | Linear Monthly | Max Drawdown | Win Rate | Profit Factor | Trades")
print("-----------------------------------------------------------------------------------------------------------------------------------")
for r, name in [(r_spot, "10-Year Daily Spot Only   "), (r_fut, "10-Year Daily Futures 2-Way")]:
    fc = r["final_capital"]
    tot = r["net_roi_total_pct"]
    cm = r["monthly_roi_pct"]
    lm = tot / months
    dd = r["max_drawdown_pct"]
    wr = r["win_rate"]
    pf = r["profit_factor"]
    tc = r["total_trades"]
    print(f"{name} | ${fc:13.2f} | +{tot:10.2f}% | +{cm:10.2f}%/mo | +{lm:12.2f}%/mo | {dd:11.2f}% | {wr:7.2f}% | {pf:13.2f} | {tc:6d}")
