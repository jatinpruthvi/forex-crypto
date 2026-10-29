

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import pandas as pd
import numpy as np
from core.analysis.fast_backtester import BacktestSimulator
from core.risk.dd_protocol import DrawdownProtocol

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

price_stretch = (close - ema50) / ema50
long_fusion_ok = price_stretch < 0.05
short_fusion_ok = price_stretch > -0.05

signals = pd.DataFrame(index=df.index)
signals['signal'] = 0
signals['atr'] = atr
signals['conviction'] = 85.0

signals.loc[bull_expansion & long_fusion_ok, 'signal'] = 1
signals.loc[bear_expansion & short_fusion_ok, 'signal'] = -1

# Let's test with Risk = 2.5% and 3.0% (Defensive risk budgeting)
sim = BacktestSimulator(slippage_pct=0.1, taker_fee_pct=0.055, initial_capital=323.0)

res_defensive = sim.run_backtest(
    df,
    signals,
    risk_per_trade_pct=2.5,
    atr_sl_mult=1.6,
    atr_tp_mult=2.4,
    trailing_atr_mult=2.5,
    leverage=2.0,
    max_open_trades=2,
    partial_take_profit=True
)

print(f"Defensive Tier (2.5% Risk): Monthly ROI: {res_defensive['monthly_roi_pct']:.2f}% | Max DD: {res_defensive['max_drawdown_pct']:.2f}% | Win Rate: {res_defensive['win_rate']:.2f}%")

res_growth = sim.run_backtest(
    df,
    signals,
    risk_per_trade_pct=4.2,
    atr_sl_mult=1.6,
    atr_tp_mult=2.4,
    trailing_atr_mult=2.5,
    leverage=2.5,
    max_open_trades=2,
    partial_take_profit=True
)

print(f"High Growth Tier (4.2% Risk): Monthly ROI: {res_growth['monthly_roi_pct']:.2f}% | Max DD: {res_growth['max_drawdown_pct']:.2f}% | Win Rate: {res_growth['win_rate']:.2f}%")
