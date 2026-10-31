#!/usr/bin/env python3
"""
AMATS Automated Storage & Log Maintenance:
1. Prunes records older than retention_days (default 90) from SQLite signals.db.
2. Runs VACUUM to reclaim filesystem blocks and optimize query indices.
3. Truncates/rotates log files exceeding max_log_mb (default 25 MB).
"""
import sqlite3
import os
import glob
import logging
from datetime import datetime, timezone, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [maintenance] %(message)s")
logger = logging.getLogger("maintenance")


def prune_sqlite_database(db_path: str = "data/signals.db", retention_days: int = 90):
    if not os.path.exists(db_path):
        logger.info(f"Database {db_path} does not exist yet. Skipping DB prune.")
        return

    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    logger.info(f"Pruning records older than {cutoff_date} from {db_path}...")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute("DELETE FROM market_signals WHERE timestamp < ?", (cutoff_date,))
        deleted_signals = cursor.rowcount
        cursor.execute("DELETE FROM events WHERE event_time < ?", (cutoff_date,))
        deleted_events = cursor.rowcount
        cursor.execute("DELETE FROM trade_log WHERE timestamp < ?", (cutoff_date,))
        deleted_trades = cursor.rowcount

        conn.commit()
        logger.info(f"Deleted rows: {deleted_signals} signals, {deleted_events} events, {deleted_trades} trade logs.")

        # Reclaim unused pages
        logger.info("Running SQLite VACUUM...")
        cursor.execute("VACUUM;")
        conn.commit()
        logger.info("Database VACUUM complete.")
    except Exception as e:
        logger.error(f"Error during SQLite pruning: {e}")
    finally:
        conn.close()


def rotate_oversized_logs(log_dir: str = "logs", max_log_mb: float = 25.0):
    os.makedirs(log_dir, exist_ok=True)
    log_files = glob.glob(os.path.join(log_dir, "*.log"))
    max_bytes = max_log_mb * 1024 * 1024

    for log_path in log_files:
        size = os.path.getsize(log_path)
        if size > max_bytes:
            logger.info(f"Rotating oversized log: {log_path} ({size / (1024*1024):.1f} MB)...")
            rotated_path = f"{log_path}.old"
            if os.path.exists(rotated_path):
                os.remove(rotated_path)
            os.rename(log_path, rotated_path)
            # Create fresh empty log
            open(log_path, "w").close()
            logger.info(f"Rotated to {rotated_path} and reset active log.")


if __name__ == "__main__":
    prune_sqlite_database("data/signals.db", retention_days=90)
    rotate_oversized_logs("logs", max_log_mb=25.0)
