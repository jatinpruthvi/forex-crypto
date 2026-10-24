import pandas as pd
import numpy as np
from scripts.evaluate_breakeven_buffer import AdvancedExitSimulator

df = pd.read_csv("data/btc_real_dataset.csv")
df["timestamp"] = df["date"] if "date" in df.columns else df.index

close = df["close"]
high = df["high"]
low = df["low"]
vol = df["volume"]
open_p = df["open"]

tr = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
atr = tr.rolling(14).mean()
large_candle = (high - low) > 1.8 * atr
ema50 = close.ewm(span=50).mean()

vol_surge = vol > vol.rolling(20).mean()
ema50_slope_up = ema50 > ema50.shift(3)
ema50_slope_down = ema50 < ema50.shift(3)
price_stretch = (close - ema50) / ema50

# Rolling VWAP
typical_price = (high + low + close) / 3.0
rolling_vwap = (typical_price * vol).rolling(30).sum() / vol.rolling(30).sum()

bull_vwap = (close > open_p) & large_candle & (close > ema50) & ema50_slope_up & vol_surge & (price_stretch < 0.05) & (close > rolling_vwap)
bear_vwap = (close < open_p) & large_candle & (close < ema50) & ema50_slope_down & vol_surge & (price_stretch > -0.05) & (close < rolling_vwap)

signals = pd.DataFrame(index=df.index)
signals["signal"] = 0
signals["atr"] = atr
signals["conviction"] = 85.0
signals.loc[bull_vwap, "signal"] = 1
signals.loc[bear_vwap, "signal"] = -1

sim = AdvancedExitSimulator(slippage_pct=0.1, taker_fee_pct=0.055, initial_capital=323.0)

for risk in [3.0, 3.5, 4.0]:
    for be_buf in [0.20, 0.25, 0.30]:
        res = sim.run_backtest_with_exit_tuning(df, signals, partial_atr_trigger=2.0, be_buffer_atr=be_buf)
        print(f"Risk: {risk}% | BE Buffer: +{be_buf:4.2f}x ATR | Monthly ROI: {res['monthly_roi']:5.2f}% | Max DD: {res['max_dd']:5.2f}% | Win Rate: {res['win_rate']:5.2f}% | PF: {res['pf']:4.2f} | Calmar: {res['calmar']:4.2f}")
