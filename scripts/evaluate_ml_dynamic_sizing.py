

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import pandas as pd
import numpy as np
import joblib
from scripts.evaluate_dd_scaling import DynamicDDBacktestSimulator
from core.ml.features import FeatureEngineer
import xgboost as xgb

df = pd.read_csv("data/btc_real_dataset.csv")
df["timestamp"] = df["date"] if "date" in df.columns else df.index

close = df["close"]
high = df["high"]
low = df["low"]
open_p = df["open"]
vol = df["volume"]

tr = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
atr = tr.rolling(14).mean()
large_candle = (high - low) > 1.8 * atr
ema50 = close.ewm(span=50).mean()
ema50_slope_up = ema50 > ema50.shift(3)
ema50_slope_down = ema50 < ema50.shift(3)
vol_surge = vol > vol.rolling(20).mean()
price_stretch = (close - ema50) / ema50

bull_expansion = (close > open_p) & large_candle & (close > ema50) & ema50_slope_up & vol_surge & (price_stretch < 0.05)
bear_expansion = (close < open_p) & large_candle & (close < ema50) & ema50_slope_down & vol_surge & (price_stretch > -0.05)

fe = FeatureEngineer()
df_features = fe.create_features(
    df,
    signals_dict={"funding_rate": 0.0001, "oi_change_pct": 0.5, "long_short_ratio": 1.1, "taker_ratio": 1.05, "conviction": 75.0},
    regime_info={"hurst": 0.55, "atr_percentile": 60.0, "regime": "TREND"}
)

y_labels = fe.create_labels(df, forward_bars=12, threshold_pct=1.5)
split_idx = 650
valid_train = y_labels.iloc[:split_idx].isin([0, 1])

model = xgb.XGBClassifier(
    n_estimators=100, max_depth=3, learning_rate=0.03, subsample=0.8, colsample_bytree=0.8, random_state=42, eval_metric="logloss"
)
model.fit(df_features.iloc[:split_idx][valid_train], y_labels.iloc[:split_idx][valid_train])
probs = model.predict_proba(df_features)[:, 1]

