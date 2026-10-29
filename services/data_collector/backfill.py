"""
Historical Data Backfill Script:
Populates signals.db with historical records from Bybit & Binance.
Usage: python services/data_collector/backfill.py --days 180
"""
import argparse
import logging
from datetime import datetime, timezone, timedelta
import requests

from services.data_collector.storage import SignalStorage

logging.basicConfig(level=logging.INFO, format="%(asctime)s [backfill] %(message)s")
logger = logging.getLogger("backfill")


def backfill_bybit_funding(symbol: str = "BTCUSDT", limit: int = 200) -> list:
    url = f"https://api.bybit.com/v5/market/funding/history?category=linear&symbol={symbol}&limit={limit}"
    try:
        resp = requests.get(url, timeout=10).json()
        return resp.get("result", {}).get("list", [])
    except Exception as e:
        logger.error(f"Failed to fetch funding history: {e}")
        return []


def run_backfill(days: int = 180):
    storage = SignalStorage("data/signals.db")
    logger.info(f"Starting backfill for past {days} days...")

    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    total_inserted = 0

    for sym in symbols:
        # Bybit funding/history caps at 200 records per request (~33 days at
        # 8h funding); honour --days as far as the API allows and say so.
        limit = max(1, min(200, int(days * 3)))
        if limit < days * 3:
            logger.info(
                f"{sym}: requesting {limit} funding records (API cap 200 ~= "
                f"{200 // 3} days at 8h); --days {days} exceeds one page."
            )
        history = backfill_bybit_funding(sym, limit=limit)
        pair_key = f"{sym[:3]}/{sym[3:]}:USDT"
        for item in history:
            funding_ts = int(item.get("fundingRateTimestamp", 0)) / 1000.0
            dt = datetime.fromtimestamp(funding_ts, tz=timezone.utc).isoformat()
            rate = float(item.get("fundingRate", 0.0))

            record = {
                "timestamp": dt,
                "symbol": pair_key,
                "funding_rate": rate,
                # Unknown in funding history — NEVER fabricate an OI value
                # (a fake 1,000,000 placeholder used to sit here and poisoned
                # downstream OI-change computations).
                "open_interest": 0.0,
                "oi_change_pct": 0.0,
                "long_short_ratio": 1.0,
                "taker_buy_volume": 0.0,
                "taker_sell_volume": 0.0,
                "taker_ratio": 1.0,
            }
            if storage.insert_signal(record):
                total_inserted += 1

    logger.info(f"Backfill finished. Inserted {total_inserted} records into signals.db.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=180, help="Days of history to backfill")
    args = parser.parse_args()
    run_backfill(args.days)
