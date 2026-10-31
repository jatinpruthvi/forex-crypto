

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import pandas as pd
import numpy as np
import joblib
from scripts.evaluate_dd_scaling import DynamicDDBacktestSimulator
import xgboost as xgb

# Evaluate 2-asset Portfolio (BTC & ETH 4h Real Candles)
df_btc = pd.read_csv("data/btc_real_dataset.csv")
df_eth = pd.read_csv("data/eth_real_dataset.csv")

df_btc["timestamp"] = df_btc["date"] if "date" in df_btc.columns else df_btc.index
df_eth["timestamp"] = df_eth["date"] if "date" in df_eth.columns else df_eth.index

n = min(len(df_btc), len(df_eth))
months_elapsed = (n * 4.0) / (24.0 * 30.4)

def process_asset(df):
    close = df["close"].values[:n]
    high = df["high"].values[:n]
    low = df["low"].values[:n]
    open_p = df["open"].values[:n]
    vol = df["volume"].values[:n]

    tr = np.maximum(high - low, np.maximum(np.abs(high - np.roll(close, 1)), np.abs(low - np.roll(close, 1))))
    atr14 = pd.Series(tr).rolling(14, min_periods=1).mean().values
    ema50 = pd.Series(close).ewm(span=50).mean().values
    vol_sma20 = pd.Series(vol).rolling(20, min_periods=1).mean().replace(0, 1e-6).values

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

    return {
        "close": close, "high": high, "low": low, "atr": atr14, "signals": raw_signals, "probs": probs,
        "split_idx": split_idx,
    }

btc = process_asset(df_btc)
eth = process_asset(df_eth)

# Multi-asset Portfolio Backtest
def run_portfolio_sim(base_risk_pct=3.5, max_leverage=3.5):
    capital = 323.0
    initial_cap = capital
    peak_capital = capital
    max_dd = 0.0
    closed_trades = []
    open_trades = []
    taker_fee = 0.00055
    slippage = 0.001
    prev_sig_btc = 0
    prev_sig_eth = 0

    oos_start = int(btc.get("split_idx", 1))  # model trained on [:split_idx] -> trade OOS only
    for i in range(oos_start, n):
        curr_dd = (peak_capital - capital) / peak_capital * 100.0 if peak_capital > 0 else 0.0
        if curr_dd < 3.0: dd_mult = 1.0
        elif curr_dd < 5.0: dd_mult = 0.75
        elif curr_dd < 7.0: dd_mult = 0.50
        elif curr_dd < 8.0: dd_mult = 0.25
        else: dd_mult = 0.0

        # Check exits across open positions
        rem = []
        for t in open_trades:
            sym = t['sym']
            ast = btc if sym == 'BTC' else eth
            c_close = ast['close'][i]
            c_high = ast['high'][i]
            c_low = ast['low'][i]
            c_atr = max(c_close * 0.005, ast['atr'][i])
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
                    ex = True
                    ex_p = sl_bar_start * (1.0 - slippage)
                elif c_high >= tp:
                    ex = True
                    ex_p = tp * (1.0 - slippage)
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

        # Evaluate Entries for BTC and ETH
        for sym, ast, prev_s in [('BTC', btc, prev_sig_btc), ('ETH', eth, prev_sig_eth)]:
            sig = ast['signals'][i]
            is_new = (sig != 0) and (sig != prev_s)
            p = ast['probs'][i]

            # ML sizing multiplier
            if sig == 1:
                size_mult = 1.35 if p >= 0.53 else (0.40 if p < 0.47 else 1.0)
            elif sig == -1:
                size_mult = 1.35 if p <= 0.47 else (0.40 if p > 0.53 else 1.0)
            else:
                size_mult = 1.0

            if is_new and len(open_trades) < 3 and size_mult > 0 and dd_mult > 0:
                c_close = ast['close'][i]
                c_atr = max(c_close * 0.005, ast['atr'][i])
                eff_risk = base_risk_pct * dd_mult * size_mult
                risk_usd = capital * (eff_risk / 100.0)
                sl_dist = c_atr * 1.6
                sl_pct = sl_dist / c_close
                if sl_pct > 0.001:
                    targ_size = risk_usd / sl_pct
                    max_size = (capital * max_leverage) / 3
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
                        'sym': sym, 'dir': sig, 'entry_p': act_entry, 'sl': sl_p, 'tp': tp_p,
                        'peak_p': act_entry, 'size_usd': sz, 'partial': False
                    })

        prev_sig_btc = btc['signals'][i]
        prev_sig_eth = eth['signals'][i]

        peak_capital = max(peak_capital, capital)
        curr_dd = (peak_capital - capital) / peak_capital * 100.0
        max_dd = max(max_dd, curr_dd)

    tot_trades = len(closed_trades)
    wins = [t for t in closed_trades if t['pnl_usd'] > 0]
    win_rate = (len(wins) / tot_trades * 100.0) if tot_trades > 0 else 0.0
    net_roi = (capital - initial_cap) / initial_cap * 100.0
    sim_months = max(0.1, months_elapsed * (n - oos_start) / n)  # OOS window only
    monthly_roi = ((1.0 + (net_roi / 100.0)) ** (1.0 / sim_months) - 1.0) * 100.0
    tot_profit = sum(t['pnl_usd'] for t in wins)
    tot_loss = abs(sum(t['pnl_usd'] for t in closed_trades if t['pnl_usd'] <= 0)) if len(wins) < tot_trades else 1e-6
    pf = tot_profit / tot_loss if tot_loss > 0 else 0.0

    return {
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
print("MULTI-ASSET (BTC + ETH) ML PORTFOLIO TEST:")
print("="*85)
for risk, lev in [(3.5, 3.5), (4.5, 4.0), (5.0, 5.0)]:
    res = run_portfolio_sim(base_risk_pct=risk, max_leverage=lev)
    print(f"Risk: {risk}% | Lev: {lev}x | Monthly ROI: {res['monthly_roi']:5.2f}% | Total ROI: {res['total_roi']:6.2f}% | Max DD: {res['max_dd']:5.2f}% | Win Rate: {res['win_rate']:5.2f}% | Trades: {res['trades']:2d} | Calmar: {res['calmar']:4.2f}")
print("="*85)
