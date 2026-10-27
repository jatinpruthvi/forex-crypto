import pytest
from services.data_collector.sources.mexc import MEXCSource

def test_mexc_source_initialization():
    source = MEXCSource(testnet=False)
    assert source.exchange.id == "mexc"
    assert source.exchange.options.get("defaultType") == "swap"

def test_mexc_source_data_structure():
    source = MEXCSource(testnet=False)
    # Test fetch_market_signals mock behavior / fallback structure
    res = source.fetch_market_signals("BTC/USDT:USDT")
    assert "symbol" in res
    assert "exchange" in res
    assert res["exchange"] == "mexc"
    assert "funding_rate" in res
    assert "open_interest" in res
