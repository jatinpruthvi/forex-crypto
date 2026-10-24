import pytest
from core.signals.event_filter import EventFilter
from datetime import datetime, timezone


def test_event_filter_window():
    filter_engine = EventFilter(cache_file="data/test_cal.json")
    # Inject mock event
    filter_engine.events = [
        {
            "title": "US CPI",
            "country": "USD",
            "date": "2025-01-15T13:30:00+00:00",
            "impact": "High",
        }
    ]

    # Test exact window (13:40 UTC is within 30 min of 13:30)
    test_time = datetime(2025, 1, 15, 13, 40, tzinfo=timezone.utc)
    is_impact, ev = filter_engine.is_high_impact_window("BTC/USDT", current_time=test_time, window_minutes=30)
    assert is_impact is True
    assert ev["title"] == "US CPI"

    # Test outside window (15:00 UTC is >30m)
    safe_time = datetime(2025, 1, 15, 15, 0, tzinfo=timezone.utc)
    is_impact_safe, _ = filter_engine.is_high_impact_window("BTC/USDT", current_time=safe_time, window_minutes=30)
    assert is_impact_safe is False
