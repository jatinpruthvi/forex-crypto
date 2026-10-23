"""
AMATS Real-Time Paper Trading & Demo Simulator Engine:
Allows running Option A and Option B strategies against simulated or live tick feeds,
maintaining an isolated virtual paper account with:
- Starting capital (default $10,000 or $1,000)
- Real-time limit order matching (Maker 0.00% on MEXC / 0.02% on Bybit)
- Dynamic ATR Stop-Loss, Breakeven Ratchet (+0.25x ATR buffer), and Take-Profit
- Real-time equity curve, open positions, trade history, and drawdown tracking
- REST API and interactive Web Dashboard
"""
import time
import os
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("paper_broker")

class PaperAccount:
    def __init__(self, broker_name: str = "MEXC", starting_capital: float = 10000.0, maker_fee: float = 0.0):
        self.broker_name = broker_name
        self.initial_capital = starting_capital
        self.balance = starting_capital
        self.equity = starting_capital
        self.peak_equity = starting_capital
        self.max_drawdown_pct = 0.0
        self.maker_fee = maker_fee
        self.positions: Dict[str, dict] = {} # symbol -> position
        self.trades_history: List[dict] = []
        self.equity_history: List[dict] = [{"time": datetime.now(timezone.utc).isoformat(), "equity": starting_capital, "balance": starting_capital}]

    def open_position(self, symbol: str, side: str, price: float, risk_pct: float, sl_price: float, tp_price: float, atr: float, tag: str = "") -> Optional[dict]:
        if symbol in self.positions:
            return None # Already open
        
        risk_dollar = self.equity * (risk_pct / 100.0)
        risk_per_unit = abs(price - sl_price)
        if risk_per_unit <= 0:
            return None
        
        size = risk_dollar / risk_per_unit
        fee_cost = (size * price) * self.maker_fee
        self.balance -= fee_cost

        pos = {
            "symbol": symbol,
            "side": side, # "long" or "short"
            "entry_price": price,
            "current_price": price,
            "size": size,
            "risk_dollar": risk_dollar,
            "sl_price": sl_price,
            "tp_price": tp_price,
            "atr": atr,
            "be_locked": False,
            "tag": tag,
            "open_time": datetime.now(timezone.utc).isoformat(),
            "unrealized_pnl": 0.0,
            "fee_paid": fee_cost
        }
        self.positions[symbol] = pos
        logger.info(f"[{self.broker_name}] OPEN {side.upper()} {symbol} at {price:.2f} | Size: {size:.4f} | SL: {sl_price:.2f} | TP: {tp_price:.2f}")
        return pos

    def update_price(self, symbol: str, high: float, low: float, close: float, current_time: str = None) -> List[dict]:
        closed_trades = []
        if symbol not in self.positions:
            self._update_equity(current_time)
            return closed_trades

        pos = self.positions[symbol]
        side = pos["side"]
        entry = pos["entry_price"]
        sl = pos["sl_price"]
        tp = pos["tp_price"]
        atr = pos["atr"]
        size = pos["size"]

        # Check Stop Loss & Take Profit
        exit_reason = None
        exit_price = None

        if side == "long":
            pos["current_price"] = close
            pos["unrealized_pnl"] = (close - entry) * size
            
            # Check Breakeven ratchet condition: +1.0x ATR reached -> Lock SL to entry + 0.25x ATR
            if not pos["be_locked"] and (high - entry) >= atr:
                pos["be_locked"] = True
                new_sl = entry + 0.25 * atr
                if new_sl > pos["sl_price"]:
                    pos["sl_price"] = new_sl
                    logger.info(f"[{self.broker_name}] BREAKEVEN LOCKED on {symbol} Long at {new_sl:.2f}")

            # Check SL
            if low <= pos["sl_price"]:
                exit_reason = "stop_loss" if not pos["be_locked"] else "breakeven_buffer"
                exit_price = pos["sl_price"]
            # Check TP
            elif high >= tp:
                exit_reason = "take_profit_2x_atr"
                exit_price = tp

        elif side == "short":
            pos["current_price"] = close
            pos["unrealized_pnl"] = (entry - close) * size
            
            # Check Breakeven ratchet condition: +1.0x ATR reached
            if not pos["be_locked"] and (entry - low) >= atr:
                pos["be_locked"] = True
                new_sl = entry - 0.25 * atr
                if new_sl < pos["sl_price"]:
                    pos["sl_price"] = new_sl
                    logger.info(f"[{self.broker_name}] BREAKEVEN LOCKED on {symbol} Short at {new_sl:.2f}")

            # Check SL
            if high >= pos["sl_price"]:
                exit_reason = "stop_loss" if not pos["be_locked"] else "breakeven_buffer"
                exit_price = pos["sl_price"]
            # Check TP
            elif low <= tp:
                exit_reason = "take_profit_2x_atr"
                exit_price = tp

        if exit_reason:
            closed = self._close_position(symbol, exit_price, exit_reason, current_time)
            closed_trades.append(closed)

        self._update_equity(current_time)
        return closed_trades

    def _close_position(self, symbol: str, exit_price: float, reason: str, exit_time: str = None) -> dict:
        pos = self.positions.pop(symbol)
        side = pos["side"]
        size = pos["size"]
        entry = pos["entry_price"]

        if side == "long":
            gross_pnl = (exit_price - entry) * size
        else:
            gross_pnl = (entry - exit_price) * size

        exit_fee = (size * exit_price) * self.maker_fee
        net_pnl = gross_pnl - exit_fee
        self.balance += (gross_pnl - exit_fee)

        trade_record = {
            "symbol": symbol,
            "side": side,
            "entry_price": entry,
            "exit_price": exit_price,
            "size": size,
            "gross_pnl": gross_pnl,
            "net_pnl": net_pnl,
            "pnl_pct": (net_pnl / pos["risk_dollar"]) * 100.0,
            "fee_total": pos["fee_paid"] + exit_fee,
            "reason": reason,
            "tag": pos["tag"],
            "open_time": pos["open_time"],
            "exit_time": exit_time or datetime.now(timezone.utc).isoformat()
        }
        self.trades_history.append(trade_record)
        logger.info(f"[{self.broker_name}] CLOSED {side.upper()} {symbol} at {exit_price:.2f} | Reason: {reason} | PnL: ${net_pnl:+.2f}")
        return trade_record

    def _update_equity(self, current_time: str = None):
        unrealized = sum(p["unrealized_pnl"] for p in self.positions.values())
        self.equity = self.balance + unrealized
        if self.equity > self.peak_equity:
            self.peak_equity = self.equity
        dd = ((self.peak_equity - self.equity) / self.peak_equity) * 100.0
        if dd > self.max_drawdown_pct:
            self.max_drawdown_pct = dd
        
        t_str = current_time or datetime.now(timezone.utc).isoformat()
        self.equity_history.append({
            "time": t_str,
            "equity": round(self.equity, 2),
            "balance": round(self.balance, 2),
            "drawdown_pct": round(dd, 2)
        })
        if len(self.equity_history) > 1000:
            self.equity_history = self.equity_history[-1000:]

    def get_summary(self) -> dict:
        wins = [t for t in self.trades_history if t["net_pnl"] > 0]
        losses = [t for t in self.trades_history if t["net_pnl"] <= 0]
        total_pnl = self.equity - self.initial_capital
        win_rate = (len(wins) / len(self.trades_history) * 100.0) if self.trades_history else 0.0

        return {
            "broker": self.broker_name,
            "maker_fee_pct": self.maker_fee * 100.0,
            "initial_capital": self.initial_capital,
            "current_equity": round(self.equity, 2),
            "current_balance": round(self.balance, 2),
            "total_net_profit": round(total_pnl, 2),
            "total_return_pct": round((total_pnl / self.initial_capital) * 100.0, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "total_trades": len(self.trades_history),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate_pct": round(win_rate, 2),
            "open_positions": list(self.positions.values()),
            "recent_trades": self.trades_history[-10:]
        }
