

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import pandas as pd
import numpy as np
from core.analysis.fast_backtester import BacktestSimulator

# Load BTC M15 and H4
df_h4 = pd.read_csv("data/timeframes/BTCUSD_H4.csv")
df_m15 = pd.read_csv("data/timeframes/BTCUSD_M15.csv")

df_h4["timestamp"] = pd.to_datetime(df_h4["timestamp"])
df_m15["timestamp"] = pd.to_datetime(df_m15["timestamp"])

df_h4["ema50_h4"] = df_h4["close"].ewm(span=50).mean()
df_h4["macro_trend"] = np.where(df_h4["close"] > df_h4["ema50_h4"], 1, -1)

df_m15 = pd.merge_asof(df_m15.sort_values("timestamp"), df_h4[["timestamp", "macro_trend"]].sort_values("timestamp"), on="timestamp", direction="backward")
df_m15["macro_trend"] = df_m15["macro_trend"].fillna(1)
df_m15["year"] = df_m15["timestamp"].dt.year

sim = BacktestSimulator(slippage_pct=0.03, taker_fee_pct=0.02, initial_capital=1000.0, order_execution_mode="maker")

records = []
for yr in sorted(df_m15["year"].unique()):
    sub = df_m15[df_m15["year"] == yr].reset_index(drop=True)
    if len(sub) < 500:
        continue
    close = sub["close"]
    high = sub["high"]
    low = sub["low"]
    open_p = sub["open"]
    vol = sub["volume"]
    macro = sub["macro_trend"]

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

    sig = pd.DataFrame(index=sub.index)
    sig["signal"] = 0
    sig["atr"] = atr
    sig["conviction"] = 85.0
    sig["regime"] = "TREND"
    sig.loc[bull, "signal"] = 1
    sig.loc[bear, "signal"] = -1

    # ATR above is .bfill()'d over its 14-bar warmup while h_lb/l_lb first signal
    # at bar 12 - zero signals through bar 13 so no entry uses future-filled ATR.
    sig.loc[:13, "signal"] = 0

    res = sim.run_backtest(sub, sig, risk_per_trade_pct=3.0, atr_sl_mult=1.3, atr_tp_mult=2.0)
    records.append({
        "year": yr,
        "months": res["months_elapsed"],
        "bars": len(sub),
        "final_capital": res["final_capital"],
        "net_return": res["net_roi_total_pct"],
        "monthly_roi": res["monthly_roi_pct"],
        "max_drawdown": res["max_drawdown_pct"],
        "trades": res["total_trades"],
        "win_rate": res["win_rate"],
        "profit_factor": res["profit_factor"]
    })

res_df = pd.DataFrame(records)
print(res_df.to_string(index=False))
