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

price_stretch = (close - ema50) / ema50
long_fusion_ok = price_stretch < 0.05
short_fusion_ok = price_stretch > -0.05

signals = pd.DataFrame(index=df.index)
signals['signal'] = 0
signals['atr'] = atr
signals['conviction'] = 85.0

signals.loc[bull_expansion & long_fusion_ok, 'signal'] = 1
signals.loc[bear_expansion & short_fusion_ok, 'signal'] = -1

sim = BacktestSimulator(slippage_pct=0.1, taker_fee_pct=0.055, initial_capital=323.0)

for risk in [4.0, 4.5, 5.0]:
    for trail in [2.5, 2.8]:
        res = sim.run_backtest(
            df,
            signals,
            risk_per_trade_pct=risk,
            atr_sl_mult=1.6,
            atr_tp_mult=2.4,
            trailing_atr_mult=trail,
            leverage=2.5,
            max_open_trades=2,
            partial_take_profit=True
        )
        print(f"Risk: {risk}% | Trail: {trail} | Monthly ROI: {res['monthly_roi_pct']:.2f}% | Max DD: {res['max_drawdown_pct']:.2f}% | Win Rate: {res['win_rate']:.2f}% | Final Cap: ${res['final_capital']:.2f}")
