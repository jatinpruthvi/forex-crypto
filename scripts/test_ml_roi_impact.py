import pandas as pd
import numpy as np
import os
import joblib

from core.analysis.fast_backtester import BacktestSimulator
from scripts.evaluate_dd_scaling import DynamicDDBacktestSimulator
from core.ml.features import FeatureEngineer
from core.regime.detector import RegimeDetector
import xgboost as xgb

# 1. Load Real BTC Dataset
df = pd.read_csv("data/btc_real_dataset.csv"); df["timestamp"] = df["date"] if "date" in df.columns else df.index
print(f"Loaded {len(df)} candles.")

# 2. Extract Base Features & Technical Indicators
fe = FeatureEngineer()
rd = RegimeDetector()

close = df["close"]
high = df["high"]
low = df["low"]
open_p = df["open"]
vol = df["volume"]

tr = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
atr = tr.rolling(14).mean()
large_candle = (high - low) > 1.8 * atr
ema50 = close.ewm(span=50).mean()

ema50_slope_up = ema50 > ema50.shift(3)
ema50_slope_down = ema50 < ema50.shift(3)

vol_surge = vol > vol.rolling(20).mean()
price_stretch = (close - ema50) / ema50

bull_expansion = (close > open_p) & large_candle & (close > ema50) & ema50_slope_up & vol_surge & (price_stretch < 0.05)
bear_expansion = (close < open_p) & large_candle & (close < ema50) & ema50_slope_down & vol_surge & (price_stretch > -0.05)

# Regime detection
df_classified = rd.detect(df)

# Feature matrix
df_features = fe.create_features(
    df,
    signals_dict={"funding_rate": 0.0001, "oi_change_pct": 0.5, "long_short_ratio": 1.1, "taker_ratio": 1.05, "conviction": 75.0},
    regime_info={"hurst": 0.55, "atr_percentile": 60.0, "regime": "TREND"}
)

# Labeling: Forward 12 candles (>1.5% return = 1, <-1.5% = 0)
y_labels = fe.create_labels(df, forward_bars=12, threshold_pct=1.5)

# Train on first 650 candles, test out-of-sample on last 350 candles
split_idx = 650
X_train = df_features.iloc[:split_idx]
y_train = y_labels.iloc[:split_idx]

X_test = df_features.iloc[split_idx:]
y_test = y_labels.iloc[split_idx:]

# Filter valid labels
valid_train = y_train.isin([0, 1])
X_tr = X_train[valid_train]
y_tr = y_train[valid_train]

model = xgb.XGBClassifier(
    n_estimators=100,
    max_depth=3,
    learning_rate=0.03,
    subsample=0.8,
    colsample_bytree=0.8,
    random_state=42,
    eval_metric="logloss"
)
model.fit(X_tr, y_tr)

# Predict probabilities across the entire dataset
probs = model.predict_proba(df_features)[:, 1]

# Save trained model to models/model_xgb.pkl
os.makedirs("models", exist_ok=True)
joblib.dump(model, "models/model_xgb.pkl")

# Baseline Signals (Without ML Probability Filter)
signals_base = pd.DataFrame(index=df.index)
signals_base["signal"] = 0
signals_base["atr"] = atr
signals_base["conviction"] = 85.0
signals_base.loc[bull_expansion, "signal"] = 1
signals_base.loc[bear_expansion, "signal"] = -1

# ML-Augmented Signals:
# Only allow long if P(profit) >= 0.52
# Only allow short if P(profit) <= 0.48
ml_long_filter = probs >= 0.52
ml_short_filter = probs <= 0.48

signals_ml = pd.DataFrame(index=df.index)
signals_ml["signal"] = 0
signals_ml["atr"] = atr
signals_ml["conviction"] = 85.0
signals_ml.loc[bull_expansion & ml_long_filter, "signal"] = 1
signals_ml.loc[bear_expansion & ml_short_filter, "signal"] = -1

# Simulator
sim = DynamicDDBacktestSimulator(slippage_pct=0.1, taker_fee_pct=0.055, initial_capital=323.0)

res_base = sim.run_backtest_with_dd_guard(df, signals_base, base_risk_pct=3.5, atr_sl_mult=1.6, atr_tp_mult=2.4)
res_ml = sim.run_backtest_with_dd_guard(df, signals_ml, base_risk_pct=3.5, atr_sl_mult=1.6, atr_tp_mult=2.4)

print("="*60)
print(f"BASELINE STRATEGY (Rule-based Trend-Consensus + DD Guard):")
print(f"  Monthly ROI: {res_base['monthly_roi_pct']:.2f}%")
print(f"  Max Drawdown: {res_base['max_drawdown_pct']:.2f}%")
print(f"  Win Rate: {res_base['win_rate']:.2f}% ({res_base['total_trades']} trades)")
print(f"  Profit Factor: {res_base['profit_factor']:.2f}")
print(f"  Calmar Ratio: {res_base['monthly_roi_pct']/res_base['max_drawdown_pct']:.2f}")

print("="*60)
print(f"ML-AUGMENTED STRATEGY (XGBoost Prob Filter P>=0.52):")
print(f"  Monthly ROI: {res_ml['monthly_roi_pct']:.2f}%")
print(f"  Max Drawdown: {res_ml['max_drawdown_pct']:.2f}%")
print(f"  Win Rate: {res_ml['win_rate']:.2f}% ({res_ml['total_trades']} trades)")
print(f"  Profit Factor: {res_ml['profit_factor']:.2f}")
print(f"  Calmar Ratio: {res_ml['monthly_roi_pct']/res_ml['max_drawdown_pct']:.2f}")
print("="*60)

# Out-of-sample test (bars 650 to 1000)
df_oos = df.iloc[split_idx:].reset_index(drop=True)
sig_base_oos = signals_base.iloc[split_idx:].reset_index(drop=True)
sig_ml_oos = signals_ml.iloc[split_idx:].reset_index(drop=True)

res_base_oos = sim.run_backtest_with_dd_guard(df_oos, sig_base_oos, base_risk_pct=3.5, atr_sl_mult=1.6, atr_tp_mult=2.4)
res_ml_oos = sim.run_backtest_with_dd_guard(df_oos, sig_ml_oos, base_risk_pct=3.5, atr_sl_mult=1.6, atr_tp_mult=2.4)

print(f"OUT-OF-SAMPLE TEST (Unseen 350 Bars):")
print(f"  Base OOS Monthly ROI: {res_base_oos['monthly_roi_pct']:.2f}% | Max DD: {res_base_oos['max_drawdown_pct']:.2f}% | Win Rate: {res_base_oos['win_rate']:.2f}%")
print(f"  ML   OOS Monthly ROI: {res_ml_oos['monthly_roi_pct']:.2f}% | Max DD: {res_ml_oos['max_drawdown_pct']:.2f}% | Win Rate: {res_ml_oos['win_rate']:.2f}%")
print("="*60)
