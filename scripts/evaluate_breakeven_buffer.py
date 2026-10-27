import pandas as pd
import numpy as np
from scripts.evaluate_dd_scaling import DynamicDDBacktestSimulator

df = pd.read_csv("data/btc_real_dataset.csv")
df["timestamp"] = df["date"] if "date" in df.columns else df.index

close = df["close"]
high = df["high"]
low = df["low"]
vol = df["volume"]

tr = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
atr = tr.rolling(14).mean()
large_candle = (high - low) > 1.8 * atr
ema50 = close.ewm(span=50).mean()
bull_expansion = (close > df["open"]) & large_candle & (close > ema50) & (ema50 > ema50.shift(3)) & (vol > vol.rolling(20).mean())
bear_expansion = (close < df["open"]) & large_candle & (close < ema50) & (ema50 < ema50.shift(3)) & (vol > vol.rolling(20).mean())
price_stretch = (close - ema50) / ema50
long_fusion_ok = price_stretch < 0.05
short_fusion_ok = price_stretch > -0.05

signals = pd.DataFrame(index=df.index)
signals["signal"] = 0
signals["atr"] = atr
signals["conviction"] = 85.0
signals.loc[bull_expansion & long_fusion_ok, "signal"] = 1
signals.loc[bear_expansion & short_fusion_ok, "signal"] = -1

