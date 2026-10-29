#!/usr/bin/env python3
"""
Automated Weekly Retraining Scheduler:
1. Loads recent market candles from data/
2. Generates feature matrix and labels
3. Invokes WalkForwardLearner to detect drift and retrain models/model_xgb.pkl
4. Verifies safety fallback guard and logs status
"""

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import logging
import pandas as pd
from datetime import datetime, timezone
from core.ml.features import FeatureEngineer
from core.ml.walk_forward_learner import WalkForwardLearner

logging.basicConfig(level=logging.INFO, format="%(asctime)s [auto_retrain] %(message)s")
logger = logging.getLogger("auto_retrain")


def run_scheduled_retrain():
    data_path = "data/btc_real_dataset.csv"
    if not os.path.exists(data_path):
        logger.warning(f"Data file {data_path} not found. Skipping retrain cycle.")
        return

    logger.info("Starting automated walk-forward retraining cycle...")
    df = pd.read_csv(data_path)
    df["timestamp"] = df["date"] if "date" in df.columns else df.index

    fe = FeatureEngineer()
    df_features = fe.create_features(
        df,
        signals_dict={"funding_rate": 0.0001, "oi_change_pct": 0.5, "long_short_ratio": 1.1, "taker_ratio": 1.05, "conviction": 75.0},
        regime_info={"hurst": 0.55, "atr_percentile": 60.0, "regime": "TREND"}
    )
    y_labels = fe.create_labels(df, forward_bars=12, threshold_pct=1.5)

    learner = WalkForwardLearner(
        model_path="models/model_xgb.pkl",
        history_window_bars=650,
        validation_window_bars=150,
        min_acceptable_accuracy=0.51
    )

    res = learner.evaluate_and_retrain(df_features, y_labels)
    logger.info(f"Retrain Cycle Result: {res}")


if __name__ == "__main__":
    run_scheduled_retrain()
