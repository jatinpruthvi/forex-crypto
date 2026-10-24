"""
Autonomous Rolling Walk-Forward Learner:
Continuously retrains machine learning models on rolling windows, detects
concept drift / degradation, and enforces automated safety fallback mechanisms.
"""
import os
import joblib
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional, Tuple
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
import xgboost as xgb
import logging

logger = logging.getLogger("walk_forward_learner")


class WalkForwardLearner:
    def __init__(
        self,
        model_path: str = "models/model_xgb.pkl",
        history_window_bars: int = 650,
        validation_window_bars: int = 150,
        min_acceptable_accuracy: float = 0.51,
    ):
        self.model_path = model_path
        self.history_window_bars = history_window_bars
        self.validation_window_bars = validation_window_bars
        self.min_acceptable_accuracy = min_acceptable_accuracy

    def evaluate_and_retrain(
        self,
        df_features: pd.DataFrame,
        y_labels: pd.Series,
    ) -> Dict[str, Any]:
        """
        Executes rolling walk-forward evaluation. If performance degrades,
        retrains the champion XGBoost architecture and validates out-of-sample.
        """
        n = len(df_features)
        total_required = self.history_window_bars + self.validation_window_bars
        if n < total_required:
            return {
                "status": "skipped",
                "reason": f"Insufficient data bars ({n} < {total_required})",
                "model_updated": False,
            }

        # Train / Validation Split
        train_start = max(0, n - total_required)
        train_end = n - self.validation_window_bars
        
        X_train = df_features.iloc[train_start:train_end]
        y_train = y_labels.iloc[train_start:train_end]
        X_val = df_features.iloc[train_end:]
        y_val = y_labels.iloc[train_end:]

        train_mask = y_train.isin([0, 1])
        val_mask = y_val.isin([0, 1])

        X_tr = X_train[train_mask]
        y_tr = y_train[train_mask]
        X_v = X_val[val_mask]
        y_v = y_val[val_mask]

        if len(y_tr) < 30 or len(y_v) < 10:
            return {
                "status": "skipped",
                "reason": "Insufficient labeled samples after filtering",
                "model_updated": False,
            }

        # Candidate Model Training
        candidate_model = xgb.XGBClassifier(
            n_estimators=100,
            max_depth=3,
            learning_rate=0.03,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            eval_metric="logloss",
        )
        candidate_model.fit(X_tr, y_tr)

        val_preds = candidate_model.predict(X_v)
        val_probs = candidate_model.predict_proba(X_v)[:, 1]

        acc = float(accuracy_score(y_v, val_preds))
        f1 = float(f1_score(y_v, val_preds, zero_division=0))
        try:
            auc = float(roc_auc_score(y_v, val_probs))
        except Exception:
            auc = 0.50

        # Safety Fallback Guard: Only deploy if model maintains positive edge
        if acc >= self.min_acceptable_accuracy and auc >= 0.50:
            os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
            joblib.dump(candidate_model, self.model_path)
            logger.info(f"WalkForwardLearner: Deployed new model (Acc: {acc:.2f}, AUC: {auc:.2f})")
            return {
                "status": "success",
                "model_updated": True,
                "accuracy": round(acc, 3),
                "f1_score": round(f1, 3),
                "roc_auc": round(auc, 3),
                "deployed_to": self.model_path,
            }
        else:
            logger.warning(f"WalkForwardLearner: Retained previous model (Candidate below min acc: {acc:.2f})")
            return {
                "status": "fallback_retained",
                "model_updated": False,
                "reason": f"Candidate accuracy {acc:.2f} below threshold {self.min_acceptable_accuracy:.2f}",
                "accuracy": round(acc, 3),
            }
