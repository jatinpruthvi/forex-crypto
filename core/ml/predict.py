"""
Model Inference Wrapper:
Loads XGBoost model and produces trade success probabilities P(profitable).
"""
import os
import joblib
import numpy as np
import pandas as pd
from typing import Optional, Dict, Any


class MLPredictor:
    def __init__(self, model_path: str = "models/model_xgb.pkl"):
        self.model_path = model_path
        self.model = None
        self.load_model()

    def load_model(self) -> bool:
        if os.path.exists(self.model_path):
            try:
                self.model = joblib.load(self.model_path)
                return True
            except Exception:
                self.model = None
        return False

    def predict_probability(self, features_df: pd.DataFrame) -> float:
        """
        Returns probability of class 1 (successful trade).
        Defaults to 0.50 if model is unavailable.
        """
        if self.model is None:
            # Fallback if model hasn't been trained yet
            return 0.50

        try:
            # Extract features matching the model's expected columns if available
            if hasattr(self.model, "feature_names_in_"):
                expected_cols = list(self.model.feature_names_in_)
                # Check if all expected cols exist in dataframe
                if all(col in features_df.columns for col in expected_cols):
                    input_data = features_df[expected_cols].iloc[-1:]
                else:
                    input_data = features_df.iloc[-1:]
            else:
                input_data = features_df.iloc[-1:]

            if hasattr(self.model, "predict_proba"):
                probs = self.model.predict_proba(input_data)
                return float(probs[0][1])
            elif hasattr(self.model, "predict"):
                preds = self.model.predict(input_data)
                return float(preds[0])
        except Exception:
            pass

        return 0.50
