"""
Event Calendar Filter:
Fetches economic calendar from Forex Factory JSON feed.
Blocks trading +/- 30 minutes around high-impact events.
"""
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone, timedelta
import requests
import json
import os


class EventFilter:
    DEFAULT_FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

    # Mapping instruments to relevant currencies
    CURRENCY_MAP = {
        "EURUSD": ["EUR", "USD"],
        "GBPUSD": ["GBP", "USD"],
        "USDJPY": ["USD", "JPY"],
        "AUDUSD": ["AUD", "USD"],
        "XAUUSD": ["USD"],
        "BTC/USDT": ["USD"],
        "ETH/USDT": ["USD"],
        "SOL/USDT": ["USD"],
        "BTC/USDT:USDT": ["USD"],
        "ETH/USDT:USDT": ["USD"],
        "SOL/USDT:USDT": ["USD"],
    }

    def __init__(self, cache_file: str = "data/calendar_cache.json", feed_url: Optional[str] = None):
        self.cache_file = cache_file
        self.feed_url = feed_url or self.DEFAULT_FEED_URL
        self.events: List[Dict[str, Any]] = []
        self._load_cache()

    def _load_cache(self) -> None:
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r") as f:
                    self.events = json.load(f)
            except Exception:
                self.events = []

    def _save_cache(self) -> None:
        os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
        try:
            with open(self.cache_file, "w") as f:
                json.dump(self.events, f, indent=2)
        except Exception:
            pass

    def refresh_calendar(self) -> bool:
        """Fetch latest weekly calendar from remote feed."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
            }
            resp = requests.get(self.feed_url, headers=headers, timeout=10)
            if resp.status_code == 200:
                raw_data = resp.json()
                parsed = []
                for item in raw_data:
                    parsed.append({
                        "title": item.get("title", ""),
                        "country": item.get("country", ""),
                        "date": item.get("date", ""),
                        "impact": item.get("impact", "Low"),
                        "forecast": item.get("forecast", ""),
                        "previous": item.get("previous", ""),
                    })
                self.events = parsed
                self._save_cache()
                return True
        except Exception:
            pass
        return False

    def is_high_impact_window(
        self,
        symbol: str,
        current_time: Optional[datetime] = None,
        window_minutes: int = 30,
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Check if current_time falls within window_minutes of any High-impact event for the symbol.
        """
        now = current_time or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        currencies = self.CURRENCY_MAP.get(symbol, ["USD"])
        window_delta = timedelta(minutes=window_minutes)

        for event in self.events:
            if event.get("impact") != "High":
                continue

            event_country = event.get("country", "").upper()
            if event_country not in currencies:
                continue

            # Parse event date: e.g. "2025-01-15T13:30:00-05:00" or ISO format
            date_str = event.get("date")
            if not date_str:
                continue

            try:
                event_dt = datetime.fromisoformat(date_str)
                if event_dt.tzinfo is None:
                    event_dt = event_dt.replace(tzinfo=timezone.utc)
                diff = abs(now - event_dt)
                if diff <= window_delta:
                    return True, event
            except Exception:
                continue

        return False, None

    def get_next_event(self, symbol: str, current_time: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
        """Return the next upcoming high-impact event for the symbol."""
        now = current_time or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        currencies = self.CURRENCY_MAP.get(symbol, ["USD"])
        upcoming = []

        for event in self.events:
            if event.get("impact") != "High":
                continue
            if event.get("country", "").upper() not in currencies:
                continue
            try:
                event_dt = datetime.fromisoformat(event.get("date"))
                if event_dt.tzinfo is None:
                    event_dt = event_dt.replace(tzinfo=timezone.utc)
                if event_dt >= now:
                    upcoming.append((event_dt, event))
            except Exception:
                continue

        if not upcoming:
            return None
        upcoming.sort(key=lambda x: x[0])
        return upcoming[0][1]
