"""
Binance Public Futures Data Source:
Fetches Global Long/Short Account Ratio (free proxy for liquidation sentiment).
Zero paid API requirement.
"""
from typing import Dict, Any, Optional
import requests


class BinanceSource:
    BASE_URL = "https://fapi.binance.com"

    def __init__(self):
        pass

    def fetch_long_short_ratio(self, symbol: str = "BTCUSDT", period: str = "1h") -> float:
        """
        Fetches globalLongShortAccountRatio.
        symbol format: BTCUSDT, ETHUSDT
        """
        clean_sym = symbol.replace("/", "").replace(":USDT", "").upper()
        # Binance L/S is supported on major perpetual contracts (BTC, ETH, SOL, BNB, LINK, etc.)
        supported_roots = ["BTC", "ETH", "SOL", "BNB", "LINK", "XRP", "ADA", "AVAX", "DOGE"]
        matched = next((root for root in supported_roots if root in clean_sym), None)
        if matched:
            binance_sym = f"{matched}USDT"
        else:
            binance_sym = f"{clean_sym}USDT" if not clean_sym.endswith("USDT") else clean_sym

        url = f"{self.BASE_URL}/futures/data/globalLongShortAccountRatio"
        params = {"symbol": binance_sym, "period": period, "limit": 1}

        try:
            resp = requests.get(url, params=params, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data and len(data) > 0:
                    return float(data[0].get("longShortRatio", 1.0))
        except Exception:
            pass

        return 1.0
