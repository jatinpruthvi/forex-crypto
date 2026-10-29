import pandas as pd
import numpy as np
from core.analysis.fast_backtester import BacktestSimulator
from core.analysis.monte_carlo import MonteCarloSimulator

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
res = sim.run_backtest(df, signals, risk_per_trade_pct=4.2, atr_sl_mult=1.6, atr_tp_mult=2.4, trailing_atr_mult=2.5, leverage=2.5, max_open_trades=2, partial_take_profit=True)

trade_returns_pct = [t['pnl_pct'] for t in res['closed_trades']]
print(f"Total evaluated trades: {len(trade_returns_pct)}")

# Run 10,000 Monte Carlo simulations
mc = MonteCarloSimulator(n_simulations=10000)
mc_res = mc.simulate(trade_returns_pct, initial_equity=323.0)

print("=== 10,000 MONTE CARLO STRESS TEST RESULTS ===")
print(f"95th Percentile Maximum Drawdown: {mc_res['max_dd_95_pct']}%")
print(f"99th Percentile Maximum Drawdown: {mc_res['max_dd_99_pct']}%")
print(f"Probability of Ruin (equity drawdown beyond {mc_res.get('ruin_threshold_pct', 50.0)}%): {mc_res['probability_of_ruin_pct']}%")
print(f"Verdict: {mc_res['verdict']}")
