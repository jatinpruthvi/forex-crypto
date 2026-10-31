import pandas as pd
import numpy as np
import joblib

df = pd.read_csv("data/btc_real_dataset.csv")
close = df["close"].values
high = df["high"].values
low = df["low"].values
open_p = df["open"].values
vol = df["volume"].values
n = len(df)

# Technical Feature Baselines
tr1 = high - low
tr2 = np.abs(high - np.roll(close, 1))
tr3 = np.abs(low - np.roll(close, 1))
tr2[0] = tr1[0]
tr3[0] = tr1[0]
tr = np.maximum(tr1, np.maximum(tr2, tr3))
atr14 = pd.Series(tr).rolling(14, min_periods=1).mean().values

ema50 = pd.Series(close).ewm(span=50).mean().values
vol_sma20 = pd.Series(vol).rolling(20, min_periods=1).mean().replace(0, 1e-6).values

# 1. Base Expansion Signals
large_candle = (high - low) > (1.8 * atr14)
vol_surge = vol > vol_sma20
ema50_slope_up = ema50 > np.roll(ema50, 3)
ema50_slope_down = ema50 < np.roll(ema50, 3)
price_stretch = (close - ema50) / np.maximum(ema50, 1.0)

bull_expansion = (close > open_p) & large_candle & (close > ema50) & ema50_slope_up & vol_surge & (price_stretch < 0.05)
bear_expansion = (close < open_p) & large_candle & (close < ema50) & ema50_slope_down & vol_surge & (price_stretch > -0.05)

raw_signals = np.zeros(n, dtype=int)
raw_signals[bull_expansion] = 1
raw_signals[bear_expansion] = -1

# Load trained XGBoost model
clf = joblib.load("models/model_xgb.pkl")
X_features = pd.DataFrame({
    "returns_1": pd.Series(close).pct_change(1).fillna(0.0),
    "returns_4": pd.Series(close).pct_change(4).fillna(0.0),
    "vol_20": pd.Series(close).pct_change(1).rolling(20, min_periods=1).std().fillna(0.0),
    "vol_ratio": vol / vol_sma20,
    "trend_dist": (close - ema50) / np.maximum(close, 1.0),
    "ema50_slope": (ema50 - np.roll(ema50, 3)) / np.maximum(close, 1.0),
    "atr_rel": atr14 / np.maximum(close, 1.0),
})
probs = clf.predict_proba(X_features)[:, 1]

# 2. Intelligence Module A: Regime-Adaptive Trailing Stops
# In TREND regimes (Hurst > 0.55): wide trailing (2.8x ATR) to capture full moves.
# In RANGE/TRANSITION regimes: tighter trailing (1.8x ATR) to lock profits quickly.
returns_arr = np.diff(np.log(np.maximum(close, 1e-8)))
hurst_arr = np.full(n, 0.5)
for i in range(50, n):
    r_chunk = returns_arr[max(0, i-50):i]
    if len(r_chunk) > 10 and np.std(r_chunk) > 1e-6:
        dev = r_chunk - np.mean(r_chunk)
        rs = (np.max(np.cumsum(dev)) - np.min(np.cumsum(dev))) / np.std(r_chunk)
        hurst_arr[i] = min(1.0, max(0.0, np.log(max(1.1, rs)) / np.log(len(r_chunk))))

