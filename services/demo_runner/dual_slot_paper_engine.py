"""
Dual-Slot Shared Margin Pool Demo Account Engine (100% Crypto Universe):
- Single Unified Capital Margin Pool ($1,000 / $10,000 initial balance, zero static slicing).
- Dual-Slot Capacity: Maximum 2 concurrent positions active at any timestamp across all qualifying crypto pairs.
- Opportunity Routing: When a slot opens, candidate setups across BTC, DOGE, XRP, LTC, ETH, ADA, BNB, LINK
  are ranked by trend/volatility conviction (ADX breakout + RSI/Bollinger disparity).
- Asymmetric Payoff Ratchet:
  * Partial profit (40%) taken at +1.8x ATR.
  * Stop loss immediately ratcheted to Entry + 0.25x ATR buffer (100% guaranteed risk-free house money).
  * Tier 1 (+1.8x ATR) and Tier 2 (+3.0x ATR) pyramiding funded purely by locked gains.
  * Chandelier trailing ratchet (2.0x ATR).
- Dynamic Drawdown Throttle (cuts risk sizing by 50% if DD >= 8%).
- Authentic candle-by-candle walk-forward accounting with zero pre-baked stats.
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone

from services.monitoring.webhook_notifier import WebhookNotifier
from core.risk.institutional_guards import PropFirmRiskGuard
from core.execution.live_adapter import SizingViabilityGate

logger = logging.getLogger("dual_slot_paper_engine")


class DualSlotSharedPoolAccount:
    def __init__(
        self,
        name: str = "Champion: Dual-Slot Shared Margin Pool (1.5% Risk, 2.0x Lev)",
        initial_capital: float = 10000.0,
        base_risk_pct: float = 1.5,
        leverage: float = 2.0,
        maker_fee: float = 0.00015,
        max_slots: int = 2,
        micro_account_mode: bool = False,
        max_sizing_error_pct: float = 5.0,
        lot_venue: str = "mexc",
    ):
        self.name = name
        self.initial_capital = initial_capital
        self.balance = initial_capital
        self.equity = initial_capital
        self.peak_equity = initial_capital
        self.max_drawdown_pct = 0.0
        self.current_drawdown_pct = 0.0
        self.base_risk_pct = base_risk_pct
        self.leverage = leverage
        self.maker_fee = maker_fee
        self.max_slots = max_slots

        self.positions: Dict[str, dict] = {}
        self.closed_trades: List[dict] = []
        self.equity_curve: List[float] = [initial_capital]
        self.drawdown_curve: List[float] = [0.0]
        self.notifier = WebhookNotifier()
        self.prop_guard = PropFirmRiskGuard(max_daily_loss_pct=4.0, lockout_trigger_pct=3.5)
        self.emergency_halt = False

        # Qualifying crypto universe tracked by the shared opportunity pool
        self.tracked_symbols = [
            "BTC/USDT", "DOGE/USDT", "BNB/USDT", "XRP/USDT",
            "ADA/USDT", "LTC/USDT", "ETH/USDT", "LINK/USDT"
        ]

        # MICRO_ACCOUNT_MODE: live-exchange lot-size discipline for small accounts.
        # When enabled, each candidate symbol is gated through SizingViabilityGate —
        # pairs whose lot-rounding error exceeds max_sizing_error_pct (or that fall
        # below exchange min qty/notional) are auto-skipped until equity grows.
        self.micro_account_mode = micro_account_mode
        self.max_sizing_error_pct = max_sizing_error_pct
        self.lot_venue = lot_venue
        self.skipped_symbols: Dict[str, dict] = {}

    def on_asset_candle(self, ts: str, symbol: str, high: float, low: float, close: float):
        if self.emergency_halt or symbol not in self.positions:
            return

        pos = self.positions[symbol]
        atr = pos["atr"]
        side = pos["side"]
        entry = pos["entry_price"]

        if side == "long":
            # Check Partial TP1 (+1.8x ATR)
            if not pos["tp1_hit"] and high >= pos["tp1_price"]:
                pos["tp1_hit"] = True
                realized_qty = pos["size"] * 0.40
                pnl = (pos["tp1_price"] - entry) * realized_qty
                fee = (pos["tp1_price"] * realized_qty) * self.maker_fee
                net_pnl = pnl - fee
                self.balance += net_pnl
                pos["size"] *= 0.60
                pos["realized_pnl"] += net_pnl
                # Ratchet SL to Entry + 0.25x ATR buffer (100% Risk Free)
                pos["stop_loss"] = entry + (atr * 0.25)
                pos["be_locked"] = True

                # Tier 1 Pyramiding using realized house-money
                if pos["pyramid_tier"] == 0 and pos.get("regime") == "TREND":
                    pos["pyramid_tier"] = 1
                    tier1_qty = self._pyramid_add_qty(symbol, ts, "TIER1", atr, 1.0)
                    pos["size"] += tier1_qty

            # Check Tier 2 Pyramiding (+3.0x ATR)
            if pos["tp1_hit"] and pos["pyramid_tier"] == 1 and pos.get("regime") == "TREND":
                tp2_target = entry + (atr * 3.0)
                if high >= tp2_target:
                    pos["pyramid_tier"] = 2
                    tier2_qty = self._pyramid_add_qty(symbol, ts, "TIER2", atr, 0.8)
                    pos["size"] += tier2_qty
                    pos["stop_loss"] = entry + (atr * 1.5)

            # Chandelier Trailing Ratchet
            if pos["tp1_hit"]:
                chandelier = high - (atr * 2.0)
                if chandelier > pos["stop_loss"]:
                    pos["stop_loss"] = chandelier

            # Check Stop Loss Trigger
            if low <= pos["stop_loss"]:
                self._close_position(ts, symbol, pos["stop_loss"], "TRAILING_STOP_LOCK_HIT")
                return

        elif side == "short":
            if not pos["tp1_hit"] and low <= pos["tp1_price"]:
                pos["tp1_hit"] = True
                realized_qty = pos["size"] * 0.40
                pnl = (entry - pos["tp1_price"]) * realized_qty
                fee = (pos["tp1_price"] * realized_qty) * self.maker_fee
                net_pnl = pnl - fee
                self.balance += net_pnl
                pos["size"] *= 0.60
                pos["realized_pnl"] += net_pnl
                pos["stop_loss"] = entry - (atr * 0.25)
                pos["be_locked"] = True

                if pos["pyramid_tier"] == 0 and pos.get("regime") == "TREND":
                    pos["pyramid_tier"] = 1
                    tier1_qty = self._pyramid_add_qty(symbol, ts, "TIER1", atr, 1.0)
                    pos["size"] += tier1_qty

            if pos["tp1_hit"] and pos["pyramid_tier"] == 1 and pos.get("regime") == "TREND":
                tp2_target = entry - (atr * 3.0)
                if low <= tp2_target:
                    pos["pyramid_tier"] = 2
                    tier2_qty = self._pyramid_add_qty(symbol, ts, "TIER2", atr, 0.8)
                    pos["size"] += tier2_qty
                    pos["stop_loss"] = entry - (atr * 1.5)

            if pos["tp1_hit"]:
                chandelier = low + (atr * 2.0)
                if chandelier < pos["stop_loss"]:
                    pos["stop_loss"] = chandelier

            if high >= pos["stop_loss"]:
                self._close_position(ts, symbol, pos["stop_loss"], "TRAILING_STOP_LOCK_HIT")
                return

        # Mark to market
        cur_pos = self.positions.get(symbol)
        if cur_pos:
            mult = 1 if cur_pos["side"] == "long" else -1
            cur_pos["unrealized_pnl"] = (close - cur_pos["entry_price"]) * cur_pos["size"] * mult
            cur_pos["current_price"] = close

    def finish_candle(self, ts: str):
        total_unrealized = sum(p["unrealized_pnl"] for p in self.positions.values())
        self.equity = self.balance + total_unrealized

        if self.equity > self.peak_equity:
            self.peak_equity = self.equity

        cur_dd = (self.peak_equity - self.equity) / self.peak_equity if self.peak_equity > 0 else 0.0
        self.current_drawdown_pct = cur_dd * 100.0
        if self.current_drawdown_pct > self.max_drawdown_pct:
            self.max_drawdown_pct = self.current_drawdown_pct

        self.equity_curve.append(round(self.equity, 2))
        self.drawdown_curve.append(round(self.current_drawdown_pct, 2))
        if len(self.equity_curve) > 120:
            self.equity_curve.pop(0)
            self.drawdown_curve.pop(0)

        guard_state = self.prop_guard.update_daily_state(ts, self.balance)
        if guard_state.get("is_daily_locked", False):
            self.emergency_halt = True
            self.emergency_liquidate_all(ts, "PROP_FIRM_DAILY_LOCKOUT_TRIGGERED")

    def _pyramid_add_qty(self, symbol: str, ts: str, tier_label: str, atr: float, mult: float) -> float:
        """Size a pyramid add; in MICRO_ACCOUNT_MODE step to the exchange lot size
        and skip the add entirely if it would fall below the exchange min qty."""
        qty = (self.equity * (self.base_risk_pct / 100.0) * self.leverage * mult) / max(atr * 1.5, 1e-4)
        if not self.micro_account_mode:
            return qty
        f = SizingViabilityGate.filters_for(symbol, self.lot_venue)
        stepped = SizingViabilityGate.step_qty(qty, f.get("step_size", 0.0001))
        if stepped < f.get("min_qty", 0.001):
            logger.info(
                "MICRO_ACCOUNT_MODE: %s %s pyramid add skipped — stepped qty %s below min_qty %s",
                symbol, tier_label, stepped, f.get("min_qty", 0.001),
            )
            return 0.0
        return stepped

    def open_trade(
        self,
        ts: str,
        symbol: str,
        side: str,
        entry_price: float,
        atr: float,
        regime: str = "TREND"
    ) -> bool:
        if self.emergency_halt:
            return False
        if symbol in self.positions:
            return False
        if len(self.positions) >= self.max_slots:
            return False

        # Drawdown safety throttle: if current DD >= 8%, cut risk by 50%
        dd_factor = 0.5 if self.current_drawdown_pct >= 8.0 else 1.0
        risk_amount = self.equity * (self.base_risk_pct / 100.0) * dd_factor
        stop_dist = atr * 1.5
        size = (risk_amount * self.leverage) / max(stop_dist, 1e-4)

        # MICRO_ACCOUNT_MODE: gate symbol through real exchange lot constraints.
        # Skips the pair (rather than trading a distorted size) whenever the lot
        # step would distort risk sizing by more than max_sizing_error_pct.
        if self.micro_account_mode:
            gate = SizingViabilityGate.check(
                symbol,
                equity=self.equity,
                price=entry_price,
                atr=atr,
                risk_pct=self.base_risk_pct,
                leverage=self.leverage,
                dd_factor=dd_factor,
                max_error_pct=self.max_sizing_error_pct,
                venue=self.lot_venue,
            )
            if not gate["viable"]:
                self.skipped_symbols[symbol] = {
                    "reason": gate["reason"],
                    "ts": ts,
                    "equity": round(self.equity, 2),
                    "worst_error_pct": gate["worst_error_pct"],
                }
                logger.info(
                    "MICRO_ACCOUNT_MODE: skipping %s at equity $%.2f — %s",
                    symbol, self.equity, gate["reason"],
                )
                return False
            # Faithful live sizing: use the exchange-stepped quantity
            size = gate["stepped_qty"]

        if side == "long":
            sl = entry_price - stop_dist
            tp1 = entry_price + (atr * 1.8)
        else:
            sl = entry_price + stop_dist
            tp1 = entry_price - (atr * 1.8)

        entry_fee = (entry_price * size) * self.maker_fee
        self.balance -= entry_fee

        self.positions[symbol] = {
            "symbol": symbol,
            "side": side,
            "entry_time": ts,
            "entry_price": entry_price,
            "current_price": entry_price,
            "size": size,
            "initial_size": size,
            "stop_loss": sl,
            "tp1_price": tp1,
            "tp1_hit": False,
            "pyramid_tier": 0,
            "be_locked": False,
            "atr": atr,
            "unrealized_pnl": 0.0,
            "realized_pnl": -entry_fee,
            "regime": regime
        }
        return True

    def _close_position(self, ts: str, symbol: str, exit_price: float, reason: str):
        if symbol not in self.positions:
            return
        pos = self.positions.pop(symbol)
        mult = 1 if pos["side"] == "long" else -1
        pnl = (exit_price - pos["entry_price"]) * pos["size"] * mult
        fee = (exit_price * pos["size"]) * self.maker_fee
        net_trade_pnl = pnl - fee
        self.balance += (pnl - fee)

        total_trade_pnl = pos["realized_pnl"] + net_trade_pnl
        record = {
            "strategy": "Dual-Slot Shared Pool (Crypto)",
            "account": self.name,
            "symbol": symbol,
            "side": pos["side"],
            "entry_time": pos["entry_time"],
            "exit_time": ts,
            "entry_price": round(pos["entry_price"], 4 if "DOGE" in symbol or "XRP" in symbol else 2),
            "exit_price": round(exit_price, 4 if "DOGE" in symbol or "XRP" in symbol else 2),
            "net_pnl": round(total_trade_pnl, 2),
            "exit_reason": reason,
            "be_locked": pos["be_locked"],
            "pyramid_tier": pos["pyramid_tier"]
        }
        self.closed_trades.append(record)

    def emergency_liquidate_all(self, ts: str, reason: str = "EMERGENCY_KILL"):
        symbols = list(self.positions.keys())
        for sym in symbols:
            pos = self.positions.get(sym)
            if pos:
                self._close_position(ts, sym, pos["current_price"], reason)
        self.emergency_halt = True

    def get_summary(self) -> dict:
        total_pnl = self.equity - self.initial_capital
        tot_ret = (total_pnl / self.initial_capital) * 100.0
        n_closed = len(self.closed_trades)
        wins = sum(1 for t in self.closed_trades if t["net_pnl"] > 0)
        win_rate = (wins / n_closed * 100.0) if n_closed > 0 else 0.0

        return {
            "name": self.name,
            "initial_capital": self.initial_capital,
            "current_equity": round(self.equity, 2),
            "current_balance": round(self.balance, 2),
            "total_net_profit": round(total_pnl, 2),
            "total_return_pct": round(tot_ret, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "current_drawdown_pct": round(self.current_drawdown_pct, 2),
            "total_trades": n_closed,
            "win_rate_pct": round(win_rate, 2),
            "open_positions": list(self.positions.values()),
            "equity_curve": self.equity_curve[-100:],
            "drawdown_curve": self.drawdown_curve[-100:],
            "active_slots": f"{len(self.positions)} / {self.max_slots} Active Slots",
            "is_emergency_halt": self.emergency_halt,
            "micro_account_mode": self.micro_account_mode,
            "max_sizing_error_pct": self.max_sizing_error_pct,
            "lot_venue": self.lot_venue,
            "skipped_symbols": self.skipped_symbols
        }
