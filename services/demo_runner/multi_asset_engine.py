"""
Portfolio Paper Engine for Option B: Concurrent Multi-Asset Trading
- Tracks multiple concurrent positions across BTC (40%), SOL (30%), BNB (15%), LINK (15%).
- Enforces independent per-position Stop Loss, Breakeven Ratchet (+0.25x ATR at +1.0x ATR),
  and Asymmetric Take-Profit Laddering (40% at 1.5x ATR, 40% at 2.5x ATR, 20% runner).
- Enforces Prop-Firm Daily Loss Lockout (< 4.0%) and Portfolio Drawdown Throttling.
"""
import logging
from typing import Dict, List, Optional
from services.monitoring.webhook_notifier import WebhookNotifier
from core.risk.institutional_guards import PropFirmRiskGuard

logger = logging.getLogger("multi_asset_portfolio_engine")


class MultiAssetPortfolioAccount:
    def __init__(
        self,
        name: str = "Option B Multi-Asset Portfolio (All-Weather)",
        initial_capital: float = 10000.0,
        maker_fee: float = 0.0000,
        max_open_positions: int = 4,
        laddered_tp: bool = True,
    ):
        self.name = name
        self.initial_capital = initial_capital
        self.balance = initial_capital
        self.equity = initial_capital
        self.peak_equity = initial_capital
        self.max_drawdown_pct = 0.0
        self.current_drawdown_pct = 0.0
        self.maker_fee = maker_fee
        self.max_open_positions = max_open_positions
        self.laddered_tp = laddered_tp

        self.positions: Dict[str, dict] = {}
        self.closed_trades: List[dict] = []
        self.equity_curve: List[float] = [initial_capital]
        self.drawdown_curve: List[float] = [0.0]
        self.notifier = WebhookNotifier()
        self.prop_guard = PropFirmRiskGuard(max_daily_loss_pct=4.0, lockout_trigger_pct=3.5)
        self.emergency_halt = False

        # Asset stake weights matching Option B strategy specification
        self.stake_weights = {
            "BTC/USDT": 0.40,
            "SOL/USDT": 0.30,
            "BNB/USDT": 0.15,
            "LINK/USDT": 0.15,
        }

    def get_dd_multiplier(self) -> float:
        if self.prop_guard.is_daily_locked:
            return 0.0

        dd = self.current_drawdown_pct
        if dd < 3.0:
            return 1.0
        elif dd < 5.0:
            return 0.75
        elif dd < 7.0:
            return 0.50
        elif dd < 8.0:
            return 0.25
        else:
            return 0.0

    def open_trade(
        self,
        timestamp: str,
        symbol: str,
        side: str,
        entry_price: float,
        atr: float,
        base_risk_pct: float = 3.0,
        ml_prob: Optional[float] = None,
        smc_entry_discount: Optional[float] = None,
    ):
        if self.emergency_halt or symbol in self.positions:
            return
        if len(self.positions) >= self.max_open_positions:
            return

        self.prop_guard.update_daily_state(timestamp, self.balance)
        dd_mult = self.get_dd_multiplier()
        if dd_mult <= 0:
            return

        effective_entry = smc_entry_discount if (smc_entry_discount is not None and smc_entry_discount > 0) else entry_price

        weight = self.stake_weights.get(symbol, 0.25)
        # Sizing proportional to portfolio weight & drawdown throttle
        effective_risk_pct = (base_risk_pct * weight * 2.5) * dd_mult
        anchor_capital = min(self.equity, self.balance) if self.balance > 0 else self.equity
        risk_usd = anchor_capital * (effective_risk_pct / 100.0)
        
        sl_mult = 1.0 if smc_entry_discount else (1.3 if ("BTC" in symbol or "LINK" in symbol) else 1.2)
        sl_dist = sl_mult * atr
        if sl_dist <= 0:
            return

        size = risk_usd / sl_dist
        max_notional = self.equity * weight * 3.0
        if (size * effective_entry) > max_notional:
            size = max_notional / effective_entry

        fee_cost = (size * effective_entry) * self.maker_fee
        self.balance -= fee_cost

        if side == "long":
            sl_price = effective_entry - sl_dist
            tp1 = effective_entry + (1.5 * atr)
            tp2 = effective_entry + (2.5 * atr)
            tp_final = effective_entry + (3.5 * atr)
        else:
            sl_price = effective_entry + sl_dist
            tp1 = effective_entry - (1.5 * atr)
            tp2 = effective_entry - (2.5 * atr)
            tp_final = effective_entry - (3.5 * atr)

        self.positions[symbol] = {
            "symbol": symbol,
            "side": side,
            "entry_time": timestamp,
            "entry_price": effective_entry,
            "current_price": effective_entry,
            "size": size,
            "remaining_size": size,
            "risk_usd": risk_usd,
            "sl_price": sl_price,
            "tp1": tp1,
            "tp2": tp2,
            "tp_price": tp_final,
            "tp1_taken": False,
            "tp2_taken": False,
            "atr": atr,
            "peak_price": effective_entry,
            "be_locked": False,
            "unrealized_pnl": 0.0,
            "fee_paid": fee_cost,
            "ml_confidence": (ml_prob * 100.0) if ml_prob is not None else None,
        }
        logger.info(f"[{self.name}] NEW {side.upper()} {symbol} @ {effective_entry:.2f} | Size: {size:.4f} | SL: {sl_price:.2f} | TP: {tp_final:.2f}")

    def on_asset_candle(self, timestamp: str, symbol: str, high: float, low: float, close: float):
        if symbol not in self.positions:
            return

        pos = self.positions[symbol]
        side = pos["side"]
        entry = pos["entry_price"]
        atr = pos["atr"]
        rem_size = pos["remaining_size"]

        exit_reason = None
        exit_price = None

        if side == "long":
            pos["current_price"] = close
            pos["unrealized_pnl"] = (close - entry) * rem_size
            if high > pos["peak_price"]:
                pos["peak_price"] = high
                if (high - entry) >= (1.5 * atr):
                    trailing_sl = high - (2.5 * atr)
                    if trailing_sl > pos["sl_price"]:
                        pos["sl_price"] = trailing_sl

            # Breakeven Lock Rule: Once +1.0x ATR reached, lock SL at Entry + 0.25x ATR
            if not pos["be_locked"] and (high - entry) >= (1.0 * atr):
                pos["be_locked"] = True
                new_sl = entry + (0.25 * atr)
                if new_sl > pos["sl_price"]:
                    pos["sl_price"] = new_sl

            # Asymmetric Take-Profit Laddering
            if self.laddered_tp:
                if not pos["tp1_taken"] and high >= pos["tp1"]:
                    pos["tp1_taken"] = True
                    part_size = pos["size"] * 0.40
                    part_gain = (pos["tp1"] - entry) * part_size
                    part_fee = (part_size * pos["tp1"]) * self.maker_fee
                    pos["fee_paid"] += part_fee
                    self.balance += (part_gain - part_fee)
                    pos["remaining_size"] -= part_size
                    pos["sl_price"] = max(pos["sl_price"], entry + (0.35 * atr))

                if not pos["tp2_taken"] and high >= pos["tp2"]:
                    pos["tp2_taken"] = True
                    part_size = pos["size"] * 0.40
                    part_gain = (pos["tp2"] - entry) * part_size
                    part_fee = (part_size * pos["tp2"]) * self.maker_fee
                    pos["fee_paid"] += part_fee
                    self.balance += (part_gain - part_fee)
                    pos["remaining_size"] -= part_size
                    pos["sl_price"] = max(pos["sl_price"], entry + (1.2 * atr))

            if low <= pos["sl_price"]:
                if not pos["be_locked"]:
                    exit_reason = "stop_loss"
                elif pos["sl_price"] > (entry + 0.25 * atr):
                    exit_reason = "trailing_stop"
                else:
                    exit_reason = "breakeven_buffer"
                exit_price = pos["sl_price"]
            elif high >= pos["tp_price"]:
                exit_reason = "take_profit_moonbag"
                exit_price = pos["tp_price"]

        elif side == "short":
            pos["current_price"] = close
            pos["unrealized_pnl"] = (entry - close) * rem_size
            if low < pos["peak_price"]:
                pos["peak_price"] = low
                if (entry - low) >= (1.5 * atr):
                    trailing_sl = low + (2.5 * atr)
                    if trailing_sl < pos["sl_price"]:
                        pos["sl_price"] = trailing_sl

            # Breakeven Lock Rule: Once +1.0x ATR reached, lock SL at Entry - 0.25x ATR
            if not pos["be_locked"] and (entry - low) >= (1.0 * atr):
                pos["be_locked"] = True
                new_sl = entry - (0.25 * atr)
                if new_sl < pos["sl_price"]:
                    pos["sl_price"] = new_sl

            # Asymmetric Take-Profit Laddering for SHORT
            if self.laddered_tp:
                if not pos["tp1_taken"] and low <= pos["tp1"]:
                    pos["tp1_taken"] = True
                    part_size = pos["size"] * 0.40
                    part_gain = (entry - pos["tp1"]) * part_size
                    part_fee = (part_size * pos["tp1"]) * self.maker_fee
                    pos["fee_paid"] += part_fee
                    self.balance += (part_gain - part_fee)
                    pos["remaining_size"] -= part_size
                    pos["sl_price"] = min(pos["sl_price"], entry - (0.35 * atr))

                if not pos["tp2_taken"] and low <= pos["tp2"]:
                    pos["tp2_taken"] = True
                    part_size = pos["size"] * 0.40
                    part_gain = (entry - pos["tp2"]) * part_size
                    part_fee = (part_size * pos["tp2"]) * self.maker_fee
                    pos["fee_paid"] += part_fee
                    self.balance += (part_gain - part_fee)
                    pos["remaining_size"] -= part_size
                    pos["sl_price"] = min(pos["sl_price"], entry - (1.2 * atr))

            if high >= pos["sl_price"]:
                if not pos["be_locked"]:
                    exit_reason = "stop_loss"
                elif pos["sl_price"] < (entry - 0.25 * atr):
                    exit_reason = "trailing_stop"
                else:
                    exit_reason = "breakeven_buffer"
                exit_price = pos["sl_price"]
            elif low <= pos["tp_price"]:
                exit_reason = "take_profit_moonbag"
                exit_price = pos["tp_price"]

        if exit_reason:
            self._close_position(timestamp, symbol, exit_price, exit_reason)

    def finish_candle(self, timestamp: str):
        total_unrealized = sum(p["unrealized_pnl"] for p in self.positions.values())
        self.equity = self.balance + total_unrealized

        if self.equity > self.peak_equity:
            self.peak_equity = self.equity

        if self.peak_equity > 0:
            self.current_drawdown_pct = ((self.peak_equity - self.equity) / self.peak_equity) * 100.0
        else:
            self.current_drawdown_pct = 0.0

        if self.current_drawdown_pct > self.max_drawdown_pct:
            self.max_drawdown_pct = self.current_drawdown_pct

        self.equity_curve.append(round(self.equity, 2))
        self.drawdown_curve.append(round(self.current_drawdown_pct, 2))
        if len(self.equity_curve) > 120:
            self.equity_curve.pop(0)
            self.drawdown_curve.pop(0)

    def emergency_flatten(self, timestamp: str, reason: str = "EMERGENCY_KILL_SWITCH"):
        """Emergency circuit breaker: liquidates all open positions and engages halt."""
        self.emergency_halt = True
        symbols = list(self.positions.keys())
        for sym in symbols:
            pos = self.positions[sym]
            cur_p = pos.get("current_price", pos["entry_price"])
            self._close_position(timestamp, sym, cur_p, reason)
        logger.warning(f"[{self.name}] EMERGENCY KILL-SWITCH ENGAGED! All {len(symbols)} positions liquidated.")

    def resume_trading(self):
        """Lifts emergency halt."""
        self.emergency_halt = False
        logger.info(f"[{self.name}] Emergency halt lifted. Trading resumed.")

    def _close_position(self, timestamp: str, symbol: str, exit_price: float, reason: str):
        pos = self.positions[symbol]
        side = pos["side"]
        rem_size = pos["remaining_size"]
        entry = pos["entry_price"]

        gross_pnl = (exit_price - entry) * rem_size if side == "long" else (entry - exit_price) * rem_size
        exit_fee = (rem_size * exit_price) * self.maker_fee
        net_pnl = gross_pnl - exit_fee
        self.balance += net_pnl

        return_pct = round((net_pnl / pos["risk_usd"]) * 100.0, 2) if pos["risk_usd"] > 0 else 0.0

        trade_record = {
            "id": len(self.closed_trades) + 1,
            "symbol": symbol,
            "side": side.upper(),
            "entry_time": str(pos["entry_time"]),
            "exit_time": str(timestamp),
            "entry_price": round(entry, 2),
            "exit_price": round(exit_price, 2),
            "size": round(rem_size, 4),
            "gross_pnl": round(gross_pnl, 2),
            "net_pnl": round(net_pnl, 2),
            "return_pct": return_pct,
            "exit_reason": reason,
            "fee": round(pos["fee_paid"] + exit_fee, 2),
        }
        self.closed_trades.append(trade_record)
        del self.positions[symbol]
        logger.info(f"[{self.name}] CLOSED {side.upper()} {symbol} @ {exit_price:.2f} | Reason: {reason} | PnL: ${net_pnl:+.2f}")

    def get_summary(self) -> dict:
        wins = [t for t in self.closed_trades if t["net_pnl"] > 0]
        losses = [t for t in self.closed_trades if t["net_pnl"] <= 0]
        total_pnl = self.equity - self.initial_capital
        win_rate = (len(wins) / len(self.closed_trades) * 100.0) if self.closed_trades else 0.0

        open_pos_list = []
        for sym, pos in self.positions.items():
            open_pos_list.append({
                "symbol": pos["symbol"],
                "side": pos["side"].upper(),
                "entry_price": round(pos["entry_price"], 2),
                "current_price": round(pos["current_price"], 2),
                "size": round(pos["remaining_size"], 4),
                "sl_price": round(pos["sl_price"], 2),
                "tp_price": round(pos["tp_price"], 2),
                "unrealized_pnl": round(pos["unrealized_pnl"], 2),
                "be_locked": pos["be_locked"],
                "ml_confidence": pos.get("ml_confidence"),
            })

        return {
            "name": self.name,
            "maker_fee_pct": self.maker_fee * 100.0,
            "initial_capital": self.initial_capital,
            "current_equity": round(self.equity, 2),
            "current_balance": round(self.balance, 2),
            "total_net_profit": round(total_pnl, 2),
            "total_return_pct": round((total_pnl / self.initial_capital) * 100.0, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "current_drawdown_pct": round(self.current_drawdown_pct, 2),
            "total_trades": len(self.closed_trades),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate_pct": round(win_rate, 2),
            "open_positions": open_pos_list,
            "recent_trades": self.closed_trades[-15:],
            "equity_curve": list(self.equity_curve),
            "drawdown_curve": list(self.drawdown_curve),
            "active_assets": ["BTC (40%)", "SOL (30%)", "BNB (15%)", "LINK (15%)"],
        }
