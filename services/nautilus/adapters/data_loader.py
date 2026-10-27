"""
Data Converter for NautilusTrader:
Converts Pandas OHLCV historical DataFrames and CSV files into Nautilus Bar format.
Supports single-instrument and multi-instrument synchronous timestamp loading.
"""
from typing import List, Dict
import pandas as pd

from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.objects import Price, Quantity


class NautilusDataLoader:
    @staticmethod
    def dataframe_to_bars(
        df: pd.DataFrame,
        instrument_id_str: str = "BTCUSDT-PERP.BYBIT",
        timeframe_minutes: int = 15,
        price_precision: int = 2,
        size_precision: int = 4,
    ) -> List[Bar]:
        """
        Converts standard pandas DataFrame into a list of NautilusTrader Bar objects.
        """
        bar_type_str = f"{instrument_id_str}-{timeframe_minutes}-MINUTE-LAST-EXTERNAL"
        bar_type = BarType.from_str(bar_type_str)

        bars = []
        for _, row in df.iterrows():
            ts = row["timestamp"]
            if isinstance(ts, (int, float)):
                ts_ns = int(ts * 1_000_000_000) if ts < 1e12 else int(ts * 1_000_000)
            else:
                dt = pd.to_datetime(ts, utc=True)
                ts_ns = int(dt.value)

            bar = Bar(
                bar_type=bar_type,
                open=Price(float(row["open"]), precision=price_precision),
                high=Price(float(row["high"]), precision=price_precision),
                low=Price(float(row["low"]), precision=price_precision),
                close=Price(float(row["close"]), precision=price_precision),
                volume=Quantity(float(row["volume"]), precision=size_precision),
                ts_event=ts_ns,
                ts_init=ts_ns,
            )
            bars.append(bar)

        return bars

    @staticmethod
    def multi_instrument_bars(
        instruments_data: Dict[str, pd.DataFrame],
        timeframe_minutes: int = 15,
        price_precision: int = 2,
        size_precision: int = 4,
    ) -> List[Bar]:
        """
        Merges multiple instrument DataFrames into a globally sorted, synchronous Bar stream.
        Enables multi-asset portfolio simulation without temporal lookahead.
        """
        all_bars: List[Bar] = []
        for instrument_id_str, df in instruments_data.items():
            bars = NautilusDataLoader.dataframe_to_bars(
                df,
                instrument_id_str=instrument_id_str,
                timeframe_minutes=timeframe_minutes,
                price_precision=price_precision,
                size_precision=size_precision,
            )
            all_bars.extend(bars)

        # Sort all bars synchronously by event timestamp
        all_bars.sort(key=lambda b: b.ts_event)
        return all_bars