# Let us evaluate different TP trigger thresholds and Breakeven Buffer levels:
# Currently partial TP is at 2.0x ATR and moves stop to entry_p.
# What if partial TP triggers at 1.8x, 2.0x, 2.2x ATR, and moves stop to entry_p +/- (0.2x ATR profit locked)?
class AdvancedExitSimulator(DynamicDDBacktestSimulator):
    def run_backtest_with_exit_tuning(
        self,
        df,
        signals,
        partial_atr_trigger=2.0,
        be_buffer_atr=0.15,
        trailing_mult=2.5
    ):
        capital = self.initial_capital
        peak_capital = capital
        max_drawdown = 0.0
        closed_trades = []
        open_trades = []

        closes = df['close'].values
        highs = df['high'].values
        lows = df['low'].values
        times = df['timestamp'].values
        sig_arr = signals['signal'].values
        atr_arr = signals['atr'].values
        conv_arr = signals['conviction'].values

        n = len(df)
        hours_elapsed = n * 4 if '4h' in str(times[1]) else n
        months_elapsed = max(1.0, hours_elapsed / (24.0 * 30.4))
        prev_sig = 0

        for i in range(1, n):
            current_close = closes[i]
            current_high = highs[i]
            current_low = lows[i]
            current_time = times[i]
            current_atr = max(current_close * 0.005, atr_arr[i])
            sig = sig_arr[i]

            current_dd = (peak_capital - capital) / peak_capital * 100.0 if peak_capital > 0 else 0.0
            if current_dd < 3.0: dd_mult = 1.0
            elif current_dd < 5.0: dd_mult = 0.75
            elif current_dd < 7.0: dd_mult = 0.50
            else: dd_mult = 0.25

            remaining_trades = []
            for t in open_trades:
                direction = t['direction']
                entry_p = t['entry_price']
                sl = t['sl']
                tp = t['tp']
                size_usd = t['size_usd']
                peak_p = t['peak_p']
                partial_taken = t.get('partial_taken', False)

                exit_trade = False
                exit_price = current_close

                if direction == 1:
                    if current_high > peak_p:
                        t['peak_p'] = current_high
                        peak_p = current_high

                    trail_candidate = peak_p - (current_atr * trailing_mult)
                    if trail_candidate > sl:
                        t['sl'] = trail_candidate
                        sl = trail_candidate

                    # Partial TP with Fee + Profit Buffer Ratchet
                    if not partial_taken and current_high >= entry_p + (current_atr * partial_atr_trigger):
                        t['partial_taken'] = True
                        partial_gain = ((entry_p + current_atr * partial_atr_trigger) - entry_p) / entry_p * (size_usd * 0.5)
                        partial_fee = (size_usd * 0.5) * self.taker_fee
                        capital += (partial_gain - partial_fee)
                        t['size_usd'] *= 0.5
                        # Move SL to entry_p + be_buffer_atr to ensure zero loss AND profit locked
                        t['sl'] = max(sl, entry_p + (current_atr * be_buffer_atr))

                    if current_low <= sl:
                        exit_trade = True
                        exit_price = sl * (1.0 - self.slippage)
                    elif current_high >= tp:
                        exit_trade = True
                        exit_price = tp * (1.0 - self.slippage)

                elif direction == -1:
                    if current_low < peak_p:
                        t['peak_p'] = current_low
                        peak_p = current_low

                    trail_candidate = peak_p + (current_atr * trailing_mult)
                    if trail_candidate < sl:
                        t['sl'] = trail_candidate
                        sl = trail_candidate

                    if not partial_taken and current_low <= entry_p - (current_atr * partial_atr_trigger):
                        t['partial_taken'] = True
                        partial_gain = (entry_p - (entry_p - current_atr * partial_atr_trigger)) / entry_p * (size_usd * 0.5)
                        partial_fee = (size_usd * 0.5) * self.taker_fee
                        capital += (partial_gain - partial_fee)
                        t['size_usd'] *= 0.5
                        t['sl'] = min(sl, entry_p - (current_atr * be_buffer_atr))

                    if current_high >= sl:
                        exit_trade = True
                        exit_price = sl * (1.0 + self.slippage)
                    elif current_low <= tp:
                        exit_trade = True
                        exit_price = tp * (1.0 + self.slippage)

                if exit_trade:
                    pnl_pct = (exit_price - entry_p) / entry_p if direction == 1 else (entry_p - exit_price) / entry_p
                    trade_pnl_usd = (pnl_pct * size_usd) - (size_usd * self.taker_fee)
                    capital += trade_pnl_usd
                    closed_trades.append({'pnl_usd': trade_pnl_usd})
                else:
                    remaining_trades.append(t)

            open_trades = remaining_trades
            is_new_signal = (sig != 0) and (sig != prev_sig)
            prev_sig = sig

            if is_new_signal and len(open_trades) < 2:
                effective_risk_pct = 3.5 * dd_mult
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
                        'direction': sig,
                        'entry_price': actual_entry,
                        'sl': sl_price,
                        'tp': tp_price,
                        'peak_p': actual_entry,
                        'size_usd': size_usd,
                        'partial_taken': False,
                    })

            peak_capital = max(peak_capital, capital)
            current_dd = (peak_capital - capital) / peak_capital * 100.0
            max_drawdown = max(max_drawdown, current_dd)

        total_trades = len(closed_trades)
        wins = [t for t in closed_trades if t['pnl_usd'] > 0]
        losses = [t for t in closed_trades if t['pnl_usd'] <= 0]
        win_rate = (len(wins) / total_trades * 100.0) if total_trades > 0 else 0.0
        net_roi = (capital - self.initial_capital) / self.initial_capital * 100.0
        monthly_roi = ((1.0 + (net_roi / 100.0)) ** (1.0 / months_elapsed) - 1.0) * 100.0
        tot_win = sum(t['pnl_usd'] for t in wins)
        tot_loss = abs(sum(t['pnl_usd'] for t in losses)) if losses else 1e-6
        pf = tot_win / tot_loss if tot_loss > 0 else 0.0

        return {
            'monthly_roi': monthly_roi,
            'max_dd': max_drawdown,
            'win_rate': win_rate,
            'pf': pf,
            'calmar': monthly_roi / max_drawdown if max_drawdown > 0 else 0.0,
            'trades': total_trades,
            'final_cap': capital
        }

sim = AdvancedExitSimulator(slippage_pct=0.1, taker_fee_pct=0.055, initial_capital=323.0)

print("="*80)
print("EXPERIMENT: TESTING PARTIAL TAKE-PROFIT & BREAKEVEN PROFIT LOCK BUFFERS")
print("="*80)
for p_trig in [1.6, 1.8, 2.0]:
    for be_buf in [0.0, 0.10, 0.15, 0.20]:
        res = sim.run_backtest_with_exit_tuning(df, signals, partial_atr_trigger=p_trig, be_buffer_atr=be_buf)
        print(f"Trigger: {p_trig:3.1f}x ATR | BE Buffer: +{be_buf:4.2f}x ATR | Monthly ROI: {res['monthly_roi']:5.2f}% | Max DD: {res['max_dd']:5.2f}% | Win Rate: {res['win_rate']:5.2f}% | PF: {res['pf']:4.2f} | Calmar: {res['calmar']:4.2f}")
