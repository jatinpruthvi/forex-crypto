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
if len(df_m15) > 20000:
    df_m15 = df_m15.iloc[-20000:].reset_index(drop=True)

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

# Exchange Fee Schedules (Maker Post-Only vs Taker)
# 1. MEXC: 0.000% Maker, 0.020% Taker (Futures promo / standard)
# 2. Bybit: 0.020% Maker (0.010% for VIP), 0.055% Taker
# 3. Binance: 0.020% Maker (0.018% w/ BNB), 0.050% Taker (0.045% w/ BNB)
# 4. Bitget: 0.020% Maker, 0.060% Taker
# 5. OKX: 0.020% Maker, 0.050% Taker
# 6. Kraken Futures: 0.020% Maker, 0.050% Taker
# 7. Coinbase Advanced: 0.400% Maker, 0.600% Taker (Highest)

exchanges = [
    ("MEXC (Zero Maker Promo)    ", 0.000, 0.0000), # 0.00% maker
    ("Bybit (Post-Only Maker)     ", 0.000, 0.0002), # 0.02% maker
    ("Binance Futures (Maker + BNB)", 0.000, 0.00018),# 0.018% maker
    ("OKX Futures (Maker)         ", 0.000, 0.0002), # 0.02% maker
    ("Bitget Futures (Maker)      ", 0.000, 0.0002), # 0.02% maker
    ("Bybit (Market Taker)        ", 0.030, 0.00055),# 0.055% taker + 0.03% slip
    ("Binance (Market Taker)      ", 0.030, 0.00050),# 0.050% taker + 0.03% slip
    ("Coinbase Advanced (High Fee) ", 0.050, 0.00400),# 0.40% maker
]

print("=== REAL PROFIT IMPACT OF BROKER FEES ON OPTION A (398 TRADES) ===")
print("Broker / Execution Route       | Maker Fee | Slippage | Final Capital | Total Return | Comp Monthly | Lost to Fees")
print("--------------------------------------------------------------------------------------------------------------------")

baseline_mexc = None

for name, slip, fee_rate in exchanges:
    sim = BacktestSimulator(slippage_pct=slip, taker_fee_pct=fee_rate * 100.0, initial_capital=1000.0, order_execution_mode="maker" if slip == 0 else "taker")
    # For custom fee rate
    sim.taker_fee = fee_rate
    sim.slippage = slip / 100.0
    res = sim.run_backtest(df_m15, sig, risk_per_trade_pct=3.0, atr_sl_mult=1.3, atr_tp_mult=2.0)
    
    fc = res["final_capital"]
    tot = res["net_roi_total_pct"]
    cm = res["monthly_roi_pct"]
    
    if baseline_mexc is None:
        baseline_mexc = fc
        fee_drag = "$0.00"
    else:
        diff = baseline_mexc - fc
        fee_drag = f"-${diff:,.2f}"
        
    print(f"{name} |   {fee_rate*100:5.3f}%  |  {slip:4.2f}%   | ${fc:12.2f} | +{tot:8.2f}% | +{cm:10.2f}%/mo | {fee_drag}")
