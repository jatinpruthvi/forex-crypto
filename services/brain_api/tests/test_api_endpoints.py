import pytest
from fastapi.testclient import TestClient
from services.brain_api.main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "alive"
    assert "uptime_seconds" in data


def test_signal_endpoint(sample_ohlcv_df):
    ohlcv_list = sample_ohlcv_df[["open", "high", "low", "close", "volume"]].values.tolist()

    payload = {
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "ohlcv": ohlcv_list,
        "account_equity": 10000.0,
        "open_positions": [],
        "signals_override": {
            "funding_rate": -0.0004,
            "oi_change_pct": 3.0,
            "long_short_ratio": 0.45,
            "taker_ratio": 1.15,
        },
    }

    response = client.post("/signal", json=payload)
    assert response.status_code == 200
    res_data = response.json()

    assert res_data["action"] in ["BUY", "SELL", "HOLD", "CLOSE_ALL"]
    assert "regime" in res_data
    assert "confidence" in res_data
    assert "sl" in res_data
    assert "tp" in res_data


def test_emergency_close():
    response = client.post("/close_all")
    assert response.status_code == 200
    assert response.json()["action"] == "CLOSE_ALL"
