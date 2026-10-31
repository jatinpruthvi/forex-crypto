import pytest
from core.ml.features import FeatureEngineer


def test_feature_engineering_shape(sample_ohlcv_df):
    fe = FeatureEngineer()
    features = fe.create_features(
        sample_ohlcv_df,
        signals_dict={"funding_rate": 0.0001, "oi_change_pct": 2.5, "long_short_ratio": 1.2, "taker_ratio": 1.05},
        regime_info={"hurst": 0.62, "atr_percentile": 45.0, "regime": "TREND"},
    )

    assert len(features) == len(sample_ohlcv_df)
    assert features.shape[1] >= 24  # Base 24 features + TA & Smart Money structure indicators (30 total)
    assert "returns_1h" in features.columns
    assert "volatility_ratio" in features.columns
    assert "hurst" in features.columns
    assert "conviction" in features.columns
