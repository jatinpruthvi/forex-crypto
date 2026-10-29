

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import pandas as pd
import numpy as np
from core.analysis.fast_backtester import BacktestSimulator

# Evaluate full available multi-year history across BTC, ETH, SOL, BNB, LINK
assets = [
    ("BTC", "data/timeframes/BTCUSD_H4.csv", "data/timeframes/BTCUSD_M15.csv"),
    ("ETH", "data/timeframes/ETHUSDT_H4.csv", "data/timeframes/ETHUSDT_M15.csv"),
    ("SOL", "data/timeframes/SOLUSDT_H4.csv", "data/timeframes/SOLUSDT_M15.csv"),
    ("BNB", "data/timeframes/BNBUSDT_H4.csv", "data/timeframes/BNBUSDT_M15.csv"),
    ("LINK", "data/timeframes/LINKUSDT_H4.csv", "data/timeframes/LINKUSDT_M15.csv"),
]

print("=== FULL MULTI-YEAR REAL DATASET EVALUATION ACROSS TOP CRYPTOS ===")
print("Asset | History Length | Total Bars | Final Capital | Total Return | Comp Monthly | Max Drawdown | Win Rate | Profit Factor | Trades")
print("----------------------------------------------------------------------------------------------------------------------------------")

sim = BacktestSimulator(slippage_pct=0.03, taker_fee_pct=0.02, initial_capital=1000.0, order_execution_mode="maker")

for sym, h4_file, m15_file in assets:
    df_h4 = pd.read_csv(h4_file)
    df_m15 = pd.read_csv(m15_file)
    df_h4["timestamp"] = pd.to_datetime(df_h4["timestamp"])
    df_m15["timestamp"] = pd.to_datetime(df_m15["timestamp"])

    df_h4["ema50_h4"] = df_h4["close"].ewm(span=50).mean()
    df_h4["macro_trend"] = np.where(df_h4["close"] > df_h4["ema50_h4"], 1, -1)

    df_m15 = pd.merge_asof(df_m15.sort_values("timestamp"), df_h4[["timestamp", "macro_trend"]].sort_values("timestamp"), on="timestamp", direction="backward")
    df_m15["macro_trend"] = df_m15["macro_trend"].fillna(1)

    close = df_m15["close"]
    high = df_m15["high"]
    low = df_m15["low"]
    open_p = df_m15["open"]
    vol = df_m15["volume"]
    macro = df_m15["macro_trend"]

    tr = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
    atr = tr.rolling(14).mean().bfill()
    ema20 = close.ewm(span=20).mean()
    ema50 = close.ewm(span=50).mean()
    typical_p = (high + low + close) / 3.0
    rolling_vwap = (typical_p * vol).rolling(30).sum() / vol.rolling(30).sum().replace(0, 1)

    h_12 = high.rolling(12).max().shift(1)
    l_12 = low.rolling(12).min().shift(1)

    bull = (macro == 1) & (close > open_p) & (close > rolling_vwap) & (ema20 > ema50) & (high >= h_12)
    bear = (macro == -1) & (close < open_p) & (close < rolling_vwap) & (ema20 < ema50) & (low <= l_12)

    sig = pd.DataFrame(index=df_m15.index)
    sig["signal"] = 0
    sig["atr"] = atr
    sig["conviction"] = 85.0
    sig["regime"] = "TREND"
    sig.loc[bull, "signal"] = 1
    sig.loc[bear, "signal"] = -1

    # ATR above is .bfill()'d over its 14-bar warmup while h_lb/l_lb first signal
    # at bar 12 - zero signals through bar 13 so no entry uses future-filled ATR.
    sig.loc[:13, "signal"] = 0

    res = sim.run_backtest(df_m15, sig, risk_per_trade_pct=3.0, atr_sl_mult=1.3, atr_tp_mult=2.0)

    fc = res["final_capital"]
    tot = res["net_roi_total_pct"]
    cm = res["monthly_roi_pct"]
    mo = res["months_elapsed"]
    dd = res["max_drawdown_pct"]
    wr = res["win_rate"]
    pf = res["profit_factor"]
    tc = res["total_trades"]
    print(f"{sym:<5} |  {mo/12.0:4.1f} Years   | {len(df_m15):10,d} | ${fc:13.2f} | {tot:+9.2f}% | {cm:+11.2f}%/mo | {dd:11.2f}% | {wr:6.2f}% | {pf:13.2f} | {tc:6d}")
