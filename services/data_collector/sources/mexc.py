"""
MEXC Public Market Data Source:
Fetches Funding Rate, Tickers, and Contract Metrics via CCXT/Public REST.
Zero paid API requirement. Supports both MEXC spot and futures (swap).
"""
from typing import Dict, Any, Optional
import requests
import ccxt


class MEXCSource:
    def __init__(self, testnet: bool = False):
        self.testnet = testnet
        self.exchange = ccxt.mexc({
            "enableRateLimit": True,
            "options": {"defaultType": "swap"},
        })
        if testnet and "test" in getattr(self.exchange, "urls", {}) and self.exchange.urls.get("test"):
            try:
                self.exchange.set_sandbox_mode(True)
            except Exception:
                pass

    def fetch_market_signals(self, symbol: str = "BTC/USDT:USDT") -> Dict[str, Any]:
        """
        Fetches funding rate, ticker details, and contract open interest for symbol on MEXC.
        """
        funding_rate = 0.0
        open_interest = 0.0
        taker_buy = 0.0
        taker_sell = 0.0
        taker_ratio = 1.0

        clean_symbol = symbol.replace(":USDT", "").replace("/", "_")

        # 1. Fetch Ticker via CCXT or REST
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            funding_rate = float(ticker.get("info", {}).get("fundingRate", 0.0) or 0.0)
            open_interest = float(ticker.get("info", {}).get("holdVol", 0.0) or ticker.get("info", {}).get("openInterest", 0.0) or 0.0)
        except Exception:
            # REST Fallback for MEXC Contract API
            url = f"https://contract.mexc.com/api/v1/contract/ticker?symbol={clean_symbol}"
            try:
                res = requests.get(url, timeout=5).json()
                data = res.get("data", {})
                funding_rate = float(data.get("fundingRate", 0.0) or 0.0)
                open_interest = float(data.get("holdVol", 0.0) or 0.0)
            except Exception:
                pass

        # 2. Direct MEXC Contract Funding Rate endpoint fallback
        if funding_rate == 0.0:
            try:
                url = f"https://contract.mexc.com/api/v1/contract/funding_rate/{clean_symbol}"
                res = requests.get(url, timeout=5).json()
                data = res.get("data", {})
                funding_rate = float(data.get("fundingRate", 0.0) or 0.0)
            except Exception:
                pass

        return {
            "symbol": symbol,
            "exchange": "mexc",
            "funding_rate": funding_rate,
            "open_interest": open_interest,
            "taker_ratio": taker_ratio,
            "taker_buy_volume": taker_buy,
            "taker_sell_volume": taker_sell,
        }
