"""
Mean Reversion Strategy for FreqTrade (Regime: RANGE)
Bollinger Bands (20, 2.5) + RSI(7) + ATR(14)
"""
from freqtrade.strategy import IStrategy
from pandas import DataFrame
import pandas as pd


class MeanReversionStrategy(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "15m"
    can_short = True
    stoploss = -0.03
    minimal_roi = {"0": 0.03, "30": 0.015, "90": 0.005}

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Bollinger Bands (20, 2.5)
        sma20 = dataframe["close"].rolling(window=20, min_periods=1).mean()
        std20 = dataframe["close"].rolling(window=20, min_periods=1).std()
        dataframe["bb_lower"] = sma20 - (2.5 * std20)
        dataframe["bb_middle"] = sma20
        dataframe["bb_upper"] = sma20 + (2.5 * std20)

        # RSI 7
        delta = dataframe["close"].diff()
        gain = delta.where(delta > 0, 0.0).rolling(window=7, min_periods=1).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(window=7, min_periods=1).mean().replace(0, 1e-6)
        rs = gain / loss
        dataframe["rsi"] = 100.0 - (100.0 / (1.0 + rs))
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["close"] <= dataframe["bb_lower"]) & (dataframe["rsi"] < 25),
            "enter_long",
        ] = 1

        dataframe.loc[
            (dataframe["close"] >= dataframe["bb_upper"]) & (dataframe["rsi"] > 75),
            "enter_short",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["close"] >= dataframe["bb_middle"]) | (dataframe["rsi"] > 55),
            "exit_long",
        ] = 1

        dataframe.loc[
            (dataframe["close"] <= dataframe["bb_middle"]) | (dataframe["rsi"] < 45),
            "exit_short",
        ] = 1
        return dataframe
