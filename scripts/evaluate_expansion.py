

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import pandas as pd
import numpy as np
from core.analysis.fast_backtester import BacktestSimulator

df = pd.read_csv('data/btc_real_dataset.csv')
close = df['close']
high = df['high']
low = df['low']

tr = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
atr = tr.rolling(14).mean()

large_candle = (high - low) > 1.8 * atr
ema50 = close.ewm(span=50).mean()

bull_expansion = (close > df['open']) & large_candle & (close > ema50) & (df['volume'] > df['volume'].rolling(20).mean())
bear_expansion = (close < df['open']) & large_candle & (close < ema50) & (df['volume'] > df['volume'].rolling(20).mean())

signals = pd.DataFrame(index=df.index)
signals['signal'] = 0
signals['atr'] = atr
signals['conviction'] = 90.0

signals.loc[bull_expansion, 'signal'] = 1
signals.loc[bear_expansion, 'signal'] = -1

sim = BacktestSimulator(slippage_pct=0.1, taker_fee_pct=0.055, initial_capital=323.0)

# Evaluate Risk=6.0%, SL=1.5, TP=2.5, Trail=2.5
res = sim.run_backtest(df, signals, risk_per_trade_pct=6.0, atr_sl_mult=1.5, atr_tp_mult=2.5, trailing_atr_mult=2.5, leverage=3.0, max_open_trades=2, partial_take_profit=True)

print('--- PERFORMANCE REPORT ---')
print('Initial Capital:   $', res['initial_capital'])
print('Final Capital:     $', res['final_capital'])
print('Total ROI:          ', res['net_roi_total_pct'], '%')
print('Monthly ROI:        ', res['monthly_roi_pct'], '%')
print('Max Drawdown:       ', res['max_drawdown_pct'], '%')
print('Total Trades:       ', res['total_trades'])
print('Win Rate:           ', res['win_rate'], '%')
print('Profit Factor:      ', res['profit_factor'])

wins = [t['pnl_usd'] for t in res['closed_trades'] if t['pnl_usd'] > 0]
losses = [t['pnl_usd'] for t in res['closed_trades'] if t['pnl_usd'] <= 0]
print(f'Wins: {len(wins)}, Avg Win: ${np.mean(wins):.2f}')
print(f'Losses: {len(losses)}, Avg Loss: ${np.mean(losses):.2f}')
print(f'Win/Loss Ratio: {abs(np.mean(wins)/np.mean(losses)):.2f}')
