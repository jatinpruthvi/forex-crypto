"""
Trend Following Strategy for FreqTrade (Regime: TREND)
EMA 21/50 + RSI(14) + ATR(14) Stop
"""
from freqtrade.strategy import IStrategy
from pandas import DataFrame
import pandas as pd


class TrendStrategy(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1h"
    can_short = True
    stoploss = -0.04
    minimal_roi = {"0": 0.06, "120": 0.04, "360": 0.02}

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema21"] = dataframe["close"].ewm(span=21, adjust=False).mean()
        dataframe["ema50"] = dataframe["close"].ewm(span=50, adjust=False).mean()

        delta = dataframe["close"].diff()
        gain = delta.where(delta > 0, 0.0).rolling(window=14, min_periods=1).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(window=14, min_periods=1).mean().replace(0, 1e-6)
        rs = gain / loss
        dataframe["rsi"] = 100.0 - (100.0 / (1.0 + rs))
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["ema21"] > dataframe["ema50"])
            & (dataframe["rsi"] > 50)
            & (dataframe["rsi"] < 70),
            "enter_long",
        ] = 1

        dataframe.loc[
            (dataframe["ema21"] < dataframe["ema50"])
            & (dataframe["rsi"] < 50)
            & (dataframe["rsi"] > 30),
            "enter_short",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["rsi"] > 75) | (dataframe["ema21"] < dataframe["ema50"]),
            "exit_long",
        ] = 1
        dataframe.loc[
            (dataframe["rsi"] < 25) | (dataframe["ema21"] > dataframe["ema50"]),
            "exit_short",
        ] = 1
        return dataframe
