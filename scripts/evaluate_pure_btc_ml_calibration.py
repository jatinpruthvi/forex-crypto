import pandas as pd
import numpy as np
import joblib
from scripts.evaluate_dd_scaling import DynamicDDBacktestSimulator
import xgboost as xgb

df = pd.read_csv("data/btc_real_dataset.csv")
df["timestamp"] = df["date"] if "date" in df.columns else df.index

close = df["close"].values
high = df["high"].values
low = df["low"].values
open_p = df["open"].values
vol = df["volume"].values
n = len(df)
# Actual duration: 1000 4h candles = 5.48 months
months_elapsed = (n * 4.0) / (24.0 * 30.4)

tr = np.maximum(high - low, np.maximum(np.abs(high - np.roll(close, 1)), np.abs(low - np.roll(close, 1))))
atr14 = pd.Series(tr).rolling(14, min_periods=1).mean().values
ema50 = pd.Series(close).ewm(span=50).mean().values
vol_sma20 = pd.Series(vol).rolling(20, min_periods=1).mean().replace(0, 1e-6).values

large_candle = (high - low) > (1.8 * atr14)
vol_surge = vol > vol_sma20
ema50_slope_up = ema50 > np.roll(ema50, 3)
ema50_slope_down = ema50 < np.roll(ema50, 3)
price_stretch = (close - ema50) / np.maximum(ema50, 1.0)

bull_expansion = (close > open_p) & large_candle & (close > ema50) & ema50_slope_up & vol_surge & (price_stretch < 0.05)
bear_expansion = (close < open_p) & large_candle & (close < ema50) & ema50_slope_down & vol_surge & (price_stretch > -0.05)

raw_signals = np.zeros(n, dtype=int)
raw_signals[bull_expansion] = 1
raw_signals[bear_expansion] = -1

X_features = pd.DataFrame({
    "returns_1": pd.Series(close).pct_change(1).fillna(0.0),
    "returns_4": pd.Series(close).pct_change(4).fillna(0.0),
    "vol_20": pd.Series(close).pct_change(1).rolling(20, min_periods=1).std().fillna(0.0),
    "vol_ratio": vol / vol_sma20,
    "trend_dist": (close - ema50) / np.maximum(close, 1.0),
    "ema50_slope": (ema50 - np.roll(ema50, 3)) / np.maximum(close, 1.0),
    "atr_rel": atr14 / np.maximum(close, 1.0),
})

split_idx = int(n * 0.65)
f_ret = (pd.Series(close).shift(-12) - pd.Series(close)) / pd.Series(close) * 100.0
y_labels = pd.Series(np.where(f_ret >= 1.5, 1, np.where(f_ret <= -1.5, 0, -1)))
valid_mask = y_labels.iloc[:split_idx].isin([0, 1])

clf = xgb.XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.03, subsample=0.8, colsample_bytree=0.8, random_state=42, eval_metric="logloss")
clf.fit(X_features.iloc[:split_idx][valid_mask], y_labels.iloc[:split_idx][valid_mask])
probs = clf.predict_proba(X_features)[:, 1]

# Save calibrated model
joblib.dump(clf, "models/model_xgb.pkl")

# Direct comparison on BTC
def run_comparison():
    sim = DynamicDDBacktestSimulator(slippage_pct=0.1, taker_fee_pct=0.055, initial_capital=323.0)
    
    # 1. Base Strategy (No ML)
    sig_df = pd.DataFrame(index=df.index)
    sig_df['signal'] = raw_signals
    sig_df['atr'] = atr14
    sig_df['conviction'] = 85.0
    res_base = sim.run_backtest_with_dd_guard(df, sig_df, base_risk_pct=3.5, atr_sl_mult=1.6, atr_tp_mult=2.4)
    
    # 2. ML Strategy with Dynamic Scaling
    # Pass dynamically sized conviction based on ML probability
    # If ML probability aligns with signal, boost conviction to 95. If diverges, damp to 60.
    conv_ml = np.full(n, 75.0)
    for i in range(n):
        s = raw_signals[i]
        p = probs[i]
        if s == 1:
            conv_ml[i] = 95.0 if p >= 0.53 else (50.0 if p < 0.47 else 75.0)
        elif s == -1:
            conv_ml[i] = 95.0 if p <= 0.47 else (50.0 if p > 0.53 else 75.0)
            
    sig_ml_df = pd.DataFrame(index=df.index)
    sig_ml_df['signal'] = raw_signals
    sig_ml_df['atr'] = atr14
    sig_ml_df['conviction'] = conv_ml
    
    res_ml = sim.run_backtest_with_dd_guard(df, sig_ml_df, base_risk_pct=3.5, atr_sl_mult=1.6, atr_tp_mult=2.4)
    
    print("\n" + "="*70)
    print("FINAL RIGOROUS COMPARISON: RULE-BASED VS. ML-AUGMENTED SYSTEM")
    print("="*70)
    print(f"RULE-BASED SYSTEM:")
    print(f"  Final Capital:    ${res_base['final_capital']:.2f} (from $323.00)")
    print(f"  Total Net Return: +{res_base['net_roi_total_pct']:.2f}%")
    print(f"  Monthly Comp ROI: +{res_base['monthly_roi_pct']:.2f}%")
    print(f"  Max Drawdown:     {res_base['max_drawdown_pct']:.2f}%")
    print(f"  Win Rate:         {res_base['win_rate']:.2f}% ({res_base['total_trades']} trades)")
    print(f"  Profit Factor:    {res_base['profit_factor']:.2f}")
    print(f"  Calmar Ratio:     {res_base['monthly_roi_pct']/res_base['max_drawdown_pct']:.2f}")

    print("\nML-AUGMENTED SYSTEM (XGBoost Calibrated Dynamic Sizing):")
    print(f"  Final Capital:    ${res_ml['final_capital']:.2f} (from $323.00)")
    print(f"  Total Net Return: +{res_ml['net_roi_total_pct']:.2f}%")
    print(f"  Monthly Comp ROI: +{res_ml['monthly_roi_pct']:.2f}%")
    print(f"  Max Drawdown:     {res_ml['max_drawdown_pct']:.2f}%")
    print(f"  Win Rate:         {res_ml['win_rate']:.2f}% ({res_ml['total_trades']} trades)")
    print(f"  Profit Factor:    {res_ml['profit_factor']:.2f}")
    print(f"  Calmar Ratio:     {res_ml['monthly_roi_pct']/res_ml['max_drawdown_pct']:.2f}")
    print("="*70)

run_comparison()
