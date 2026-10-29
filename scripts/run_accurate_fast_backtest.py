"""
Rigorous Empirical Backtest Benchmark using BacktestSimulator on Real Multi-Year Data:
Evaluates:
1. Pure Baseline 12-Bar Donchian Breakout
2. Baseline + TA Multi-Oscillator & Volatility Squeeze Filtering (RSI, MFI, ADX, Bollinger Bands)
3. Baseline + Smart Money Concepts (FVG & Order Block Discount Entries)
4. Full Synergy: Items 1, 2, and 3 Combined
Uses real 99,999 M15 bars + real H4 macro alignment, maker post-only fees (0.02%), slippage (0.03%),
and authentic partial take-profit laddering + dynamic breakeven buffer ratchet.
"""

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import pandas as pd
import numpy as np
import ta
from smartmoneyconcepts import smc
from core.analysis.fast_backtester import BacktestSimulator

print("Loading real BTCUSD 15-minute and 4-hour historical datasets...")
df_m15 = pd.read_parquet("/tmp/Backtesting_Data/Forex_Data/BTCUSD_15m_real.parquet")
df_h4 = pd.read_parquet("/tmp/Backtesting_Data/Forex_Data/BTCUSD_4h_real.parquet")

df_m15["timestamp"] = pd.to_datetime(df_m15["datetime"])
df_h4["timestamp"] = pd.to_datetime(df_h4["datetime"])

if "volume" not in df_m15.columns:
    df_m15["volume"] = df_m15["real_volume"] if ("real_volume" in df_m15.columns and df_m15["real_volume"].sum() > 0) else df_m15["tick_volume"]

# Align H4 macro trend into M15
df_h4["ema50_h4"] = df_h4["close"].ewm(span=50).mean()
df_h4["macro_trend"] = np.where(df_h4["close"] > df_h4["ema50_h4"], 1, -1)

df_m15 = pd.merge_asof(
    df_m15.sort_values("timestamp"),
    df_h4[["timestamp", "macro_trend"]].sort_values("timestamp"),
    on="timestamp",
    direction="backward"
)
df_m15["macro_trend"] = df_m15["macro_trend"].fillna(1)

close = df_m15["close"]
high = df_m15["high"]
low = df_m15["low"]
open_p = df_m15["open"]
vol = df_m15["volume"]
macro = df_m15["macro_trend"]

# Base Donchian & ATR
tr = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
atr = tr.rolling(14).mean().bfill()
ema20 = close.ewm(span=20).mean()
ema50 = close.ewm(span=50).mean()
typical_p = (high + low + close) / 3.0
rolling_vwap = (typical_p * vol).rolling(30).sum() / vol.rolling(30).sum().replace(0, 1)

h_12 = high.rolling(12).max().shift(1)
l_12 = low.rolling(12).min().shift(1)

# Baseline Donchian breakout signals
base_bull = (macro == 1) & (close > open_p) & (close > rolling_vwap) & (ema20 > ema50) & (high >= h_12)
base_bear = (macro == -1) & (close < open_p) & (close < rolling_vwap) & (ema20 < ema50) & (low <= l_12)

# Item 2: TA indicators (RSI, MFI, ADX, Bollinger Bands)
print("Computing TA indicators (RSI, MFI, ADX, Bollinger Bands)...")
rsi = ta.momentum.rsi(close, window=14).fillna(50.0)
mfi = ta.volume.money_flow_index(high, low, close, vol, window=14).fillna(50.0)
adx = ta.trend.adx(high, low, close, window=14).fillna(20.0)
bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
bb_wband = bb.bollinger_wband().fillna(0.1)

ta_bull = base_bull & (adx >= 18.0) & (rsi >= 50.0) & (mfi >= 45.0)
ta_bear = base_bear & (adx >= 18.0) & (rsi <= 50.0) & (mfi <= 55.0)

# Item 3: Smart Money Concepts (FVG & Order Block Discount)
print("Computing Smart Money Concepts (Swing Highs/Lows, FVG, Order Blocks)...")
ohlcv_cols = df_m15[["open", "high", "low", "close", "volume"]].copy()
shl = smc.swing_highs_lows(ohlcv_cols, swing_length=5)
fvg = smc.fvg(ohlcv_cols)
ob = smc.ob(ohlcv_cols, swing_highs_lows=shl)

fvg_val = fvg["FVG"].fillna(0.0) if "FVG" in fvg.columns else pd.Series(0.0, index=df_m15.index)
ob_val = ob["OB"].fillna(0.0) if "OB" in ob.columns else pd.Series(0.0, index=df_m15.index)

