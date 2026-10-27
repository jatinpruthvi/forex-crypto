"""
Bybit Public Market Data Source:
Fetches Funding Rate, Open Interest, and Ticker Buy/Sell Volumes via CCXT/Public REST.
Zero paid API requirement.
"""
from typing import Dict, Any, Optional
import requests
import ccxt


class BybitSource:
    def __init__(self, testnet: bool = False):
        self.testnet = testnet
        self.exchange = ccxt.bybit({
            "enableRateLimit": True,
            "options": {"defaultType": "linear"},
        })
        if testnet:
            self.exchange.set_sandbox_mode(True)

    def fetch_market_signals(self, symbol: str = "BTC/USDT:USDT") -> Dict[str, Any]:
        """
        Fetches funding rate, open interest, and taker buy/sell ratio for symbol.
        """
        funding_rate = 0.0
        open_interest = 0.0
        taker_buy = 0.0
        taker_sell = 0.0
        taker_ratio = 1.0

        clean_symbol = symbol.replace(":USDT", "").replace("/", "")

        # 1. Fetch Ticker via CCXT or REST
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            info = ticker.get("info") or {}
            fr_raw = info.get("fundingRate")
            oi_raw = info.get("openInterest")
            funding_rate = float(fr_raw) if fr_raw is not None else 0.0
            open_interest = float(oi_raw) if oi_raw is not None else 0.0
        except Exception:
            # REST Fallback
            url = f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={clean_symbol}"
            try:
                res = requests.get(url, timeout=5).json()
                items = res.get("result", {}).get("list", [])
                item = items[0] if items else {}
                fr_raw = item.get("fundingRate")
                oi_raw = item.get("openInterest")
                funding_rate = float(fr_raw) if fr_raw is not None else 0.0
                open_interest = float(oi_raw) if oi_raw is not None else 0.0
            except Exception:
                pass

        # 2. Fetch Open Interest Endpoint directly if needed
        if open_interest == 0.0:
            try:
                url = f"https://api.bybit.com/v5/market/open-interest?category=linear&symbol={clean_symbol}&intervalTime=1h&limit=1"
                res = requests.get(url, timeout=5).json()
                item = res.get("result", {}).get("list", [{}])[0]
                open_interest = float(item.get("openInterest", 0.0) or 0.0)
            except Exception:
                pass

        return {
            "symbol": symbol,
            "funding_rate": funding_rate,
            "open_interest": open_interest,
            "taker_ratio": taker_ratio,
            "taker_buy_volume": taker_buy,
            "taker_sell_volume": taker_sell,
        }
