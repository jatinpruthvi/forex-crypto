

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import pandas as pd
import os
import numpy as np
import joblib
from scripts.evaluate_dd_scaling import DynamicDDBacktestSimulator
import xgboost as xgb

df = pd.read_csv("data/btc_real_dataset.csv")
df["timestamp"] = df["date"] if "date" in df.columns else df.index

close = df["close"].values
high = df["high"].values
low = df["low"].values
open_p = df["open"].values
vol = df["volume"].values
n = len(df)
# 1000 4h candles = 4000 hours = 5.48 months
months_elapsed = (n * 4.0) / (24.0 * 30.4)

tr1 = high - low
_prev_close = np.concatenate([close[:1], close[:-1]])  # no np.roll wrap-around
tr2 = np.abs(high - _prev_close)
tr3 = np.abs(low - _prev_close)
tr2[0] = tr1[0]
tr3[0] = tr1[0]
tr = np.maximum(tr1, np.maximum(tr2, tr3))
atr14 = pd.Series(tr).rolling(14, min_periods=1).mean().values

ema50 = pd.Series(close).ewm(span=50).mean().values
vol_sma20 = pd.Series(vol).rolling(20, min_periods=1).mean().replace(0, 1e-6).values

large_candle = (high - low) > (1.8 * atr14)
vol_surge = vol > vol_sma20
_ema50_prev3 = np.concatenate([np.full(3, np.nan), ema50[:-3]])  # shift, no wrap-around
ema50_slope_up = ema50 > _ema50_prev3
ema50_slope_down = ema50 < _ema50_prev3
price_stretch = (close - ema50) / np.maximum(ema50, 1.0)

bull_expansion = (close > open_p) & large_candle & (close > ema50) & ema50_slope_up & vol_surge & (price_stretch < 0.05)
bear_expansion = (close < open_p) & large_candle & (close < ema50) & ema50_slope_down & vol_surge & (price_stretch > -0.05)

raw_signals = np.zeros(n, dtype=int)
raw_signals[bull_expansion] = 1
raw_signals[bear_expansion] = -1

# Train ML Classifier
X_features = pd.DataFrame({
    "returns_1": pd.Series(close).pct_change(1).fillna(0.0),
    "returns_4": pd.Series(close).pct_change(4).fillna(0.0),
    "vol_20": pd.Series(close).pct_change(1).rolling(20, min_periods=1).std().fillna(0.0),
    "vol_ratio": vol / vol_sma20,
    "trend_dist": (close - ema50) / np.maximum(close, 1.0),
    "ema50_slope": (ema50 - np.concatenate([np.full(3, np.nan), ema50[:-3]])) / np.maximum(close, 1.0),
    "atr_rel": atr14 / np.maximum(close, 1.0),
})

split_idx = int(n * 0.65)
f_ret = (pd.Series(close).shift(-12) - pd.Series(close)) / pd.Series(close) * 100.0
y_labels = pd.Series(np.where(f_ret >= 1.5, 1, np.where(f_ret <= -1.5, 0, -1)))
valid_mask = y_labels.iloc[:split_idx].isin([0, 1])

clf = xgb.XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.03, subsample=0.8, colsample_bytree=0.8, random_state=42, eval_metric="logloss")
clf.fit(X_features.iloc[:split_idx][valid_mask], y_labels.iloc[:split_idx][valid_mask])
probs = clf.predict_proba(X_features)[:, 1]

# Save model
joblib.dump(clf, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "model_xgb.pkl"))