class MLDynamicDDBacktestSimulator(DynamicDDBacktestSimulator):
    def run_backtest_ml_hybrid(self, df, signals, base_risk_pct=3.5):
        # We allow trades, but scale risk dynamically with ML confidence
        capital = self.initial_capital
        peak_capital = capital
        max_drawdown = 0.0
        drawdown_history = []
        equity_curve = [capital]
        open_trades = []
        closed_trades = []

        closes = df['close'].values
        highs = df['high'].values
        lows = df['low'].values
        times = df['timestamp'].values
        sig_arr = signals['signal'].values
        atr_arr = signals['atr'].values
        ml_mult_arr = signals['ml_multiplier'].values

        n = len(df)
        # Derive the bar duration from real timestamps (the old '4h'-in-str(times)
        # sniff never matched datetime values and treated 4h bars as 1h, overstating
        # monthly ROI ~4x).
        try:
            bar_hours = float((times[1] - times[0]) / np.timedelta64(1, "h"))
        except Exception:
            bar_hours = 1.0
        if not bar_hours or bar_hours != bar_hours:
            bar_hours = 1.0
        hours_elapsed = n * bar_hours
        months_elapsed = max(1.0, hours_elapsed / (24.0 * 30.4))
        prev_sig = 0

        for i in range(1, n):
            current_close = closes[i]
            current_high = highs[i]
            current_low = lows[i]
            current_time = times[i]
            current_atr = max(current_close * 0.005, atr_arr[i])
            sig = sig_arr[i]
            ml_mult = ml_mult_arr[i]

            current_dd = (peak_capital - capital) / peak_capital * 100.0 if peak_capital > 0 else 0.0
            if current_dd < 3.0:
                dd_multiplier = 1.0
            elif current_dd < 5.0:
                dd_multiplier = 0.75
            elif current_dd < 7.0:
                dd_multiplier = 0.50
            else:
                dd_multiplier = 0.25

            remaining_trades = []
            for t in open_trades:
                direction = t['direction']
                entry_p = t['entry_price']
                sl = t['sl']
                tp = t['tp']
                size_usd = t['size_usd']
                sl_bar_start = t['sl']  # bar-START stop: ratchets are future-only
                peak_p = t['peak_p']
                partial_taken = t.get('partial_taken', False)

                exit_trade = False
                exit_price = current_close
                exit_reason = ''

                if direction == 1:
                    if current_high > peak_p:
                        t['peak_p'] = current_high
                        peak_p = current_high
                    trail_candidate = peak_p - (current_atr * 2.5)
                    if trail_candidate > sl:
                        t['sl'] = trail_candidate
                        sl = trail_candidate
                    if not partial_taken and current_high >= entry_p + (current_atr * 2.0):
                        t['partial_taken'] = True
                        partial_gain = ((entry_p + current_atr * 2.0) - entry_p) / entry_p * (size_usd * 0.5)
                        partial_fee = (size_usd * 0.5) * self.taker_fee
                        capital += (partial_gain - partial_fee)
                        t['size_usd'] *= 0.5
                        size_usd = t['size_usd']  # exit must use post-partial size
                        t['sl'] = max(sl, entry_p)
                    if current_low <= sl_bar_start:
                        exit_trade = True
                        exit_price = sl_bar_start * (1.0 - self.slippage)
                        exit_reason = 'SL'
                    elif current_high >= tp:
                        exit_trade = True
                        exit_price = tp * (1.0 - self.slippage)
                        exit_reason = 'TP'
                elif direction == -1:
                    if current_low < peak_p:
                        t['peak_p'] = current_low
                        peak_p = current_low
                    trail_candidate = peak_p + (current_atr * 2.5)
                    if trail_candidate < sl:
                        t['sl'] = trail_candidate
                        sl = trail_candidate
                    if not partial_taken and current_low <= entry_p - (current_atr * 2.0):
                        t['partial_taken'] = True
                        partial_gain = (entry_p - (entry_p - current_atr * 2.0)) / entry_p * (size_usd * 0.5)
                        partial_fee = (size_usd * 0.5) * self.taker_fee
                        capital += (partial_gain - partial_fee)
                        t['size_usd'] *= 0.5
                        size_usd = t['size_usd']  # exit must use post-partial size
                        t['sl'] = min(sl, entry_p)
                    if current_high >= sl_bar_start:
                        exit_trade = True
                        exit_price = sl_bar_start * (1.0 + self.slippage)
                        exit_reason = 'SL'
                    elif current_low <= tp:
                        exit_trade = True
                        exit_price = tp * (1.0 + self.slippage)
                        exit_reason = 'TP'

                if exit_trade:
                    pnl_pct = (exit_price - entry_p) / entry_p if direction == 1 else (entry_p - exit_price) / entry_p
                    trade_pnl_usd = (pnl_pct * size_usd) - (size_usd * self.taker_fee)
                    capital += trade_pnl_usd
                    closed_trades.append({'pnl_usd': trade_pnl_usd, 'pnl_pct': pnl_pct * 100.0})
                else:
                    remaining_trades.append(t)

            open_trades = remaining_trades
            is_new_signal = (sig != 0) and (sig != prev_sig)
            prev_sig = sig

            if is_new_signal and len(open_trades) < 2 and ml_mult > 0:
                effective_risk_pct = base_risk_pct * dd_multiplier * ml_mult
                risk_usd = capital * (effective_risk_pct / 100.0)
                sl_dist = current_atr * 1.6
                sl_pct = sl_dist / current_close
                if sl_pct > 0.001:
                    target_size = risk_usd / sl_pct
                    max_allowed_size = (capital * 2.5) / 2
                    size_usd = min(target_size, max_allowed_size)
                    if sig == 1:
                        actual_entry = current_close * (1.0 + self.slippage)
                        sl_price = actual_entry - sl_dist
                        tp_price = actual_entry + (current_atr * 2.4)
                    else:
                        actual_entry = current_close * (1.0 - self.slippage)
                        sl_price = actual_entry + sl_dist
                        tp_price = actual_entry - (current_atr * 2.4)

                    capital -= size_usd * self.taker_fee
                    open_trades.append({
                        'direction': sig, 'entry_price': actual_entry, 'sl': sl_price, 'tp': tp_price,
                        'peak_p': actual_entry, 'size_usd': size_usd, 'partial_taken': False
                    })

            peak_capital = max(peak_capital, capital)
            current_dd = (peak_capital - capital) / peak_capital * 100.0
            max_drawdown = max(max_drawdown, current_dd)

        total_trades = len(closed_trades)
        wins = [t for t in closed_trades if t['pnl_usd'] > 0]
        losses = [t for t in closed_trades if t['pnl_usd'] <= 0]
        win_rate = (len(wins) / total_trades * 100.0) if total_trades > 0 else 0.0
        net_roi_total_pct = (capital - self.initial_capital) / self.initial_capital * 100.0
        monthly_roi_pct = ((1.0 + (net_roi_total_pct / 100.0)) ** (1.0 / months_elapsed) - 1.0) * 100.0
        total_profit = sum(t['pnl_usd'] for t in wins)
        total_loss = abs(sum(t['pnl_usd'] for t in losses)) if losses else 1e-6
        pf = total_profit / total_loss if total_loss > 0 else 0.0

        return {
            'monthly_roi_pct': monthly_roi_pct,
            'max_drawdown_pct': max_drawdown,
            'win_rate': win_rate,
            'total_trades': total_trades,
            'profit_factor': pf
        }