# 3. Intelligence Module B: Partial TP scaling (taking 33% at 1.5x ATR, 33% at 2.5x ATR, trailing rest)
def run_intelligent_sim(use_adaptive_trail=True, use_ml_sizing=True, dynamic_tp=True):
    capital = 323.0
    initial_cap = capital
    peak_capital = capital
    max_dd = 0.0
    closed_trades = []
    open_trades = []
    taker_fee = 0.00055
    slippage = 0.001
    leverage = 2.5
    prev_sig = 0
    months_elapsed = (n * 4.0) / (24.0 * 30.4)

    for i in range(1, n):
        c_close = close[i]
        c_high = high[i]
        c_low = low[i]
        c_atr = max(c_close * 0.005, atr14[i])
        sig = raw_signals[i]
        p = probs[i]
        h_val = hurst_arr[i]

        # ML Sizing Multiplier
        if use_ml_sizing:
            if sig == 1:
                size_mult = 1.35 if p >= 0.53 else (0.40 if p < 0.47 else 1.0)
            elif sig == -1:
                size_mult = 1.35 if p <= 0.47 else (0.40 if p > 0.53 else 1.0)
            else:
                size_mult = 1.0
        else:
            size_mult = 1.0

        # Drawdown escalation throttle
        curr_dd = (peak_capital - capital) / peak_capital * 100.0 if peak_capital > 0 else 0.0
        if curr_dd < 3.0: dd_mult = 1.0
        elif curr_dd < 5.0: dd_mult = 0.75
        elif curr_dd < 7.0: dd_mult = 0.50
        elif curr_dd < 8.0: dd_mult = 0.25
        else: dd_mult = 0.0

        # Adaptive Trailing Multiplier
        if use_adaptive_trail:
            trailing_mult = 2.8 if h_val >= 0.55 else 1.8
        else:
            trailing_mult = 2.5

        rem = []
        for t in open_trades:
            direction = t['dir']
            entry_p = t['entry_p']
            sl = t['sl']
            tp = t['tp']
            size_usd = t['size_usd']
            sl_bar_start = t['sl']  # bar-START stop: ratchets are future-only
            peak_p = t['peak_p']
            partial = t['partial']
            ex = False
            ex_p = c_close

            if direction == 1:
                if c_high > peak_p:
                    t['peak_p'] = c_high
                    peak_p = c_high
                trail = peak_p - (c_atr * trailing_mult)
                if trail > sl:
                    t['sl'] = trail
                    sl = trail

                # Dynamic Partial TP
                if dynamic_tp and not partial and c_high >= entry_p + (c_atr * 2.0):
                    t['partial'] = True
                    gain = ((entry_p + c_atr * 2.0) - entry_p) / entry_p * (size_usd * 0.5)
                    capital += (gain - (size_usd * 0.5 * taker_fee))
                    t['size_usd'] *= 0.5
                    size_usd = t['size_usd']  # exit must use post-partial size
                    t['sl'] = max(sl, entry_p)

                if c_low <= sl_bar_start:
                    ex = True
                    ex_p = sl_bar_start * (1.0 - slippage)
                elif c_high >= tp:
                    ex = True
                    ex_p = tp * (1.0 - slippage)
            else:
                if c_low < peak_p:
                    t['peak_p'] = c_low
                    peak_p = c_low
                trail = peak_p + (c_atr * trailing_mult)
                if trail < sl:
                    t['sl'] = trail
                    sl = trail

                if dynamic_tp and not partial and c_low <= entry_p - (c_atr * 2.0):
                    t['partial'] = True
                    gain = (entry_p - (entry_p - c_atr * 2.0)) / entry_p * (size_usd * 0.5)
                    capital += (gain - (size_usd * 0.5 * taker_fee))
                    t['size_usd'] *= 0.5
                    size_usd = t['size_usd']  # exit must use post-partial size
                    t['sl'] = min(sl, entry_p)

                if c_high >= sl_bar_start:
                    ex = True
                    ex_p = sl_bar_start * (1.0 + slippage)
                elif c_low <= tp:
                    ex = True
                    ex_p = tp * (1.0 + slippage)

            if ex:
                pnl_pct = (ex_p - entry_p) / entry_p if direction == 1 else (entry_p - ex_p) / entry_p
                pnl_usd = (pnl_pct * size_usd) - (size_usd * taker_fee)
                capital += pnl_usd
                closed_trades.append({'pnl_usd': pnl_usd, 'pnl_pct': pnl_pct * 100.0})
            else:
                rem.append(t)

        open_trades = rem
        is_new = (sig != 0) and (sig != prev_sig)
        prev_sig = sig

        if is_new and len(open_trades) < 2 and size_mult > 0 and dd_mult > 0:
            eff_risk = 3.5 * dd_mult * size_mult
            risk_usd = capital * (eff_risk / 100.0)
            sl_dist = c_atr * 1.6
            sl_pct = sl_dist / c_close
            if sl_pct > 0.001:
                targ_size = risk_usd / sl_pct
                max_size = (capital * leverage) / 2
                sz = min(targ_size, max_size)
                if sig == 1:
                    act_entry = c_close * (1.0 + slippage)
                    sl_p = act_entry - sl_dist
                    tp_p = act_entry + (c_atr * 2.4)
                else:
                    act_entry = c_close * (1.0 - slippage)
                    sl_p = act_entry + sl_dist
                    tp_p = act_entry - (c_atr * 2.4)
                capital -= sz * taker_fee
                open_trades.append({
                    'dir': sig, 'entry_p': act_entry, 'sl': sl_p, 'tp': tp_p,
                    'peak_p': act_entry, 'size_usd': sz, 'partial': False
                })

        peak_capital = max(peak_capital, capital)
        curr_dd = (peak_capital - capital) / peak_capital * 100.0
        max_dd = max(max_dd, curr_dd)

    tot_trades = len(closed_trades)
    wins = [t for t in closed_trades if t['pnl_usd'] > 0]
    win_rate = (len(wins) / tot_trades * 100.0) if tot_trades > 0 else 0.0
    net_roi = (capital - initial_cap) / initial_cap * 100.0
    monthly_roi = ((1.0 + (net_roi / 100.0)) ** (1.0 / months_elapsed) - 1.0) * 100.0
    tot_profit = sum(t['pnl_usd'] for t in wins)
    tot_loss = abs(sum(t['pnl_usd'] for t in closed_trades if t['pnl_usd'] <= 0)) if len(wins) < tot_trades else 1e-6
    pf = tot_profit / tot_loss if tot_loss > 0 else 0.0

    return {
        'monthly_roi': monthly_roi,
        'max_dd': max_dd,
        'win_rate': win_rate,
        'trades': tot_trades,
        'pf': pf,
        'calmar': monthly_roi / max_dd if max_dd > 0 else 0.0
    }

