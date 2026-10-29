"""
Hyperliquid Live Execution Adapter:
Routes Dual-Slot engine signals to real Hyperliquid perp orders via CCXT, with
full MICRO_ACCOUNT_MODE discipline:

1. SizingViabilityGate   -> auto-reject pairs whose lot step distorts risk > 5%
2. OrderExecutionSanitizer -> floor qty/price to exchange lot & tick, enforce $10 min
3. LiveOrderStateMachine -> track NEW -> FILLED / CANCELLED lifecycles
4. ExchangeCredentialManager -> wallet-based auth (walletAddress + privateKey)

DANGER ZONE: live_mode=True places REAL on-chain orders with REAL USDC.
Everything defaults to dry_run=True (simulated fills, no network writes).
"""
from typing import Dict, Any, Optional
import logging
import time

from core.execution.live_adapter import (
    ExchangeCredentialManager,
    OrderExecutionSanitizer,
    LiveOrderStateMachine,
    SizingViabilityGate,
)
from services.data_collector.sources.hyperliquid import to_hyperliquid_symbol

logger = logging.getLogger("hyperliquid_executor")


class HyperliquidLiveExecutor:
    """
    Turn-key executor for the champion Dual-Slot strategy on Hyperliquid.

    Typical $25 live-test flow:
        ex = HyperliquidLiveExecutor(dry_run=True)          # rehearsal
        plan = ex.plan_entry("DOGE/USDT", "buy", equity=25, price=0.22, atr=0.0077)
        ex.submit_entry(plan)                                # simulated fill
        ...
        ex = HyperliquidLiveExecutor(dry_run=False, testnet=True)  # testnet
        ex = HyperliquidLiveExecutor(dry_run=False)                # LIVE $25
    """

    def __init__(
        self,
        dry_run: bool = True,
        testnet: bool = False,
        max_sizing_error_pct: float = 5.0,
        client: Optional[Any] = None,
    ):
        self.dry_run = dry_run
        self.testnet = testnet
        self.max_sizing_error_pct = max_sizing_error_pct
        self.order_log: list = []
        self.state_machine = LiveOrderStateMachine(timeout_seconds=60)

        if client is not None:
            self.client = client
        else:
            import ccxt
            config = ExchangeCredentialManager.build_ccxt_config(
                "hyperliquid", live_mode=not dry_run
            )
            self.client = ccxt.hyperliquid(config)
            if testnet:
                self.client.set_sandbox_mode(True)

    # ------------------------------------------------------------------
    # Sizing & planning (pure — fully testable offline)
    # ------------------------------------------------------------------
    def plan_entry(
        self,
        symbol: str,
        side: str,
        equity: float,
        price: float,
        atr: float,
        risk_pct: float = 1.5,
        leverage: float = 2.0,
        dd_factor: float = 1.0,
        stop_atr_mult: float = 1.5,
    ) -> Dict[str, Any]:
        """
        Compute a live-ready entry plan for `symbol` at the current equity.
        Runs the MICRO_ACCOUNT_MODE viability gate first: if the Hyperliquid lot
        step would distort the 1.5%-risk sizing by more than max_sizing_error_pct
        (or the order falls below the $10 min notional), the plan is REJECTED and
        no order should be sent.
        """
        gate = SizingViabilityGate.check(
            symbol,
            equity=equity,
            price=price,
            atr=atr,
            risk_pct=risk_pct,
            leverage=leverage,
            dd_factor=dd_factor,
            stop_atr_mult=stop_atr_mult,
            max_error_pct=self.max_sizing_error_pct,
            venue="hyperliquid",
        )
        if not gate["viable"]:
            logger.info("PLAN REJECTED %s: %s", symbol, gate["reason"])
            return {"accepted": False, "symbol": symbol, "reason": gate["reason"], "gate": gate}

        filters = SizingViabilityGate.filters_for(symbol, "hyperliquid")
        sanitized = OrderExecutionSanitizer.sanitize_order(
            symbol, side, gate["stepped_qty"], price,
            exchange_filters={**filters, "tick_size": 0.01},
        )
        if not sanitized["valid"]:
            return {"accepted": False, "symbol": symbol, "reason": sanitized["error"], "gate": gate}

        stop_dist = atr * stop_atr_mult
        if side.lower() == "buy":
            stop_price = price - stop_dist
            tp1_price = price + (atr * 1.8)
        else:
            stop_price = price + stop_dist
            tp1_price = price - (atr * 1.8)

        return {
            "accepted": True,
            "symbol": symbol,
            "hl_symbol": to_hyperliquid_symbol(symbol),
            "side": side.lower(),
            "qty": sanitized["qty"],
            "limit_price": sanitized["price"],
            "notional": sanitized["notional"],
            "stop_price": round(stop_dist and stop_price, 6),
            "tp1_price": round(tp1_price, 6),
            "atr": atr,
            "gate": gate,
        }

    # ------------------------------------------------------------------
    # Order routing
    # ------------------------------------------------------------------
    def submit_entry(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """Submit a post-only limit entry (maker fee) from an accepted plan."""
        if not plan.get("accepted"):
            return {"status": "REJECTED", "reason": plan.get("reason")}
        if self.dry_run:
            order = {
                "id": f"DRY-{int(time.time() * 1000)}",
                "status": "DRY_FILLED",
                "symbol": plan["hl_symbol"],
                "side": plan["side"],
                "qty": plan["qty"],
                "price": plan["limit_price"],
            }
            self.order_log.append({**order, "dry_run": True})
            self.state_machine.register_order(order["id"], plan["symbol"], plan["side"].upper(), plan["qty"], plan["limit_price"])
            logger.info("DRY-RUN entry %s %s x %s @ %s", plan["side"], plan["symbol"], plan["qty"], plan["limit_price"])
            return order

        raw = self.client.create_order(
            plan["hl_symbol"], "limit", plan["side"], plan["qty"], plan["limit_price"],
            {"timeInForce": "Gtc", "postOnly": True},
        )
        order = {"id": raw.get("id"), "status": raw.get("status", "NEW"), "raw": raw}
        self.order_log.append(order)
        self.state_machine.register_order(order["id"], plan["symbol"], plan["side"].upper(), plan["qty"], plan["limit_price"])
        return order

    def place_stop(self, symbol: str, side: str, qty: float, trigger_price: float) -> Dict[str, Any]:
        """
        Place a reduce-only trigger stop (Hyperliquid tpsl 'sl' order).
        `side` is the CLOSING side (sell to close a long).
        """
        close_side = "sell" if side.lower() in ("buy", "long") else "buy"
        if self.dry_run:
            order = {"id": f"DRY-SL-{int(time.time() * 1000)}", "status": "DRY_PLACED",
                     "symbol": symbol, "side": close_side, "qty": qty, "trigger": trigger_price}
            self.order_log.append({**order, "dry_run": True})
            return order
        raw = self.client.create_order(
            to_hyperliquid_symbol(symbol), "market", close_side, qty, None,
            {"triggerPrice": trigger_price, "reduceOnly": True, "tpsl": "sl"},
        )
        order = {"id": raw.get("id"), "status": raw.get("status", "NEW"), "raw": raw}
        self.order_log.append(order)
        return order

    def close_position(self, symbol: str, side: str, qty: float, price: Optional[float] = None) -> Dict[str, Any]:
        """Reduce-only market close of `qty` on `symbol`."""
        close_side = "sell" if side.lower() in ("buy", "long") else "buy"
        if self.dry_run:
            order = {"id": f"DRY-CL-{int(time.time() * 1000)}", "status": "DRY_FILLED",
                     "symbol": symbol, "side": close_side, "qty": qty, "price": price}
            self.order_log.append({**order, "dry_run": True})
            return order
        raw = self.client.create_order(
            to_hyperliquid_symbol(symbol), "market", close_side, qty, price or None,
            {"reduceOnly": True},
        )
        order = {"id": raw.get("id"), "status": raw.get("status", "NEW"), "raw": raw}
        self.order_log.append(order)
        return order

    # ------------------------------------------------------------------
    # Account state
    # ------------------------------------------------------------------
    def fetch_equity(self) -> float:
        """Total USDC collateral (margin equity) on the Hyperliquid account."""
        if self.dry_run:
            return 0.0
        balance = self.client.fetch_balance()
        usdc = balance.get("USDC") or {}
        return float(usdc.get("total") or 0.0)

    def fetch_h4(self, symbol: str, limit: int = 300) -> list:
        """H4 OHLCV candles straight from the venue (signal generation)."""
        return self.client.fetch_ohlcv(to_hyperliquid_symbol(symbol), timeframe="4h", limit=limit)