# Compare sizing strategies:
# Mode A: Base Sizing (ml_mult = 1.0)
signals = pd.DataFrame(index=df.index)
signals['signal'] = 0
signals['atr'] = atr
signals.loc[bull_expansion, 'signal'] = 1
signals.loc[bear_expansion, 'signal'] = -1
signals['ml_multiplier'] = 1.0

sim = MLDynamicDDBacktestSimulator(slippage_pct=0.1, taker_fee_pct=0.055, initial_capital=323.0)
res_static = sim.run_backtest_ml_hybrid(df, signals, base_risk_pct=3.5)

# Mode B: ML Dynamic Sizing (High ML confidence = 1.25x size, Low ML confidence = 0.5x size)
# For longs: prob >= 0.53 -> 1.25x, prob < 0.48 -> 0.4x, else 1.0x
ml_mult = np.ones(len(df))
for i in range(len(df)):
    p = probs[i]
    sig = signals['signal'].iloc[i]
    if sig == 1:
        if p >= 0.53:
            ml_mult[i] = 1.30
        elif p < 0.47:
            ml_mult[i] = 0.40
    elif sig == -1:
        if p <= 0.47:
            ml_mult[i] = 1.30
        elif p > 0.53:
            ml_mult[i] = 0.40

signals_dyn = signals.copy()
signals_dyn['ml_multiplier'] = ml_mult
res_dyn = sim.run_backtest_ml_hybrid(df, signals_dyn, base_risk_pct=3.5)

print("\n" + "="*65)
print("RESULTS: MACHINE LEARNING TESTING ON REAL BTC DATA")
print("="*65)
print(f"1. PURE RULE-BASED (No ML):")
print(f"   Monthly ROI:   {res_static['monthly_roi_pct']:.2f}%")
print(f"   Max Drawdown:  {res_static['max_drawdown_pct']:.2f}%")
print(f"   Win Rate:      {res_static['win_rate']:.2f}% ({res_static['total_trades']} trades)")
print(f"   Profit Factor: {res_static['profit_factor']:.2f}")
print(f"   Calmar Ratio:  {res_static['monthly_roi_pct']/res_static['max_drawdown_pct']:.2f}")

print("\n2. ML DYNAMIC SIZING (Boost high-conviction ML trades, damp low-conviction):")
print(f"   Monthly ROI:   {res_dyn['monthly_roi_pct']:.2f}%")
print(f"   Max Drawdown:  {res_dyn['max_drawdown_pct']:.2f}%")
print(f"   Win Rate:      {res_dyn['win_rate']:.2f}% ({res_dyn['total_trades']} trades)")
print(f"   Profit Factor: {res_dyn['profit_factor']:.2f}")
print(f"   Calmar Ratio:  {res_dyn['monthly_roi_pct']/res_dyn['max_drawdown_pct']:.2f}")
print("="*65)