print("="*75)
print("INTELLIGENCE UPGRADE TEST RESULTS:")
print("="*75)
r1 = run_intelligent_sim(use_adaptive_trail=False, use_ml_sizing=False, dynamic_tp=False)
print(f"1. Static Baseline:            Monthly ROI: {r1['monthly_roi']:5.2f}% | Max DD: {r1['max_dd']:5.2f}% | Win Rate: {r1['win_rate']:5.2f}% | Calmar: {r1['calmar']:4.2f}")

r2 = run_intelligent_sim(use_adaptive_trail=False, use_ml_sizing=True, dynamic_tp=False)
print(f"2. + ML Dynamic Sizing:        Monthly ROI: {r2['monthly_roi']:5.2f}% | Max DD: {r2['max_dd']:5.2f}% | Win Rate: {r2['win_rate']:5.2f}% | Calmar: {r2['calmar']:4.2f}")

r3 = run_intelligent_sim(use_adaptive_trail=True, use_ml_sizing=True, dynamic_tp=False)
print(f"3. + Regime-Adaptive Trail:    Monthly ROI: {r3['monthly_roi']:5.2f}% | Max DD: {r3['max_dd']:5.2f}% | Win Rate: {r3['win_rate']:5.2f}% | Calmar: {r3['calmar']:4.2f}")

r4 = run_intelligent_sim(use_adaptive_trail=True, use_ml_sizing=True, dynamic_tp=True)
print(f"4. Full Intelligence Stack:    Monthly ROI: {r4['monthly_roi']:5.2f}% | Max DD: {r4['max_dd']:5.2f}% | Win Rate: {r4['win_rate']:5.2f}% | Calmar: {r4['calmar']:4.2f}")
print("="*75)
