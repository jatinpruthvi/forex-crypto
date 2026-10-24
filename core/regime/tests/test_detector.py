import pytest
from core.regime.detector import RegimeDetector


def test_regime_detector_trending(sample_ohlcv_df):
    detector = RegimeDetector()
    detected = detector.detect(sample_ohlcv_df)

    assert "hurst" in detected.columns
    assert "atr_percentile" in detected.columns
    assert "regime" in detected.columns

    latest = detector.get_latest_regime(sample_ohlcv_df)
    assert latest["regime"] in ["TREND", "BREAKOUT", "SQUEEZE", "RANGE", "TRANSITION", "CRISIS"]
    assert 0.0 <= latest["hurst"] <= 1.0


def test_regime_classification_rules():
    detector = RegimeDetector()
    assert detector.classify_regime(0.65, 50.0) == "TREND"
    assert detector.classify_regime(0.35, 50.0) == "RANGE"
    assert detector.classify_regime(0.60, 85.0) == "BREAKOUT"
    assert detector.classify_regime(0.60, 10.0) == "SQUEEZE"
    assert detector.classify_regime(0.60, 96.0) == "CRISIS"
