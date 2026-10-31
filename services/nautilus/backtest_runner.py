"""
NautilusTrader High-Fidelity Backtest Runner:
Executes Donchian Breakout and Multi-Asset strategies with nanosecond-resolution event simulation.
"""
from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np

from nautilus_trader.model.data import Bar
from services.nautilus.strategies.donchian_breakout import DonchianBreakoutConfig, DonchianBreakoutStrategy
from services.nautilus.adapters.data_loader import NautilusDataLoader


class NautilusSimulationRunner:
    """
    Simulation orchestrator running Nautilus strategy actors against historical Bar sequences.
    """
    def __init__(self, instrument_id: str = "BTCUSDT-PERP.BYBIT"):
        self.instrument_id = instrument_id

    def run_strategy_simulation(
        self,
        df: pd.DataFrame,
        config: Optional[DonchianBreakoutConfig] = None,
    ) -> Dict[str, Any]:
        """
        Executes event-driven bar simulation using the DonchianBreakoutStrategy.
        """
        if config is None:
            config = DonchianBreakoutConfig(instrument_id=self.instrument_id)

        strategy = DonchianBreakoutStrategy(config)
        strategy.on_start()

        bars = NautilusDataLoader.dataframe_to_bars(
            df,
            instrument_id_str=self.instrument_id,
            timeframe_minutes=15,
        )

        trades_executed = 0
        trade_logs = []

        # Hook into strategy logging to capture state transitions
        for bar in bars:
            prev_pos = strategy.position_side
            strategy.on_bar(bar)
            curr_pos = strategy.position_side

            if prev_pos is None and curr_pos is not None:
                trades_executed += 1
                trade_logs.append({
                    "event": "ENTRY",
                    "side": str(curr_pos),
                    "price": strategy.entry_price,
                    "sl": strategy.current_sl,
                    "tp": strategy.current_tp,
                    "ts": bar.ts_event,
                })
            elif prev_pos is not None and curr_pos is None:
                trade_logs.append({
                    "event": "EXIT",
                    "price": float(bar.close),
                    "ts": bar.ts_event,
                })

        strategy.on_stop()

        return {
            "instrument": self.instrument_id,
            "total_bars_processed": len(bars),
            "total_trades_initiated": trades_executed,
            "trade_events": trade_logs,
            "status": "completed",
        }

    def run_multi_instrument_simulation(
        self,
        instruments_data: Dict[str, pd.DataFrame],
        configs: Optional[Dict[str, DonchianBreakoutConfig]] = None,
    ) -> Dict[str, Any]:
        """
        Executes synchronous multi-instrument simulation across multiple assets simultaneously.
        """
        configs = configs or {}
        strategies: Dict[str, DonchianBreakoutStrategy] = {}
        for inst_id in instruments_data.keys():
            cfg = configs.get(inst_id, DonchianBreakoutConfig(instrument_id=inst_id))
            strat = DonchianBreakoutStrategy(cfg)
            strat.on_start()
            strategies[inst_id] = strat

        multi_bars = NautilusDataLoader.multi_instrument_bars(instruments_data, timeframe_minutes=15)
        
        per_instrument_trades: Dict[str, int] = {inst: 0 for inst in instruments_data}
        event_logs = []

        for bar in multi_bars:
            inst_str = str(bar.bar_type.instrument_id)
            strat = strategies.get(inst_str)
            if not strat:
                continue

            prev_pos = strat.position_side
            strat.on_bar(bar)
            curr_pos = strat.position_side

            if prev_pos is None and curr_pos is not None:
                per_instrument_trades[inst_str] += 1
                event_logs.append({
                    "event": "ENTRY",
                    "instrument": inst_str,
                    "side": str(curr_pos),
                    "price": strat.entry_price,
                    "ts": bar.ts_event,
                })
            elif prev_pos is not None and curr_pos is None:
                event_logs.append({
                    "event": "EXIT",
                    "instrument": inst_str,
                    "price": float(bar.close),
                    "ts": bar.ts_event,
                })

        for strat in strategies.values():
            strat.on_stop()

        return {
            "total_bars_processed": len(multi_bars),
            "instruments": list(instruments_data.keys()),
            "trades_per_instrument": per_instrument_trades,
            "total_trades": sum(per_instrument_trades.values()),
            "trade_events": event_logs,
            "status": "completed",
        }
