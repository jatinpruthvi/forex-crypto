import pandas as pd
import numpy as np

# Load real BTC 4h data
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
ema20 = close.ewm(span=20).mean()

# Base Expansion Signals
vol_surge = vol > vol.rolling(20).mean()
ema50_slope_up = ema50 > ema50.shift(3)
ema50_slope_down = ema50 < ema50.shift(3)
price_stretch = (close - ema50) / ema50

# 1. Idea A: VWAP / Volume-Weighted Confirmation
# Calculate rolling 30-bar VWAP
typical_price = (high + low + close) / 3.0
rolling_vwap = (typical_price * vol).rolling(30).sum() / vol.rolling(30).sum()

bull_base = (close > open_p) & large_candle & (close > ema50) & ema50_slope_up & vol_surge & (price_stretch < 0.05)
bear_base = (close < open_p) & large_candle & (close < ema50) & ema50_slope_down & vol_surge & (price_stretch > -0.05)

bull_vwap = bull_base & (close > rolling_vwap)
bear_vwap = bear_base & (close < rolling_vwap)

# 2. Idea B: ADX / Trend Strength Filter (avoid low-momentum false breakouts)
up_move = high - high.shift(1)
down_move = low.shift(1) - low
plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
safe_atr = atr.replace(0, 1e-6)
plus_di = 100.0 * (pd.Series(plus_dm).rolling(14).mean() / safe_atr)
minus_di = 100.0 * (pd.Series(minus_dm).rolling(14).mean() / safe_atr)
di_sum = (plus_di + minus_di).replace(0, 1e-6)
dx = 100.0 * (abs(plus_di - minus_di) / di_sum).replace(np.nan, 0)
adx = dx.rolling(14).mean()

bull_adx = bull_base & (adx > 20.0)
bear_adx = bear_base & (adx > 20.0)

from scripts.evaluate_breakeven_buffer import AdvancedExitSimulator
sim = AdvancedExitSimulator(slippage_pct=0.1, taker_fee_pct=0.055, initial_capital=323.0)

def test_signals(name, b_sig, s_sig):
    sig = pd.DataFrame(index=df.index)
    sig["signal"] = 0
    sig["atr"] = atr
    sig["conviction"] = 85.0
    sig.loc[b_sig, "signal"] = 1
    sig.loc[s_sig, "signal"] = -1
    res = sim.run_backtest_with_exit_tuning(df, sig, partial_atr_trigger=2.0, be_buffer_atr=0.25)
    print(f"{name:<25}: Monthly ROI: {res['monthly_roi']:5.2f}% | Max DD: {res['max_dd']:5.2f}% | Win Rate: {res['win_rate']:5.2f}% | PF: {res['pf']:4.2f} | Calmar: {res['calmar']:4.2f} | Trades: {res['trades']}")

print("="*85)
print("TESTING NEW ADVANCED SIGNAL INTELLIGENCE FILTERS:")
print("="*85)
test_signals("1. Current Baseline", bull_base, bear_base)
test_signals("2. + VWAP Institutional Bias", bull_vwap, bear_vwap)
test_signals("3. + ADX Momentum Filter (>20)", bull_adx, bear_adx)
test_signals("4. VWAP + ADX Synergy", bull_vwap & (adx > 20.0), bear_vwap & (adx > 20.0))
print("="*85)
