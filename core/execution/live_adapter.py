"""
Live Execution Adapter & Order Sanitizer:
1. Exchange Credential Manager (Env-based, fail-fast in live mode)
2. Order Execution State Machine (NEW, PARTIALLY_FILLED, FILLED, CANCELLED)
3. Minimum Notional & Lot-Step Size Sanitizer
4. Heartbeat Watchdog & Feed Health Monitor
5. Event News Lockout Guard Integration
6. Emergency Kill Switch Handler
"""
from typing import Dict, Any, Optional, List
import os
import time
import math
import logging
from datetime import datetime, timezone

logger = logging.getLogger("live_adapter")


class ExchangeCredentialManager:
    """
    Manages API credentials for live exchange connectivity.
    Strictly forbids hardcoded keys. Fails fast in live mode if credentials are missing.
    """
    REQUIRED_VARS = {
        "binance": ["BINANCE_API_KEY", "BINANCE_API_SECRET"],
        "bybit": ["BYBIT_API_KEY", "BYBIT_API_SECRET"],
        "mexc": ["MEXC_API_KEY", "MEXC_API_SECRET"],
        # Hyperliquid is wallet-authenticated: API_KEY = wallet address (0x...),
        # API_SECRET = the signing private key. Use a dedicated API wallet, never
        # your main wallet key. See docs/LIVE_CRYPTO_DEMO_SETUP.md.
        "hyperliquid": ["HYPERLIQUID_API_KEY", "HYPERLIQUID_API_SECRET"],
    }

    @classmethod
    def get_credentials(cls, exchange_id: str, live_mode: bool = False) -> Dict[str, str]:
        exchange_id = exchange_id.lower()
        api_key = os.getenv(f"{exchange_id.upper()}_API_KEY", "")
        api_secret = os.getenv(f"{exchange_id.upper()}_API_SECRET", "")

        if live_mode:
            required = cls.REQUIRED_VARS.get(exchange_id, [])
            missing = [var for var in required if not os.getenv(var)]
            if missing:
                raise ValueError(
                    f"FATAL: Missing required live API credentials for {exchange_id}: {missing}. "
                    f"Refusing to execute live orders without authenticated credentials."
                )

        return {
            "apiKey": api_key,
            "secret": api_secret,
        }

    @classmethod
    def build_ccxt_config(cls, exchange_id: str, live_mode: bool = False) -> Dict[str, Any]:
        """
        Build an exchange-ready CCXT client config from env credentials.
        Hyperliquid uses wallet-based auth (walletAddress + privateKey) while
        CEXes use conventional (apiKey + secret) pairs.
        """
        creds = cls.get_credentials(exchange_id, live_mode=live_mode)
        exchange_id = exchange_id.lower()
        config: Dict[str, Any] = {"enableRateLimit": True}
        if exchange_id == "hyperliquid":
            config["walletAddress"] = creds["apiKey"]
            config["privateKey"] = creds["secret"]
        else:
            config["apiKey"] = creds["apiKey"]
            config["secret"] = creds["secret"]
        return config


