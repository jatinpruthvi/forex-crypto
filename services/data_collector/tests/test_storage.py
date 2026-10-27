import pytest
import os
from services.data_collector.storage import SignalStorage


def test_sqlite_storage():
    test_db = "data/test_signals.db"
    if os.path.exists(test_db):
        os.remove(test_db)

    storage = SignalStorage(test_db)
    inserted = storage.insert_signal({
        "symbol": "BTC/USDT:USDT",
        "funding_rate": 0.0001,
        "open_interest": 5000000.0,
        "oi_change_pct": 2.5,
        "long_short_ratio": 1.15,
        "taker_buy_volume": 1000.0,
        "taker_sell_volume": 900.0,
        "taker_ratio": 1.11,
    })

    assert inserted is True
    latest = storage.get_latest_signal("BTC/USDT")
    assert latest is not None
    assert latest["funding_rate"] == 0.0001
    assert latest["open_interest"] == 5000000.0

    if os.path.exists(test_db):
        os.remove(test_db)
