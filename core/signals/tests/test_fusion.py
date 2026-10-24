import pytest
from core.signals.fusion import SignalFusion


def test_signal_fusion_conviction_bullish():
    fusion = SignalFusion()
    bullish_signals = {
        "funding_rate": -0.0004,     # Heavily negative funding -> shorts paying longs -> bullish
        "oi_change_pct": 5.0,        # Expanding open interest
        "long_short_ratio": 0.45,    # Contrarian extreme short crowd
        "taker_ratio": 1.25,         # Aggressive buyers
    }

    result = fusion.calculate_conviction("BTC/USDT", price_change_pct=1.5, signals_override=bullish_signals)
    assert result["direction"] == "LONG"
    assert result["conviction"] >= 70.0
    assert result["breakdown"]["funding"] > 0
    assert result["breakdown"]["ls_ratio"] > 0


def test_signal_fusion_conviction_bearish():
    fusion = SignalFusion()
    bearish_signals = {
        "funding_rate": 0.0006,      # Overleveraged longs
        "oi_change_pct": 5.0,        # Expanding OI on drop
        "long_short_ratio": 2.8,     # Extreme long crowd -> contrarian short
        "taker_ratio": 0.85,         # Aggressive sellers
    }

    result = fusion.calculate_conviction("BTC/USDT", price_change_pct=-1.5, signals_override=bearish_signals)
    assert result["direction"] == "SHORT"
    assert result["conviction"] >= 70.0
    assert result["breakdown"]["funding"] < 0
    assert result["breakdown"]["ls_ratio"] < 0
