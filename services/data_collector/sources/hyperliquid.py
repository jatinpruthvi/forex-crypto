"""
Hyperliquid Public Market Data Source:
Fetches Ticker, Funding Rate, and H4 OHLCV candles for the crypto universe via
CCXT (public endpoints — zero API key required for market data).
Also provides the canonical engine<->Hyperliquid symbol mapping (USDT -> USDC).
"""
import logging
from typing import Dict, Any, List, Optional
import ccxt

# Hyperliquid perps are USDC-margined: engine symbols ("BTC/USDT") map to
# CCXT linear-swap symbols ("BTC/USDC:USDC").
SYMBOL_MAP = {
    "BTC/USDT": "BTC/USDC:USDC",
    "ETH/USDT": "ETH/USDC:USDC",
    "BNB/USDT": "BNB/USDC:USDC",
    "XRP/USDT": "XRP/USDC:USDC",
    "ADA/USDT": "ADA/USDC:USDC",
    "DOGE/USDT": "DOGE/USDC:USDC",
    "LTC/USDT": "LTC/USDC:USDC",
    "LINK/USDT": "LINK/USDC:USDC",
}


def to_hyperliquid_symbol(symbol: str) -> str:
    """Map an engine symbol (BTC/USDT) to its Hyperliquid CCXT symbol."""
    return SYMBOL_MAP.get(symbol, symbol.replace("/USDT", "/USDC:USDC"))


logger = logging.getLogger(__name__)


class HyperliquidSource:
    def __init__(self, testnet: bool = False, client: Optional[Any] = None):
        self.testnet = testnet
        self.exchange = client if client is not None else ccxt.hyperliquid({
            "enableRateLimit": True,
        })
        if client is None and testnet:
            self.exchange.set_sandbox_mode(True)

    def fetch_market_signals(self, symbol: str = "BTC/USDT") -> Dict[str, Any]:
        """
        Fetches funding rate, open interest, and last price for symbol.
        Network failures degrade gracefully to zero-valued signals (matching the
        BybitSource/BinanceSource contract used by the data collector).
        """
        hl_symbol = to_hyperliquid_symbol(symbol)
        funding_rate = 0.0
        open_interest = 0.0
        last_price = 0.0

        fetch_ok = True
        try:
            ticker = self.exchange.fetch_ticker(hl_symbol)
            last_price = float(ticker.get("last") or 0.0)
            info = ticker.get("info") or {}
            oi_raw = info.get("openInterest")
            open_interest = float(oi_raw) if oi_raw is not None else 0.0
        except Exception:
            fetch_ok = False
            logger.warning("HyperliquidSource: fetch_ticker failed for %s", hl_symbol, exc_info=True)

        try:
            fr = self.exchange.fetch_funding_rate(hl_symbol)
            funding_rate = float(fr.get("fundingRate") or 0.0)
        except Exception:
            fetch_ok = False
            logger.warning("HyperliquidSource: fetch_funding_rate failed for %s", hl_symbol, exc_info=True)

        return {
            "symbol": symbol,
            "last_price": last_price,
            "funding_rate": funding_rate,
            "open_interest": open_interest,
            "taker_ratio": 1.0,
            # False -> values above may be silent zeros; do NOT treat as live data.
            "fetch_ok": fetch_ok,
        }

    def fetch_h4_candles(self, symbol: str = "BTC/USDT", limit: int = 300) -> List[Dict[str, Any]]:
        """
        Fetch H4 OHLCV candles as engine-ready dicts:
        [{timestamp, open, high, low, close, volume}, ...] (oldest first).
        """
        hl_symbol = to_hyperliquid_symbol(symbol)
        raw = self.exchange.fetch_ohlcv(hl_symbol, timeframe="4h", limit=limit)
        return [
            {
                "timestamp": row[0],
                "open": row[1],
                "high": row[2],
                "low": row[3],
                "close": row[4],
                "volume": row[5],
            }
            for row in raw
        ]
