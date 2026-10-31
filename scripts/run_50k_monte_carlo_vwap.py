

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import numpy as np
import pandas as pd
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
res = sim.run_backtest_with_exit_tuning(df, signals, partial_atr_trigger=2.0, be_buffer_atr=0.25)

# Extract trade results
print(f"Optimal Strategy: Monthly ROI: {res['monthly_roi']:.2f}% | Max DD: {res['max_dd']:.2f}% | Win Rate: {res['win_rate']:.2f}% | Calmar: {res['calmar']:.2f} | PF: {res['pf']:.2f}")

# 50,000 Monte Carlo Simulation
np.random.seed(42)
n_sims = 50000
ruin_count = 0
max_dds = []

# Trade PnL bootstrap: resample the realized trade PnL sequence with
# replacement 50,000 times. If equity falls below $161.50 (50% of the
# $323 start), that path counts as ruin.
trade_pnls = np.asarray(res["trade_pnls"], dtype=float)
if trade_pnls.size == 0:
    raise SystemExit("No closed trades to bootstrap - cannot run Monte Carlo.")

print(f"Running 50,000 Monte Carlo Permutations over {trade_pnls.size} trades...")
rng = np.random.default_rng(42)
ruin_thresh = 0.5 * 323.0
start_cap = 323.0

max_dds = []
ruin_count = 0
final_caps = []
for _ in range(n_sims):
    seq = rng.choice(trade_pnls, size=trade_pnls.size, replace=True)
    equity = start_cap
    peak = start_cap
    max_dd = 0.0
    ruined = False
    for pnl in seq:
        equity += pnl
        if equity <= ruin_thresh:
            ruined = True
            break
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak
        if dd > max_dd:
            max_dd = dd
    if ruined:
        ruin_count += 1
    max_dds.append(max_dd)
    final_caps.append(equity)

max_dds = np.asarray(max_dds)
final_caps = np.asarray(final_caps)
print(f"Ruin probability (< 50% equity): {ruin_count / n_sims * 100.0:.3f}% ({ruin_count}/{n_sims})")
print(f"Max DD  - mean: {max_dds.mean() * 100:.2f}% | p95: {np.percentile(max_dds, 95) * 100:.2f}% | worst: {max_dds.max() * 100:.2f}%")
print(f"Final equity - mean: ${final_caps.mean():.2f} | p5: ${np.percentile(final_caps, 5):.2f} | p95: ${np.percentile(final_caps, 95):.2f}")
neg = (final_caps < start_cap).mean() * 100.0
print(f"Paths ending below start capital: {neg:.2f}%")
