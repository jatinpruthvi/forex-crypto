"""
TradingView TvDatafeed Automated Ingestion Client:
Connects to TradingView's datafeed to fetch up to 5,000 bars
across M15, H1, and H4 timeframes for BTC, SOL, BNB, and LINK.
"""
from typing import Optional, Dict, Any
import os
import logging
import pandas as pd

logger = logging.getLogger("tv_ingestion")


class TvDatafeedClient:
    """
    Automated client for pulling TradingView historical OHLCV data.
    Provides graceful fallback to local cache or offline datasets.
    """
    def __init__(self, username: Optional[str] = None, password: Optional[str] = None):
        self.username = username or os.getenv("TRADINGVIEW_USERNAME")
        self.password = password or os.getenv("TRADINGVIEW_PASSWORD")
        self._tv = None

    def _get_instance(self):
        if self._tv is None:
            try:
                from tvDatafeed import TvDatafeed
                if self.username and self.password:
                    self._tv = TvDatafeed(username=self.username, password=self.password)
                else:
                    self._tv = TvDatafeed()
            except Exception as e:
                logger.warning(f"Could not initialize TvDatafeed: {e}")
                self._tv = None
        return self._tv

    def fetch_historical_bars(
        self,
        symbol: str = "BTCUSDT",
        exchange: str = "BINANCE",
        n_bars: int = 500,
        interval_str: str = "15m",
    ) -> Optional[pd.DataFrame]:
        """
        Fetches up to n_bars for the specified symbol and interval.
        interval_str: '1m', '5m', '15m', '1h', '4h', '1d'
        """
        tv = self._get_instance()
        if tv is None:
            logger.warning("TvDatafeed instance unavailable. Using local fallback.")
            return None

        try:
            from tvDatafeed import Interval
            interval_map = {
                "1m": Interval.in_1_minute,
                "5m": Interval.in_5_minute,
                "15m": Interval.in_15_minute,
                "1h": Interval.in_1_hour,
                "4h": Interval.in_4_hour,
                "1d": Interval.in_daily,
            }
            tv_interval = interval_map.get(interval_str, Interval.in_15_minute)
            df = tv.get_hist(symbol=symbol, exchange=exchange, interval=tv_interval, n_bars=n_bars)

            if df is not None and not df.empty:
                df = df.reset_index()
                # Normalize column headers
                df.columns = [c.lower() for c in df.columns]
                if "datetime" in df.columns and "timestamp" not in df.columns:
                    df["timestamp"] = df["datetime"].astype(str)
                return df

        except Exception as e:
            logger.warning(f"Error fetching {symbol} from TradingView: {e}")

        return None
