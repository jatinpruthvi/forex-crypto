"""
Console Dashboard Generator:
Visualizes real-time status of AMATS components, open positions, drawdown level, and regimes.
"""
from datetime import datetime, timezone
import requests
import json


def render_dashboard(brain_api_url: str = "http://127.0.0.1:8000"):
    try:
        status = requests.get(f"{brain_api_url}/status", timeout=5).json()
    except Exception:
        print("❌ Cannot connect to AMATS Brain API.")
        return

    print("=" * 65)
    print("           AMATS TRADING SYSTEM - LIVE DASHBOARD")
    print("=" * 65)
    print(f" API Uptime:        {status.get('api_uptime_hours', 0.0)} hours")
    print(f" System Time:       {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f" ML Model Loaded:   {status.get('ml_model', {}).get('loaded')}")
    print("-" * 65)
    print(" Active Regimes:")
    regimes = status.get("regimes", {})
    if not regimes:
        print("   No symbols monitored yet.")
    for sym, reg in regimes.items():
        print(f"   • {sym:15s} -> {reg}")
    print("-" * 65)
    last_sig = status.get("last_signal", {})
    if last_sig:
        print(f" Last Signal:       {last_sig.get('action')} {last_sig.get('symbol')} (Conf: {last_sig.get('confidence')}%)")
        print(f" Reason:            {last_sig.get('reason')}")
    print("=" * 65)


if __name__ == "__main__":
    render_dashboard()
