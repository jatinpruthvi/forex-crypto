

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import pandas as pd
import numpy as np

# Load dataset
df = pd.read_csv("data/btc_real_dataset.csv")
df["timestamp"] = df["date"] if "date" in df.columns else df.index

close = df["close"].values
high = df["high"].values
low = df["low"].values
vol = df["volume"].values
open_p = df["open"].values
n = len(df)

tr = np.maximum(high - low, np.maximum(abs(high - np.roll(close, 1)), abs(low - np.roll(close, 1))))
tr[0] = high[0] - low[0]  # np.roll wraps the LAST close into bar 0 - kill that lookahead
atr14 = pd.Series(tr).rolling(14, min_periods=1).mean().values
ema50 = pd.Series(close).ewm(span=50).mean().values
vol_sma20 = pd.Series(vol).rolling(20, min_periods=1).mean().replace(0, 1e-6).values

large_candle = (high - low) > (1.8 * atr14)
vol_surge = vol > vol_sma20
ema50_slope_up = ema50 > np.roll(ema50, 3)
ema50_slope_down = ema50 < np.roll(ema50, 3)
# np.roll wraps the LAST bars' ema into the first 3 slots - kill that lookahead
ema50_slope_up[:3] = False
ema50_slope_down[:3] = False
price_stretch = (close - ema50) / np.maximum(ema50, 1.0)

# Rolling VWAP
typical_p = (high + low + close) / 3.0
rolling_vol = pd.Series(vol).rolling(30, min_periods=1).sum().replace(0, 1).values
vwap30 = (pd.Series(typical_p * vol).rolling(30, min_periods=1).sum().values) / rolling_vol

bull_vwap = (close > open_p) & large_candle & (close > ema50) & ema50_slope_up & vol_surge & (price_stretch < 0.05) & (close > vwap30)
bear_vwap = (close < open_p) & large_candle & (close < ema50) & ema50_slope_down & vol_surge & (price_stretch > -0.05) & (close < vwap30)

signals = pd.DataFrame(index=df.index)
signals["signal"] = 0
signals["atr"] = atr14
signals["conviction"] = 85.0
signals.loc[bull_vwap, "signal"] = 1
signals.loc[bear_vwap, "signal"] = -1

from scripts.evaluate_breakeven_buffer import AdvancedExitSimulator
sim = AdvancedExitSimulator(slippage_pct=0.1, taker_fee_pct=0.055, initial_capital=323.0)
res = sim.run_backtest_with_exit_tuning(df, signals, partial_atr_trigger=2.0, be_buffer_atr=0.25)

print("="*75)
print("VERIFICATION OF INTEGRATED STRATEGY WITH BE BUFFER + VWAP:")
print(f"  Monthly ROI:   {res['monthly_roi']:.2f}%")
print(f"  Max Drawdown:  {res['max_dd']:.2f}%")
print(f"  Win Rate:      {res['win_rate']:.2f}% ({res['trades']} trades)")
print(f"  Profit Factor: {res['pf']:.2f}")
print(f"  Calmar Ratio:  {res['calmar']:.2f}")
print("="*75)
