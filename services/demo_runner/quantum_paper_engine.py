"""
Live Demo Paper Trading Engine for Option C:
Triple-Confluence Quantum Hybrid Engine (Crypto & Forex Multi-Market):
- Dual-Regime Classifier:
  * Trending (ADX >= 20): Donchian 14 + SMC Fair Value Gap (FVG) breakout with VWAP acceptance.
  * Chop (ADX < 20): Bollinger Band 2.0 std + RSI extreme scalper.
- Two-Tier Risk-Free House Money Pyramiding:
  * Tier 1 (@ 1.8x ATR): Realizes 40% profit, moves SL to Entry + 0.35x ATR buffer (100% risk free),
    and adds a 1.0x runner unit funded purely by locked gains.
  * Tier 2 (@ 3.0x ATR): Locks SL at Entry + 1.5x ATR and adds a 0.8x trailing runner.
  * Chandelier Trailing Ratchet: 2.0x ATR.
- Multi-Market Asset Support:
  * BTC/USDT (35%), BNB/USDT (35%), Gold/XAUUSD (30%).
- Real-Time Transparent Accounting:
  * Candle-by-candle walk-forward tracking, Dynamic Drawdown Throttle, full trade audit log.
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone

from services.monitoring.webhook_notifier import WebhookNotifier
from core.risk.institutional_guards import PropFirmRiskGuard

logger = logging.getLogger("quantum_hybrid_paper_engine")


class QuantumHybridPortfolioAccount:
    def __init__(
        self,
        name: str = "Option C: Triple-Confluence Quantum Hybrid (BTC 35%, BNB 35%, Gold 30%)",
        initial_capital: float = 10000.0,
        maker_fee: float = 0.00015,
        taker_fee: Optional[float] = None,
        stop_slippage: float = 0.0005,
        max_open_positions: int = 4,
    ):
        self.name = name
        self.initial_capital = initial_capital
        self.balance = initial_capital
        self.equity = initial_capital
        self.peak_equity = initial_capital
        self.max_drawdown_pct = 0.0
        self.current_drawdown_pct = 0.0
        self.maker_fee = maker_fee
        # Trigger stops are taker orders: default 3x maker (HL Tier 0).
        self.taker_fee = taker_fee if taker_fee is not None else max(maker_fee * 3.0, 0.00045)
        self.stop_slippage = stop_slippage
        self.max_open_positions = max_open_positions

        self.positions: Dict[str, dict] = {}
        self.closed_trades: List[dict] = []
        self.equity_curve: List[float] = [initial_capital]
        self.drawdown_curve: List[float] = [0.0]
        self.notifier = WebhookNotifier()
        self.prop_guard = PropFirmRiskGuard(max_daily_loss_pct=4.0, lockout_trigger_pct=3.5)
        self.emergency_halt = False

        # Stake weights for Option C Quantum Hybrid
        self.stake_weights = {
            "BTC/USDT": 0.35,
            "BNB/USDT": 0.35,
            "XAU/USD": 0.30,
            "SOL/USDT": 0.0,
        }

    def on_asset_candle(self, ts: str, symbol: str, high: float, low: float, close: float):
        if self.emergency_halt or symbol not in self.positions:
            return

        pos = self.positions[symbol]
        atr = pos["atr"]
        side = pos["side"]
        entry = pos["entry_price"]

        # Check Stops & Pyramiding
        if side == "long":
            stop_at_start = pos["stop_loss"]
            # Conservative same-bar resolution: if the bar traded through the
            # bar-START stop, the stop fills FIRST -- no TP/pyramid bookkeeping.
            if low <= stop_at_start:
                self._close_position(ts, symbol, stop_at_start * (1.0 - self.stop_slippage), "STOP_OR_TRAILING_HIT")
                return

            # Check Tier 1 Take-Profit (+1.8x ATR)
            if not pos["tp1_hit"] and high >= pos["tp1_price"]:
                pos["tp1_hit"] = True
                realized_qty = pos["size"] * 0.40
                pnl = (pos["tp1_price"] - entry) * realized_qty
                fee = (pos["tp1_price"] * realized_qty) * self.maker_fee
                net_pnl = pnl - fee
                self.balance += net_pnl
                pos["size"] *= 0.60
                pos["realized_pnl"] += net_pnl
                # Ratchet SL to Entry + 0.35x ATR buffer (100% Risk Free)
                pos["stop_loss"] = entry + (atr * 0.35)
                pos["be_locked"] = True

                # Tier 1 House Money Pyramiding
                if pos["pyramid_tier"] == 0 and pos.get("regime") == "TREND":
                    pos["pyramid_tier"] = 1
                    tier1_qty = (self.equity * 0.02 * 2.0 * 1.0) / max(atr * 1.5, 1e-4, entry * 5e-4)
                    pos["size"] += tier1_qty

            # Check Tier 2 Take-Profit (+3.0x ATR)
            if pos["tp1_hit"] and pos["pyramid_tier"] == 1 and pos.get("regime") == "TREND":
                tp2_target = entry + (atr * 3.0)
                if high >= tp2_target:
                    pos["pyramid_tier"] = 2
                    tier2_qty = (self.equity * 0.02 * 2.0 * 0.8) / max(atr * 1.5, 1e-4, entry * 5e-4)
                    pos["size"] += tier2_qty
                    pos["stop_loss"] = entry + (atr * 1.5)  # Lock deep profit

            # Chandelier Trailing Stop Ratchet (effective for FUTURE bars only)
            if pos["tp1_hit"]:
                chandelier = high - (atr * 2.0)
                if chandelier > pos["stop_loss"]:
                    pos["stop_loss"] = chandelier

        elif side == "short":
            stop_at_start = pos["stop_loss"]
            # Conservative same-bar resolution against the bar-START stop.
            if high >= stop_at_start:
                self._close_position(ts, symbol, stop_at_start * (1.0 + self.stop_slippage), "STOP_OR_TRAILING_HIT")
                return

            if not pos["tp1_hit"] and low <= pos["tp1_price"]:
                pos["tp1_hit"] = True
                realized_qty = pos["size"] * 0.40
                pnl = (entry - pos["tp1_price"]) * realized_qty
                fee = (pos["tp1_price"] * realized_qty) * self.maker_fee
                net_pnl = pnl - fee
                self.balance += net_pnl
                pos["size"] *= 0.60
                pos["realized_pnl"] += net_pnl
                pos["stop_loss"] = entry - (atr * 0.35)
                pos["be_locked"] = True

                if pos["pyramid_tier"] == 0 and pos.get("regime") == "TREND":
                    pos["pyramid_tier"] = 1
                    tier1_qty = (self.equity * 0.02 * 2.0 * 1.0) / max(atr * 1.5, 1e-4, entry * 5e-4)
                    pos["size"] += tier1_qty

            if pos["tp1_hit"] and pos["pyramid_tier"] == 1 and pos.get("regime") == "TREND":
                tp2_target = entry - (atr * 3.0)
                if low <= tp2_target:
                    pos["pyramid_tier"] = 2
                    tier2_qty = (self.equity * 0.02 * 2.0 * 0.8) / max(atr * 1.5, 1e-4, entry * 5e-4)
                    pos["size"] += tier2_qty
                    pos["stop_loss"] = entry - (atr * 1.5)

            if pos["tp1_hit"]:
                chandelier = low + (atr * 2.0)
                if chandelier < pos["stop_loss"]:
                    pos["stop_loss"] = chandelier

        # Mark-to-Market Unrealized P&L
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

        # Check Prop Firm Risk Guard (halt at 3.5% daily drawdown)
        guard_state = self.prop_guard.update_daily_state(ts, self.balance)
        if guard_state.get("is_locked_out", False):
            self.emergency_halt = True
            self.emergency_liquidate_all(ts, "PROP_FIRM_DAILY_LOCKOUT_TRIGGERED")

    def open_trade(
        self,
        ts: str,
        symbol: str,
        side: str,
        entry_price: float,
        atr: float,
        base_risk_pct: float = 2.0,
        regime: str = "TREND"
    ) -> bool:
        if self.emergency_halt:
            return False
        if symbol in self.positions:
            return False  # Already in position
        if len(self.positions) >= self.max_open_positions:
            return False

        stake_weight = self.stake_weights.get(symbol, 0.25)
        if stake_weight <= 0:
            return False

        # Dynamic Drawdown Throttle (scales risk down at 5% DD)
        dd_factor = 0.5 if self.current_drawdown_pct >= 5.0 else 1.0
        allocated_capital = self.equity * stake_weight
        risk_capital = allocated_capital * (base_risk_pct / 100.0) * 2.0 * dd_factor

        stop_dist = atr * 1.3
        size = risk_capital / max(stop_dist, 1e-4)

        if side == "long":
            sl = entry_price - stop_dist
            tp1 = entry_price + (atr * 1.8)
        else:
            sl = entry_price + stop_dist
            tp1 = entry_price - (atr * 1.8)

        # Deduct initial maker entry fee
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
        # Trigger/stop exits execute as taker orders (maker only for TP1 partials).
        fee = (exit_price * pos["size"]) * self.taker_fee
        net_trade_pnl = pnl - fee
        self.balance += (pnl - fee)

        total_trade_pnl = pos["realized_pnl"] + net_trade_pnl
        record = {
            "strategy": "Option C (Quantum Hybrid)",
            "account": self.name,
            "symbol": symbol,
            "side": pos["side"],
            "entry_time": pos["entry_time"],
            "exit_time": ts,
            "entry_price": round(pos["entry_price"], 2),
            "exit_price": round(exit_price, 2),
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
            "active_assets": [f"{s} ({int(w*100)}%)" for s, w in self.stake_weights.items() if w > 0],
            "is_emergency_halt": self.emergency_halt
        }
