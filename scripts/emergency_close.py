#!/usr/bin/env python3
"""
Manual Emergency Close Script:
Calls Brain API /close_all endpoint and sends Telegram kill notification.
"""
import requests
import sys

BRAIN_API = "http://127.0.0.1:8000"


def trigger_emergency_close():
    print(f"Triggering manual emergency close on {BRAIN_API}...")
    try:
        resp = requests.post(f"{BRAIN_API}/close_all", timeout=5)
        print("Response:", resp.status_code, resp.json())
    except Exception as e:
        print(f"Error contacting Brain API: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    trigger_emergency_close()