class OrderExecutionSanitizer:
    """
    Sanitizes order quantities, notional value, and price increments before dispatching to exchanges.
    Enforces exchange minNotional, minQty, and lot size constraints.
    """
    # Exchange defaults: min_notional ($), min_qty, qty_step, price_tick
    DEFAULT_FILTERS = {
        "BTC/USDT": {"min_notional": 5.0, "min_qty": 0.001, "step_size": 0.0001, "tick_size": 0.1},
        "ETH/USDT": {"min_notional": 5.0, "min_qty": 0.01, "step_size": 0.001, "tick_size": 0.01},
        "SOL/USDT": {"min_notional": 5.0, "min_qty": 0.01, "step_size": 0.01, "tick_size": 0.01},
        "BNB/USDT": {"min_notional": 5.0, "min_qty": 0.01, "step_size": 0.01, "tick_size": 0.01},
        "LINK/USDT": {"min_notional": 5.0, "min_qty": 0.1, "step_size": 0.01, "tick_size": 0.001},
    }

    @classmethod
    def sanitize_order(
        cls,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        exchange_filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Rounds qty and price to exchange step size and tick size.
        Rejects orders failing minimum notional requirement to avoid exchange rejections.
        """
        filters = exchange_filters or cls.DEFAULT_FILTERS.get(symbol, {
            "min_notional": 5.0,
            "min_qty": 0.001,
            "step_size": 0.0001,
            "tick_size": 0.01,
        })

        min_notional = filters.get("min_notional", 5.0)
        min_qty = filters.get("min_qty", 0.001)
        step_size = filters.get("step_size", 0.0001)
        tick_size = filters.get("tick_size", 0.01)

        # Round down quantity to step size
        precision_qty = max(0, int(round(-math.log10(step_size)))) if step_size < 1 else 0
        stepped_qty = math.floor(qty / step_size) * step_size
        stepped_qty = round(stepped_qty, precision_qty)

        # Round price to tick size
        precision_price = max(0, int(round(-math.log10(tick_size)))) if tick_size < 1 else 0
        stepped_price = round(round(price / tick_size) * tick_size, precision_price)

        notional = stepped_qty * stepped_price

        if stepped_qty < min_qty:
            return {
                "valid": False,
                "error": f"Quantity {stepped_qty} below minimum allowed {min_qty} for {symbol}",
                "qty": 0.0,
                "price": stepped_price,
                "notional": 0.0,
            }

        if notional < min_notional:
            return {
                "valid": False,
                "error": f"Notional value ${notional:.2f} below exchange minimum ${min_notional:.2f} for {symbol}",
                "qty": 0.0,
                "price": stepped_price,
                "notional": round(notional, 2),
            }

        return {
            "valid": True,
            "symbol": symbol,
            "side": side.upper(),
            "qty": stepped_qty,
            "price": stepped_price,
            "notional": round(notional, 2),
            "error": None,
        }


class SizingViabilityGate:
    """
    MICRO_ACCOUNT_MODE gate: decides whether a symbol can be traded faithfully
    at the current account equity under real exchange lot-size constraints.

    Rejects any symbol whose ideal ATR-scaled position size, after stepping down
    to the exchange lot step, deviates by more than ``max_error_pct`` — or that
    falls below the exchange minimum quantity / minimum notional. This lets a
    small ($100-$500) account trade only the pairs whose lot granularity can
    honour the 1.5%-risk sizing math, instead of silently oversizing/undersizing.

    Checked stages: initial entry, Tier-1 pyramid add (+1.0x), Tier-2 pyramid
    add (+0.8x) — all three must fit, since the champion strategy pyramids.
    """

    # Exchange-default table (repo baseline, MEXC-style fine lot steps).
    MEXC_LOT_FILTERS = {
        "BTC/USDT":  {"min_notional": 5.0, "min_qty": 0.001, "step_size": 0.0001},
        "ETH/USDT":  {"min_notional": 5.0, "min_qty": 0.01,  "step_size": 0.001},
        "BNB/USDT":  {"min_notional": 5.0, "min_qty": 0.01,  "step_size": 0.01},
        "XRP/USDT":  {"min_notional": 5.0, "min_qty": 0.1,   "step_size": 0.1},
        "ADA/USDT":  {"min_notional": 5.0, "min_qty": 1.0,   "step_size": 1.0},
        "DOGE/USDT": {"min_notional": 5.0, "min_qty": 1.0,   "step_size": 1.0},
        "LTC/USDT":  {"min_notional": 5.0, "min_qty": 0.001, "step_size": 0.001},
        "LINK/USDT": {"min_notional": 5.0, "min_qty": 0.1,   "step_size": 0.01},
    }

    # Bybit linear-perp lot filters (exchange-published, Oct 2026): coarser steps.
    BYBIT_LOT_FILTERS = {
        "BTC/USDT":  {"min_notional": 5.0, "min_qty": 0.001, "step_size": 0.001},
        "ETH/USDT":  {"min_notional": 5.0, "min_qty": 0.01,  "step_size": 0.01},
        "BNB/USDT":  {"min_notional": 5.0, "min_qty": 0.01,  "step_size": 0.01},
        "XRP/USDT":  {"min_notional": 5.0, "min_qty": 0.1,   "step_size": 0.1},
        "ADA/USDT":  {"min_notional": 5.0, "min_qty": 1.0,   "step_size": 1.0},
        "DOGE/USDT": {"min_notional": 5.0, "min_qty": 1.0,   "step_size": 1.0},
        "LTC/USDT":  {"min_notional": 5.0, "min_qty": 0.001, "step_size": 0.001},
        "LINK/USDT": {"min_notional": 5.0, "min_qty": 0.1,   "step_size": 0.1},
    }

    # Hyperliquid on-chain perps (Oct 2026): szDecimals lot steps (BTC 5, ETH 4,
    # BNB 3 decimals) with $10 USDC minimum notional and no true minimum qty
    # beyond one lot. Verify szDecimals live via meta_and_asset_ctxs().
    HYPERLIQUID_LOT_FILTERS = {
        "BTC/USDT":  {"min_notional": 10.0, "min_qty": 0.00001, "step_size": 0.00001},
        "ETH/USDT":  {"min_notional": 10.0, "min_qty": 0.0001,  "step_size": 0.0001},
        "BNB/USDT":  {"min_notional": 10.0, "min_qty": 0.001,   "step_size": 0.001},
        "XRP/USDT":  {"min_notional": 10.0, "min_qty": 0.1,     "step_size": 0.1},
        "ADA/USDT":  {"min_notional": 10.0, "min_qty": 0.1,     "step_size": 0.1},
        "DOGE/USDT": {"min_notional": 10.0, "min_qty": 1.0,     "step_size": 1.0},
        "LTC/USDT":  {"min_notional": 10.0, "min_qty": 0.01,    "step_size": 0.01},
        "LINK/USDT": {"min_notional": 10.0, "min_qty": 0.01,    "step_size": 0.01},
    }

    GENERIC_FILTERS = {"min_notional": 5.0, "min_qty": 0.001, "step_size": 0.0001}

    @classmethod
    def filters_for(cls, symbol: str, venue: str = "mexc", exchange_filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if exchange_filters:
            return exchange_filters
        tables = {
            "mexc": cls.MEXC_LOT_FILTERS,
            "bybit": cls.BYBIT_LOT_FILTERS,
            "hyperliquid": cls.HYPERLIQUID_LOT_FILTERS,
        }
        table = tables.get(venue.lower(), cls.MEXC_LOT_FILTERS)
        return table.get(symbol, cls.GENERIC_FILTERS)

    @classmethod
    def step_qty(cls, qty: float, step_size: float) -> float:
        if step_size <= 0:
            return qty
        precision = max(0, int(round(-math.log10(step_size)))) if step_size < 1 else 0
        return round(math.floor(qty / step_size) * step_size, precision)

    @classmethod
    def qty_rounding_error(cls, ideal_qty: float, step_size: float) -> float:
        """Signed % error introduced by stepping the ideal qty DOWN to the lot step."""
        if ideal_qty <= 0:
            return -100.0
        stepped = cls.step_qty(ideal_qty, step_size)
        return (stepped - ideal_qty) / ideal_qty * 100.0

    @classmethod
    def check(
        cls,
        symbol: str,
        equity: float,
        price: float,
        atr: float,
        risk_pct: float = 1.5,
        leverage: float = 2.0,
        dd_factor: float = 1.0,
        stop_atr_mult: float = 1.5,
        tier_multipliers: tuple = (1.0, 0.8),
        max_error_pct: float = 5.0,
        venue: str = "mexc",
        exchange_filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate whether `symbol` is tradeable at `equity` with <= max_error_pct
        lot-rounding distortion across the entry and both pyramid tiers.
        """
        f = cls.filters_for(symbol, venue, exchange_filters)
        min_qty = f.get("min_qty", 0.001)
        step_size = f.get("step_size", 0.0001)
        min_notional = f.get("min_notional", 5.0)

        stop_dist = max(atr * stop_atr_mult, 1e-4)
        ideal_qty = (equity * (risk_pct / 100.0) * leverage * dd_factor) / stop_dist

        stages = {}
        worst_err = 0.0
        viable = True
        reason = None

        for stage, mult in (("initial", 1.0),) + tuple(
            (f"tier{i}", m) for i, m in enumerate(tier_multipliers, start=1)
        ):
            target = ideal_qty * mult
            stepped = cls.step_qty(target, step_size)
            err = cls.qty_rounding_error(target, step_size)
            notional = stepped * price
            stage_ok = True
            stage_reason = None
            if stepped < min_qty:
                stage_ok = False
                stage_reason = f"{stage}: qty {stepped} below min_qty {min_qty}"
            elif notional < min_notional:
                stage_ok = False
                stage_reason = f"{stage}: notional ${notional:.2f} below min ${min_notional:.2f}"
            elif abs(err) > max_error_pct:
                stage_ok = False
                stage_reason = f"{stage}: lot-rounding error {err:.1f}% exceeds {max_error_pct:.1f}%"
            stages[stage] = {
                "target_qty": target,
                "stepped_qty": stepped,
                "rounding_error_pct": round(err, 2),
                "notional": round(notional, 2),
                "ok": stage_ok,
            }
            worst_err = max(worst_err, abs(err))
            if not stage_ok and viable:
                viable = False
                reason = stage_reason

        return {
            "symbol": symbol,
            "viable": viable,
            "reason": reason,
            "ideal_qty": ideal_qty,
            "stepped_qty": stages["initial"]["stepped_qty"],
            "worst_error_pct": round(worst_err, 2),
            "max_error_pct": max_error_pct,
            "venue": venue,
            "stages": stages,
        }


class LiveOrderStateMachine:
    """
    Tracks order life-cycle:
    NEW -> PARTIALLY_FILLED -> FILLED or CANCELLED / EXPIRED.
    Handles stale partial fills and sweeps residual dust.
    """
    def __init__(self, timeout_seconds: int = 60):
        self.orders: Dict[str, Dict[str, Any]] = {}
        self.timeout_seconds = timeout_seconds

    def register_order(self, order_id: str, symbol: str, side: str, qty: float, price: float) -> Dict[str, Any]:
        entry = {
            "order_id": order_id,
            "symbol": symbol,
            "side": side.upper(),
            "target_qty": qty,
            "filled_qty": 0.0,
            "price": price,
            "status": "NEW",
            "created_at": time.time(),
            "last_updated": time.time(),
        }
        self.orders[order_id] = entry
        return entry

    def update_fill(self, order_id: str, new_filled_qty: float) -> Dict[str, Any]:
        if order_id not in self.orders:
            raise KeyError(f"Order {order_id} not registered")

        ord_info = self.orders[order_id]
        ord_info["filled_qty"] = new_filled_qty
        ord_info["last_updated"] = time.time()

        if ord_info["filled_qty"] >= ord_info["target_qty"]:
            ord_info["status"] = "FILLED"
        elif ord_info["filled_qty"] > 0:
            ord_info["status"] = "PARTIALLY_FILLED"

        return ord_info

    def check_stale_orders(self) -> List[Dict[str, Any]]:
        """Identifies orders that have stayed open / partially filled beyond timeout."""
        now = time.time()
        stale = []
        for oid, ord_info in self.orders.items():
            if ord_info["status"] in ("NEW", "PARTIALLY_FILLED"):
                age = now - ord_info["last_updated"]
                if age > self.timeout_seconds:
                    stale.append(ord_info)
        return stale


class HeartbeatWatchdog:
    """
    Tracks incoming tick / candle timestamps.
    Engages safety trip if exchange feed stalls for longer than max_silence_seconds.
    """
    def __init__(self, max_silence_seconds: float = 30.0):
        self.max_silence_seconds = max_silence_seconds
        self.last_tick_time: Dict[str, float] = {}

    def record_tick(self, feed_name: str) -> None:
        self.last_tick_time[feed_name] = time.time()

    def is_feed_healthy(self, feed_name: str) -> bool:
        last = self.last_tick_time.get(feed_name)
        if last is None:
            return False
        return (time.time() - last) <= self.max_silence_seconds

    def get_feed_status(self) -> Dict[str, Any]:
        now = time.time()
        status = {}
        for feed, t in self.last_tick_time.items():
            age = now - t
            status[feed] = {
                "age_seconds": round(age, 1),
                "healthy": age <= self.max_silence_seconds,
            }
        return status


class CandleTimeAligner:
    """
    Synchronizes multi-asset candle arrival across BTC, SOL, BNB, LINK.
    Buffers incoming bars until all assets for a matching timestamp window arrive,
    preventing race conditions from minor network latency variations.
    """
    def __init__(self, symbols: List[str]):
        self.symbols = set(symbols)
        self.buffers: Dict[str, Dict[str, Any]] = {}

    def add_candle(self, timestamp: str, symbol: str, candle: Dict[str, Any]) -> Optional[Dict[str, Dict[str, Any]]]:
        if timestamp not in self.buffers:
            self.buffers[timestamp] = {}

        self.buffers[timestamp][symbol] = candle

        # If all symbols for this timestamp arrived, release synchronized slice
        if set(self.buffers[timestamp].keys()) == self.symbols:
            complete_slice = self.buffers.pop(timestamp)
            # Prune old unaligned timestamps to prevent memory growth
            if len(self.buffers) > 50:
                oldest_keys = sorted(self.buffers.keys())[:25]
                for k in oldest_keys:
                    self.buffers.pop(k, None)
            return complete_slice

        return None