# SMC confirms bullish breakout only if supported by a Bullish FVG or Order Block.
# (An earlier `(close > open_p)` escape hatch made the gate always-true - base_bull
# already requires it - so "SMC" was silently identical to baseline. Removed.)
smc_bull = base_bull & ((fvg_val == 1) | (ob_val == 1))
smc_bear = base_bear & ((fvg_val == -1) | (ob_val == -1))

# Item 4: Full Synergy (Baseline + TA Filters + SMC Confirmation)
synergy_bull = ta_bull & ((fvg_val == 1) | (ob_val == 1))
synergy_bear = ta_bear & ((fvg_val == -1) | (ob_val == -1))

def create_sig_df(bull_mask, bear_mask):
    sig = pd.DataFrame(index=df_m15.index)
    sig["signal"] = np.where(bull_mask, 1, np.where(bear_mask, -1, 0))
    sig["atr"] = atr
    sig["conviction"] = 85.0
    sig["regime"] = "TREND"
    return sig

# Warmup honesty: ATR is .bfill()'d through bar 12 and h_12 first signals at bar 12 -
# zero signals through bar 13 so no entry uses future-filled ATR.
for _m in (base_bull, base_bear, ta_bull, ta_bear, smc_bull, smc_bear, synergy_bull, synergy_bear):
    _m.iloc[:14] = False

sig_base = create_sig_df(base_bull, base_bear)
sig_ta = create_sig_df(ta_bull, ta_bear)
sig_smc = create_sig_df(smc_bull, smc_bear)
sig_synergy = create_sig_df(synergy_bull, synergy_bear)

# Standard simulator with Maker post-only fee (0.02%), 0.03% slippage, 3.0% risk per trade
sim = BacktestSimulator(slippage_pct=0.03, taker_fee_pct=0.02, initial_capital=10000.0, order_execution_mode="maker")

configs = [
    ("1. Baseline (12-Bar Donchian)", sig_base, 1.3, 2.0),
    ("2. + Item 2 (TA Oscillators & Volume Flow)", sig_ta, 1.3, 2.0),
    ("3. + Item 3 (SMC Institutional Alignment)", sig_smc, 1.0, 2.5),  # Tighter stop (1.0x ATR) & wider TP (2.5x ATR)
    ("4. Full Synergy (Items 1 + 2 + 3 Combined)", sig_synergy, 1.0, 2.8), # Asymmetric R:R (1.0x SL, 2.8x TP)
]

print("\nRunning BacktestSimulator across all 99,999 real bars...")
results = []
for name, s_df, sl_m, tp_m in configs:
    res = sim.run_backtest(
        df_m15, s_df,
        risk_per_trade_pct=3.0,
        atr_sl_mult=sl_m,
        atr_tp_mult=tp_m,
        partial_take_profit=True,
    )
    results.append({
        "name": name,
        "final_capital": res["final_capital"],
        "net_return_pct": res["net_roi_total_pct"],
        "monthly_roi": res["monthly_roi_pct"],
        "max_dd_pct": res["max_drawdown_pct"],
        "total_trades": res["total_trades"],
        "win_rate": res["win_rate"],
        "profit_factor": res["profit_factor"],
        "sharpe": res.get("sharpe_ratio", 0.0),
    })

start_time_str = str(df_m15["timestamp"].iloc[0])[:10]
end_time_str = str(df_m15["timestamp"].iloc[-1])[:10]
months = (pd.to_datetime(end_time_str) - pd.to_datetime(start_time_str)).days / 30.4375

print("\n" + "="*95)
print(f"REAL BACKTEST BENCHMARK RESULTS: {months:.1f} MONTHS ({start_time_str} to {end_time_str}, 99,999 M15 BARS)")
print("="*95)
print(f"{'Strategy Configuration':<42} | {'Monthly ROI':<12} | {'Net Return':<12} | {'Max DD':<8} | {'Win Rate':<9} | {'Trades':<7} | {'PF':<5}")
print("-" * 95)
for r in results:
    sign = "+" if r["net_return_pct"] >= 0 else ""
    print(f"{r['name']:<42} | {sign}{r['monthly_roi']:>6.2f}%/mo | {sign}{r['net_return_pct']:>9.2f}% | {r['max_dd_pct']:>6.2f}% | {r['win_rate']:>6.2f}% | {r['total_trades']:>6d} | {r['profit_factor']:>4.2f}")
print("="*95)
