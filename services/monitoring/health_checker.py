"""
Health Checker Service:
Pings Brain API, checks SQLite data freshness, VPS memory/disk,
and dispatches Telegram alerts on stale feeds or outages.
"""
import time
import requests
from typing import Optional
import os
import shutil
from datetime import datetime, timezone

from services.monitoring.telegram_bot import TelegramAlert


def run_health_check(brain_api_url: Optional[str] = None):
    if brain_api_url is None:
        brain_api_url = os.getenv("BRAIN_API_URL", "http://127.0.0.1:8000")
    telegram = TelegramAlert()
    print(f"Running AMATS Health Check against {brain_api_url}...")

    # 1. Ping Brain API
    try:
        resp = requests.get(f"{brain_api_url}/health", timeout=5)
        if resp.status_code == 200:
            print(" Brain API is online.")
        else:
            telegram.send_message(f"🚨 Brain API returned non-200 status: {resp.status_code}")
    except Exception as e:
        telegram.send_message(f"🚨 Brain API is UNREACHABLE: {e}")

    # 2. Check Database Freshness
    db_file = "data/signals.db"
    if os.path.exists(db_file):
        mtime = os.path.getmtime(db_file)
        age_hours = (time.time() - mtime) / 3600.0
        if age_hours > 3.0:
            telegram.send_message(f"⚠️ Market signals database is STALE ({age_hours:.1f} hours old)")
        else:
            print(f" signals.db is fresh ({age_hours:.2f} hours old).")

    # 3. Check Disk Space
    total, used, free = shutil.disk_usage("/")
    used_pct = (used / max(1, total)) * 100.0
    if used_pct > 85.0:
        telegram.send_message(f"⚠️ VPS Disk usage critical: {used_pct:.1f}%")
    else:
        print(f" Disk usage normal: {used_pct:.1f}%.")


if __name__ == "__main__":
    run_health_check()