# Simulation testing across leverage/risk levels to find true monthly ROI ~20-25%
def simulate_leverage(base_risk_pct, max_leverage, mult_boost=1.35, months_total=None):
    capital = 323.0
    initial_cap = capital
    peak_capital = capital
    max_dd = 0.0
    closed_trades = []
    open_trades = []
    taker_fee = 0.00055
    slippage = 0.001
    prev_sig = 0

    for i in range(split_idx, n):  # out-of-sample ONLY (model trained on [:split_idx])
        c_close = close[i]
        c_high = high[i]
        c_low = low[i]
        c_atr = max(c_close * 0.005, atr14[i])
        sig = raw_signals[i]
        p = probs[i]

        # ML Sizing Multiplier
        if sig == 1:
            size_mult = mult_boost if p >= 0.53 else (0.40 if p < 0.47 else 1.0)
        elif sig == -1:
            size_mult = mult_boost if p <= 0.47 else (0.40 if p > 0.53 else 1.0)
        else:
            size_mult = 1.0

        curr_dd = (peak_capital - capital) / peak_capital * 100.0 if peak_capital > 0 else 0.0
        if curr_dd < 3.0: dd_mult = 1.0
        elif curr_dd < 5.0: dd_mult = 0.75
        elif curr_dd < 7.0: dd_mult = 0.50
        elif curr_dd < 8.0: dd_mult = 0.25
        else: dd_mult = 0.0

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
            exit_trade = False
            exit_p = c_close

            if direction == 1:
                if c_high > peak_p:
                    t['peak_p'] = c_high
                    peak_p = c_high
                trail = peak_p - (c_atr * 2.5)
                if trail > sl:
                    t['sl'] = trail
                    sl = trail
                if not partial and c_high >= entry_p + (c_atr * 2.0):
                    t['partial'] = True
                    gain = ((entry_p + c_atr * 2.0) - entry_p) / entry_p * (size_usd * 0.5)
                    capital += (gain - (size_usd * 0.5 * taker_fee))
                    t['size_usd'] *= 0.5
                    size_usd = t['size_usd']  # exit must use post-partial size
                    t['sl'] = max(sl, entry_p)
                if c_low <= sl_bar_start:
                    exit_trade = True
                    exit_p = sl_bar_start * (1.0 - slippage)
                elif c_high >= tp:
                    exit_trade = True
                    exit_p = tp * (1.0 - slippage)
            else:
                if c_low < peak_p:
                    t['peak_p'] = c_low
                    peak_p = c_low
                trail = peak_p + (c_atr * 2.5)
                if trail < sl:
                    t['sl'] = trail
                    sl = trail
                if not partial and c_low <= entry_p - (c_atr * 2.0):
                    t['partial'] = True
                    gain = (entry_p - (entry_p - c_atr * 2.0)) / entry_p * (size_usd * 0.5)
                    capital += (gain - (size_usd * 0.5 * taker_fee))
                    t['size_usd'] *= 0.5
                    size_usd = t['size_usd']  # exit must use post-partial size
                    t['sl'] = min(sl, entry_p)
                if c_high >= sl_bar_start:
                    exit_trade = True
                    exit_p = sl_bar_start * (1.0 + slippage)
                elif c_low <= tp:
                    exit_trade = True
                    exit_p = tp * (1.0 + slippage)

            if exit_trade:
                pnl_pct = (exit_p - entry_p) / entry_p if direction == 1 else (entry_p - exit_p) / entry_p
                pnl_usd = (pnl_pct * size_usd) - (size_usd * taker_fee)
                capital += pnl_usd
                closed_trades.append({'pnl_usd': pnl_usd, 'pnl_pct': pnl_pct * 100.0})
            else:
                rem.append(t)

        open_trades = rem
        is_new = (sig != 0) and (sig != prev_sig)
        prev_sig = sig

        if is_new and len(open_trades) < 2 and size_mult > 0 and dd_mult > 0:
            eff_risk = base_risk_pct * dd_mult * size_mult
            risk_usd = capital * (eff_risk / 100.0)
            sl_dist = c_atr * 1.6
            sl_pct = sl_dist / c_close
            if sl_pct > 0.001:
                targ_size = risk_usd / sl_pct
                max_size = (capital * max_leverage) / 2
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
    months_total = months_total if months_total is not None else months_elapsed  # explicit, not implicit global
    sim_months = max(0.1, months_total * (n - split_idx) / n)  # OOS window only
    monthly_roi = ((1.0 + (net_roi / 100.0)) ** (1.0 / sim_months) - 1.0) * 100.0
    tot_profit = sum(t['pnl_usd'] for t in wins)
    tot_loss = abs(sum(t['pnl_usd'] for t in closed_trades if t['pnl_usd'] <= 0)) if len(wins) < tot_trades else 1e-6
    pf = tot_profit / tot_loss if tot_loss > 0 else (10.0 if tot_profit > 0 else 0.0)

    return {
        'base_risk': base_risk_pct,
        'max_leverage': max_leverage,
        'monthly_roi': monthly_roi,
        'total_roi': net_roi,
        'max_dd': max_dd,
        'win_rate': win_rate,
        'trades': tot_trades,
        'pf': pf,
        'calmar': monthly_roi / max_dd if max_dd > 0 else 0.0,
        'final_cap': capital
    }

print("="*85)
print("PARAMETER SWEEP FOR 20-25% MONTHLY ROI WITH MACHINE LEARNING:")
print("="*85)
for risk in [2.5, 3.5, 5.0, 7.5, 10.0]:
    for lev in [2.5, 3.5, 5.0, 7.0]:
        res = simulate_leverage(risk, lev, mult_boost=1.35)
        print(f"Risk: {res['base_risk']:4.1f}% | Lev: {res['max_leverage']:3.1f}x | Monthly ROI: {res['monthly_roi']:5.2f}% | Total ROI: {res['total_roi']:6.2f}% | Max DD: {res['max_dd']:5.2f}% | Calmar: {res['calmar']:4.2f} | PF: {res['pf']:4.2f}")
