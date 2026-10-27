import pytest
import pandas as pd
import numpy as np
from core.analysis.fast_backtester import BacktestSimulator


def test_backtester_metrics(sample_ohlcv_df):
    sim = BacktestSimulator(slippage_pct=0.1, taker_fee_pct=0.055, initial_capital=323.0)
    signals = pd.DataFrame(index=sample_ohlcv_df.index)
    signals['signal'] = 0
    signals['atr'] = sample_ohlcv_df['close'] * 0.015
    signals['conviction'] = 80.0

    # Trigger alternating signals every 20 bars
    for i in range(20, len(sample_ohlcv_df), 40):
        signals.loc[i, 'signal'] = 1
        signals.loc[min(i + 20, len(sample_ohlcv_df) - 1), 'signal'] = -1

    res = sim.run_backtest(sample_ohlcv_df, signals, risk_per_trade_pct=2.0, atr_sl_mult=1.5, atr_tp_mult=2.5)

    assert 'initial_capital' in res
    assert 'final_capital' in res
    assert 'monthly_roi_pct' in res
    assert 'max_drawdown_pct' in res
    assert res['total_trades'] > 0
