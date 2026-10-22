"""
Data Collector Service:
Pulls Funding Rate, Open Interest, Long/Short Ratio, and Taker Ratios hourly.
Persists records into SQLite data/signals.db.
Designed to run standalone or via cron.
"""
import logging
from datetime import datetime, timezone
import sys

import os
from services.data_collector.storage import SignalStorage
from services.data_collector.sources.bybit import BybitSource
from services.data_collector.sources.binance import BinanceSource
from core.signals.event_filter import EventFilter

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] data_collector: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/collector.log", mode="a", encoding="utf-8")
    ],
)
logger = logging.getLogger("collector")

TARGET_SYMBOLS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]


def collect_hourly_signals() -> None:
    storage = SignalStorage("data/signals.db")
    bybit = BybitSource(testnet=False)
    binance = BinanceSource()
    event_filter = EventFilter()

    now_iso = datetime.now(timezone.utc).isoformat()
    logger.info("Beginning hourly data collection cycle...")

    # 1. Refresh economic calendar
    try:
        event_filter.refresh_calendar()
        logger.info("Forex Factory economic calendar refreshed.")
    except Exception as e:
        logger.warning(f"Failed to refresh calendar: {e}")

    # 2. Collect market signals for each pair
    for sym in TARGET_SYMBOLS:
        try:
            bybit_data = bybit.fetch_market_signals(sym)
            ls_ratio = binance.fetch_long_short_ratio(sym)

            # Previous OI to calculate % change
            prev_signal = storage.get_latest_signal(sym)
            oi_change = 0.0
            if prev_signal and prev_signal.get("open_interest"):
                old_oi = prev_signal["open_interest"]
                new_oi = bybit_data["open_interest"]
                if old_oi > 0:
                    oi_change = ((new_oi - old_oi) / old_oi) * 100.0

            record = {
                "timestamp": now_iso,
                "symbol": sym,
                "funding_rate": bybit_data["funding_rate"],
                "open_interest": bybit_data["open_interest"],
                "oi_change_pct": round(oi_change, 3),
                "long_short_ratio": ls_ratio,
                "taker_buy_volume": bybit_data["taker_buy_volume"],
                "taker_sell_volume": bybit_data["taker_sell_volume"],
                "taker_ratio": bybit_data["taker_ratio"],
            }
            storage.insert_signal(record)
            logger.info(
                f"Saved signal {sym}: Funding={record['funding_rate']:.5f}, "
                f"OI={record['open_interest']:.0f}, L/S={record['long_short_ratio']:.2f}"
            )
        except Exception as err:
            logger.error(f"Error collecting data for {sym}: {err}")

    logger.info("Collection cycle completed successfully.")


if __name__ == "__main__":
    collect_hourly_signals()
