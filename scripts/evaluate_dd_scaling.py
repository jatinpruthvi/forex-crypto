

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import pandas as pd
import numpy as np

# Implement Backtester with Dynamic Drawdown Protocol
from core.analysis.fast_backtester import BacktestSimulator

df = pd.read_csv('data/btc_real_dataset.csv'); df['timestamp'] = df['date'] if 'date' in df.columns else df.index
close = df['close']
high = df['high']
low = df['low']

tr = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
atr = tr.rolling(14).mean()

large_candle = (high - low) > 1.8 * atr
ema50 = close.ewm(span=50).mean()

bull_expansion = (close > df['open']) & large_candle & (close > ema50) & (ema50 > ema50.shift(3)) & (df['volume'] > df['volume'].rolling(20).mean())
bear_expansion = (close < df['open']) & large_candle & (close < ema50) & (ema50 < ema50.shift(3)) & (df['volume'] > df['volume'].rolling(20).mean())

price_stretch = (close - ema50) / ema50
long_fusion_ok = price_stretch < 0.05
short_fusion_ok = price_stretch > -0.05

signals = pd.DataFrame(index=df.index)
signals['signal'] = 0
signals['atr'] = atr
signals['conviction'] = 85.0
signals.loc[bull_expansion & long_fusion_ok, 'signal'] = 1
signals.loc[bear_expansion & short_fusion_ok, 'signal'] = -1

# Modified Simulator with Hard Drawdown Scaling
class DynamicDDBacktestSimulator(BacktestSimulator):
    def run_backtest_with_dd_guard(
        self,
        df: pd.DataFrame,
        signals: pd.DataFrame,
        base_risk_pct: float = 3.5,
        atr_sl_mult: float = 1.6,
        atr_tp_mult: float = 2.4,
        trailing_atr_mult: float = 2.5,
        leverage: float = 2.5,
        max_open_trades: int = 2,
    ):
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
        conv_arr = signals['conviction'].values

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
            conv = conv_arr[i]

            # Current drawdown percentage
            current_dd = (peak_capital - capital) / peak_capital * 100.0 if peak_capital > 0 else 0.0

            # Dynamic Drawdown Tiering:
            # Green (0-3%): 100% size
            # Yellow (3-5%): 75% size
            # Orange (5-7%): 50% size
            # Red (>7%): 25% size
            if current_dd < 3.0:
                dd_multiplier = 1.0
            elif current_dd < 5.0:
                dd_multiplier = 0.75
            elif current_dd < 7.0:
                dd_multiplier = 0.50
            else:
                dd_multiplier = 0.25

            # 1. Manage Active Positions
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

                    # Trailing stop ratchet
                    trail_candidate = peak_p - (current_atr * trailing_atr_mult)
                    if trail_candidate > sl:
                        t['sl'] = trail_candidate
                        sl = trail_candidate

                    # Partial TP at 2.0x ATR
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

                    trail_candidate = peak_p + (current_atr * trailing_atr_mult)
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
                    closed_trades.append({
                        'entry_time': t['entry_time'],
                        'exit_time': current_time,
                        'direction': direction,
                        'entry_price': entry_p,
                        'exit_price': exit_price,
                        'pnl_usd': trade_pnl_usd,
                        'pnl_pct': pnl_pct * 100.0,
                        'exit_reason': exit_reason,
                    })
                else:
                    remaining_trades.append(t)

            open_trades = remaining_trades

            # 2. Enter New Position
            is_new_signal = (sig != 0) and (sig != prev_sig)
            prev_sig = sig

            if is_new_signal and len(open_trades) < max_open_trades and conv >= 60.0:
                effective_risk_pct = base_risk_pct * dd_multiplier
                risk_usd = capital * (effective_risk_pct / 100.0)
                sl_dist = current_atr * atr_sl_mult
                sl_pct = sl_dist / current_close

                if sl_pct > 0.001:
                    target_size = risk_usd / sl_pct
                    max_allowed_size = (capital * leverage) / max_open_trades
                    size_usd = min(target_size, max_allowed_size)

                    if sig == 1:
                        actual_entry = current_close * (1.0 + self.slippage)
                        sl_price = actual_entry - sl_dist
                        tp_price = actual_entry + (current_atr * atr_tp_mult)
                    else:
                        actual_entry = current_close * (1.0 - self.slippage)
                        sl_price = actual_entry + sl_dist
                        tp_price = actual_entry - (current_atr * atr_tp_mult)

                    entry_fee = size_usd * self.taker_fee
                    capital -= entry_fee

                    open_trades.append({
                        'entry_time': current_time,
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
            drawdown_history.append(current_dd)
            equity_curve.append(capital)

        total_trades = len(closed_trades)
        wins = [t for t in closed_trades if t['pnl_usd'] > 0]
        losses = [t for t in closed_trades if t['pnl_usd'] <= 0]
        win_rate = (len(wins) / total_trades * 100.0) if total_trades > 0 else 0.0

        net_roi_total_pct = (capital - self.initial_capital) / self.initial_capital * 100.0
        monthly_roi_pct = ((1.0 + (net_roi_total_pct / 100.0)) ** (1.0 / months_elapsed) - 1.0) * 100.0

        total_profit_usd = sum(t['pnl_usd'] for t in wins)
        total_loss_usd = abs(sum(t['pnl_usd'] for t in losses)) if losses else 1e-6
        profit_factor = total_profit_usd / total_loss_usd if total_loss_usd > 0 else 0.0

        return {
            'initial_capital': self.initial_capital,
            'final_capital': round(capital, 2),
            'net_roi_total_pct': round(net_roi_total_pct, 2),
            'monthly_roi_pct': round(monthly_roi_pct, 2),
            'max_drawdown_pct': round(max_drawdown, 2),
            'total_trades': total_trades,
            'win_rate': round(win_rate, 2),
            'profit_factor': round(profit_factor, 2),
            'months_elapsed': round(months_elapsed, 1),
            'closed_trades': closed_trades,
        }

dyn_sim = DynamicDDBacktestSimulator(slippage_pct=0.1, taker_fee_pct=0.055, initial_capital=323.0)

for risk in [3.5, 4.0, 4.5]:
    res = dyn_sim.run_backtest_with_dd_guard(df, signals, base_risk_pct=risk, atr_sl_mult=1.6, atr_tp_mult=2.4, trailing_atr_mult=2.5)
    calmar = res['monthly_roi_pct'] / res['max_drawdown_pct']
    print(f"DYNAMIC DD GUARD (Base Risk: {risk}%): Monthly ROI: {res['monthly_roi_pct']:.2f}% | Max DD: {res['max_drawdown_pct']:.2f}% | Win Rate: {res['win_rate']:.2f}% | PF: {res['profit_factor']:.2f} | Calmar: {calmar:.2f}")
