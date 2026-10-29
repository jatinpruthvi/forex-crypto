

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

print(f"{'Risk%':<6} {'SL':<5} {'TP':<5} {'Trail':<6} {'Monthly ROI':<12} {'Max DD':<10} {'Calmar (ROI/DD)':<15} {'Win Rate':<10} {'Trades'}")
print("-" * 80)

candidates = []

for risk in np.arange(2.0, 6.0, 0.5):
    for sl in [1.2, 1.4, 1.5, 1.6]:
        for tp in [2.0, 2.4, 2.6, 3.0]:
            for trail in [2.2, 2.5, 2.8]:
                res = sim.run_backtest(df, signals, risk_per_trade_pct=risk, atr_sl_mult=sl, atr_tp_mult=tp, trailing_atr_mult=trail, leverage=2.0, max_open_trades=2, partial_take_profit=True)
                roi = res['monthly_roi_pct']
                dd = res['max_drawdown_pct']
                if roi >= 15.0 and dd <= 15.0:
                    calmar = roi / dd
                    candidates.append((calmar, risk, sl, tp, trail, roi, dd, res['win_rate'], res['total_trades']))

candidates.sort(key=lambda x: x[0], reverse=True)

for c in candidates[:15]:
    calmar, risk, sl, tp, trail, roi, dd, wr, trs = c
    print(f"{risk:<6.1f} {sl:<5.1f} {tp:<5.1f} {trail:<6.1f} {roi:<12.2f}% {dd:<10.2f}% {calmar:<15.2f} {wr:<10.1f}% {trs}")
