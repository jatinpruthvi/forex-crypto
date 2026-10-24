import pytest
import pandas as pd
import numpy as np
from core.analysis.fast_backtester import BacktestSimulator
from services.freqtrade.user_data.strategies.OptionA_BTC_CompressedDonchian import OptionA_BTC_CompressedDonchian
from services.freqtrade.user_data.strategies.OptionB_MultiAsset_Portfolio import OptionB_MultiAsset_Portfolio

def test_option_a_strategy_interface():
    strat = OptionA_BTC_CompressedDonchian()
    assert strat.timeframe == "15m"
    assert strat.can_short is True
    assert strat.donchian_lookback == 12
    assert strat.atr_sl_mult == 1.3
    assert strat.atr_tp_mult == 2.0
    assert strat.trailing_atr_mult == 2.5
    assert strat.adx_min == 18.0
    assert strat.be_profit_buffer == 0.25

    # Mock OHLCV DataFrame
    n = 50
    df = pd.DataFrame({
        "open": np.linspace(20000, 21000, n),
        "high": np.linspace(20100, 21200, n),
        "low": np.linspace(19900, 20900, n),
        "close": np.linspace(20050, 21150, n),
        "volume": np.full(n, 100.0),
        "macro_trend_4h": np.full(n, 1)
    })
    
    df_ind = strat.populate_indicators(df, {"pair": "BTC/USDT:USDT"})
    assert "donchian_high" in df_ind.columns
    assert "donchian_low" in df_ind.columns
    assert "vwap" in df_ind.columns
    assert "atr" in df_ind.columns

    df_entry = strat.populate_entry_trend(df_ind, {"pair": "BTC/USDT:USDT"})
    assert "enter_long" in df_entry.columns
    assert "enter_short" in df_entry.columns


def test_option_b_strategy_interface():
    strat = OptionB_MultiAsset_Portfolio()
    assert strat.timeframe == "15m"
    assert strat.can_short is True
    assert "BTC/USDT:USDT" in strat.custom_stake_weights
    assert "SOL/USDT:USDT" in strat.custom_stake_weights
    assert strat.custom_stake_weights["BTC/USDT:USDT"] == 0.40

    n = 50
    df = pd.DataFrame({
        "open": np.linspace(20, 25, n),
        "high": np.linspace(21, 26, n),
        "low": np.linspace(19, 24, n),
        "close": np.linspace(20.5, 25.5, n),
        "volume": np.full(n, 500.0),
        "macro_trend_4h": np.full(n, 1)
    })

    df_ind = strat.populate_indicators(df, {"pair": "SOL/USDT:USDT"})
    assert "bb_lower" in df_ind.columns
    assert "bb_upper" in df_ind.columns

    df_entry = strat.populate_entry_trend(df_ind, {"pair": "SOL/USDT:USDT"})
    assert "enter_long" in df_entry.columns
    assert "enter_short" in df_entry.columns


def test_option_a_backtest_simulation():
    # Verify execution of Option A logic under BacktestSimulator
    df_h4 = pd.read_csv("data/timeframes/BTCUSD_H4.csv")
    df_m15 = pd.read_csv("data/timeframes/BTCUSD_M15.csv")
    df_h4["timestamp"] = pd.to_datetime(df_h4["timestamp"])
    df_m15["timestamp"] = pd.to_datetime(df_m15["timestamp"])

    df_h4["ema50_h4"] = df_h4["close"].ewm(span=50).mean()
    df_h4["macro_trend"] = np.where(df_h4["close"] > df_h4["ema50_h4"], 1, -1)

    df_m15 = pd.merge_asof(df_m15.sort_values("timestamp"), df_h4[["timestamp", "macro_trend"]].sort_values("timestamp"), on="timestamp", direction="backward")
    df_m15["macro_trend"] = df_m15["macro_trend"].fillna(1)
    df_sub = df_m15.iloc[-2000:].reset_index(drop=True)

    close, high, low, open_p, vol = df_sub["close"], df_sub["high"], df_sub["low"], df_sub["open"], df_sub["volume"]
    macro = df_sub["macro_trend"]

    tr = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
    atr = tr.rolling(14).mean().bfill()
    ema20 = close.ewm(span=20).mean()
    ema50 = close.ewm(span=50).mean()
    typical_p = (high + low + close) / 3.0
    rolling_vwap = (typical_p * vol).rolling(30).sum() / vol.rolling(30).sum().replace(0, 1)

    h_12 = high.rolling(12).max().shift(1)
    l_12 = low.rolling(12).min().shift(1)

    bull = (macro == 1) & (close > open_p) & (close > rolling_vwap) & (ema20 > ema50) & (high >= h_12)
    bear = (macro == -1) & (close < open_p) & (close < rolling_vwap) & (ema20 < ema50) & (low <= l_12)

    sig = pd.DataFrame(index=df_sub.index)
    sig["signal"] = 0
    sig["atr"] = atr
    sig["conviction"] = 85.0
    sig["regime"] = "TREND"
    sig.loc[bull, "signal"] = 1
    sig.loc[bear, "signal"] = -1

    sim = BacktestSimulator(slippage_pct=0.03, taker_fee_pct=0.02, initial_capital=1000.0, order_execution_mode="maker")
    res = sim.run_backtest(df_sub, sig, risk_per_trade_pct=3.0, atr_sl_mult=1.3, atr_tp_mult=2.0)
    assert res["max_drawdown_pct"] <= 10.0
    assert res["final_capital"] > 0

def test_mexc_and_bybit_compatibility():
    import json
    # Verify Bybit configs
    with open("services/freqtrade/user_data/config_option_a.json") as f:
        conf_a_bybit = json.load(f)
    assert conf_a_bybit["exchange"]["name"] == "bybit"
    assert conf_a_bybit["order_types"]["entry"] == "limit"

    with open("services/freqtrade/user_data/config_option_b.json") as f:
        conf_b_bybit = json.load(f)
    assert conf_b_bybit["exchange"]["name"] == "bybit"

    # Verify MEXC configs
    with open("services/freqtrade/user_data/config_option_a_mexc.json") as f:
        conf_a_mexc = json.load(f)
    assert conf_a_mexc["exchange"]["name"] == "mexc"
    assert conf_a_mexc["fee"] == 0.0000
    assert conf_a_mexc["order_types"]["entry"] == "limit"

    with open("services/freqtrade/user_data/config_option_b_mexc.json") as f:
        conf_b_mexc = json.load(f)
    assert conf_b_mexc["exchange"]["name"] == "mexc"
    assert conf_b_mexc["fee"] == 0.0000

    # Verify CCXT data source compatibility
    from services.data_collector.sources.bybit import BybitSource
    from services.data_collector.sources.mexc import MEXCSource
    bybit_src = BybitSource(testnet=True)
    mexc_src = MEXCSource(testnet=True)
    assert bybit_src.exchange.id == "bybit"
    assert mexc_src.exchange.id == "mexc"
