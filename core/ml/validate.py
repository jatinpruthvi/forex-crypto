"""
ML Model Validation & Retraining Module:
Implements Walk-Forward Validation and Automated Monthly Retraining.
"""
from typing import Dict, Any, List
import pandas as pd
import numpy as np


class MLValidator:
    def __init__(self, n_windows: int = 4):
        self.n_windows = n_windows

    def walk_forward_split(
        self, df_features: pd.DataFrame, labels: pd.Series
    ) -> List[Dict[str, Any]]:
        """
        Splits dataset into n_windows rolling train/test slices.
        """
        valid_indices = labels[labels.isin([0, 1])].index
        clean_X = df_features.loc[valid_indices]
        clean_y = labels.loc[valid_indices]

        n = len(clean_X)
        if n < 100:
            return []

        window_size = n // (self.n_windows + 1)
        splits = []

        for w in range(self.n_windows):
            train_end = (w + 2) * window_size
            test_end = min(n, train_end + window_size)

            X_train = clean_X.iloc[:train_end]
            y_train = clean_y.iloc[:train_end]
            X_test = clean_X.iloc[train_end:test_end]
            y_test = clean_y.iloc[train_end:test_end]

            splits.append({
                "window": w + 1,
                "X_train": X_train,
                "y_train": y_train,
                "X_test": X_test,
                "y_test": y_test,
            })

        return splits
