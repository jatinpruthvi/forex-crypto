"""
Option A: BTC Compressed Donchian Breakout Strategy for NautilusTrader
Ported from OptionA_BTC_CompressedDonchian with native event-driven lifecycle,
microstructure trailing stops, and breakeven buffer protection.
"""
from typing import Optional, List
import numpy as np

from nautilus_trader.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId


class DonchianBreakoutConfig(StrategyConfig, frozen=True):
    instrument_id: str
    timeframe_minutes: int = 15
    donchian_period: int = 12
    atr_period: int = 14
    sl_atr_mult: float = 1.3
    tp_atr_mult: float = 2.0
    trailing_atr_mult: float = 2.5
    be_profit_buffer_mult: float = 0.25
    be_activation_mult: float = 1.0
    risk_pct_per_trade: float = 0.02
    max_leverage: float = 3.0


class DonchianBreakoutStrategy(Strategy):
    """
    NautilusTrader implementation of the Champion 12-bar Donchian Breakout engine.
    """
    def __init__(self, config: DonchianBreakoutConfig) -> None:
        super().__init__(config)
        self.instrument_id = InstrumentId.from_str(config.instrument_id)
        bar_type_str = f"{config.instrument_id}-{config.timeframe_minutes}-MINUTE-LAST-EXTERNAL"
        self.bar_type = BarType.from_str(bar_type_str)
        self.bars: List[Bar] = []
        self.entry_price: Optional[float] = None
        self.current_sl: Optional[float] = None
        self.current_tp: Optional[float] = None
        self.peak_price: Optional[float] = None
        self.valley_price: Optional[float] = None
        self.position_side: Optional[OrderSide] = None
        self.partial_taken: bool = False

    def on_start(self) -> None:
        self.log.info(f"Starting DonchianBreakoutStrategy for {self.bar_type}")

    def on_stop(self) -> None:
        self.log.info(f"Stopping DonchianBreakoutStrategy for {self.bar_type}")

    def calculate_atr(self) -> float:
        if len(self.bars) < 2:
            return 0.0
        trs = []
        for i in range(1, min(len(self.bars), self.config.atr_period + 1)):
            curr = self.bars[-i]
            prev = self.bars[-(i + 1)]
            tr = max(
                float(curr.high - curr.low),
                abs(float(curr.high - prev.close)),
                abs(float(curr.low - prev.close)),
            )
            trs.append(tr)
        return float(np.mean(trs)) if trs else 0.0

    def on_bar(self, bar: Bar) -> None:
        self.bars.append(bar)
        if len(self.bars) > 100:
            self.bars.pop(0)

        if len(self.bars) < self.config.donchian_period + 2:
            return

        atr = self.calculate_atr()
        if atr <= 0:
            return

        curr_close = float(bar.close)
        curr_high = float(bar.high)
        curr_low = float(bar.low)

        # 1. Manage Active Position (Trailing ratchets & Breakeven Lock)
        if self.position_side is not None and self.entry_price is not None:
            if self.position_side == OrderSide.BUY:
                if self.peak_price is None or curr_high > self.peak_price:
                    self.peak_price = curr_high

                unrealized_profit = curr_close - self.entry_price
                be_dist = self.config.be_activation_mult * atr

                # Ratchet Breakeven + Buffer
                if unrealized_profit >= be_dist:
                    target_be_sl = self.entry_price + (self.config.be_profit_buffer_mult * atr)
                    if self.current_sl is None or target_be_sl > self.current_sl:
                        self.current_sl = target_be_sl

                # Dynamic Trailing Ratchet
                if self.peak_price is not None and unrealized_profit >= (1.5 * atr):
                    trail_sl = self.peak_price - (self.config.trailing_atr_mult * atr)
                    if self.current_sl is None or trail_sl > self.current_sl:
                        self.current_sl = trail_sl

                # Check Exits
                if self.current_sl is not None and curr_low <= self.current_sl:
                    self._close_position("SL_HIT")
                    return
                if self.current_tp is not None and curr_high >= self.current_tp:
                    self._close_position("TP_HIT")
                    return

            elif self.position_side == OrderSide.SELL:
                if self.valley_price is None or curr_low < self.valley_price:
                    self.valley_price = curr_low

                unrealized_profit = self.entry_price - curr_close
                be_dist = self.config.be_activation_mult * atr

                # Ratchet Breakeven + Buffer (Shorts: lower SL is tighter)
                if unrealized_profit >= be_dist:
                    target_be_sl = self.entry_price - (self.config.be_profit_buffer_mult * atr)
                    if self.current_sl is None or target_be_sl < self.current_sl:
                        self.current_sl = target_be_sl

                # Dynamic Trailing Ratchet
                if self.valley_price is not None and unrealized_profit >= (1.5 * atr):
                    trail_sl = self.valley_price + (self.config.trailing_atr_mult * atr)
                    if self.current_sl is None or trail_sl < self.current_sl:
                        self.current_sl = trail_sl

                # Check Exits
                if self.current_sl is not None and curr_high >= self.current_sl:
                    self._close_position("SL_HIT")
                    return
                if self.current_tp is not None and curr_low <= self.current_tp:
                    self._close_position("TP_HIT")
                    return

            return  # In position, don't open secondary

        # 2. Check Breakout Entries
        past_bars = self.bars[-(self.config.donchian_period + 1):-1]
        donchian_high = max(float(b.high) for b in past_bars)
        donchian_low = min(float(b.low) for b in past_bars)

        if curr_close > donchian_high:
            self._enter_position(OrderSide.BUY, curr_close, atr)
        elif curr_close < donchian_low:
            self._enter_position(OrderSide.SELL, curr_close, atr)

    def _enter_position(self, side: OrderSide, price: float, atr: float) -> None:
        self.position_side = side
        self.entry_price = price
        self.partial_taken = False

        sl_dist = self.config.sl_atr_mult * atr
        tp_dist = self.config.tp_atr_mult * atr

        if side == OrderSide.BUY:
            self.current_sl = price - sl_dist
            self.current_tp = price + tp_dist
            self.peak_price = price
            self.valley_price = None
            self.log.info(f"BUY Signal at {price:.2f} | SL: {self.current_sl:.2f} | TP: {self.current_tp:.2f}")
        else:
            self.current_sl = price + sl_dist
            self.current_tp = price - tp_dist
            self.peak_price = None
            self.valley_price = price
            self.log.info(f"SELL Signal at {price:.2f} | SL: {self.current_sl:.2f} | TP: {self.current_tp:.2f}")

    def _close_position(self, reason: str) -> None:
        self.log.info(f"Closed {self.position_side} position: Reason={reason}")
        self.position_side = None
        self.entry_price = None
        self.current_sl = None
        self.current_tp = None
        self.peak_price = None
        self.valley_price = None
        self.partial_taken = False
