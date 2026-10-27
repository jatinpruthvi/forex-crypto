import os
import pytest
import pandas as pd
import numpy as np
import joblib

def test_champion_model_inference():
    model_path = "models/model_xgb.pkl"
    assert os.path.exists(model_path), "Champion ML model must exist in models/model_xgb.pkl"
    model = joblib.load(model_path)

    # Synthetic sample feature vector (matching 7 champion feature inputs)
    # ['returns_1', 'returns_4', 'vol_20', 'vol_ratio', 'trend_dist', 'ema50_slope', 'atr_rel']
    sample_df = pd.DataFrame([{
        "returns_1": 0.01,
        "returns_4": 0.02,
        "vol_20": 0.015,
        "vol_ratio": 1.2,
        "trend_dist": 0.005,
        "ema50_slope": 0.001,
        "atr_rel": 0.01
    }])
    
    if hasattr(model, "predict_proba"):
        probs = model.predict_proba(sample_df)
        assert probs.shape[1] == 2
        p_profit = probs[0][1]
        assert 0.0 <= p_profit <= 1.0

def test_ml_experiments_ledger_integrity():
    ledger_path = ".agent/ml_experiments_ledger.json"
    assert os.path.exists(ledger_path), "ML experiments ledger must exist"
    import json
    with open(ledger_path) as f:
        experiments = json.load(f)
    assert len(experiments) >= 50, f"Expected at least 50 experiments, found {len(experiments)}"
