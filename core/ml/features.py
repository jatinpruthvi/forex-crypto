"""
Feature Engineering Pipeline:
Generates 22 features across Price, Volume, Regime, Market Signals, and Time for ML.
"""
from typing import Tuple, Dict, Any, Optional
import numpy as np
import pandas as pd


class FeatureEngineer:
    def __init__(self):
        pass

    def create_features(
        self,
        df_ohlcv: pd.DataFrame,
        signals_dict: Optional[Dict[str, float]] = None,
        regime_info: Optional[Dict[str, Any]] = None,
    ) -> pd.DataFrame:
        """
        Calculates 22 features matching PRD section 4.4.1.
        """
        df = df_ohlcv.copy()
        for col in ["open", "high", "low", "close", "volume"]:
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col}")

        close = df["close"]
        high = df["high"]
        low = df["low"]
        open_p = df["open"]
        vol = df["volume"]

        # 1-3. Returns
        df["returns_1h"] = close.pct_change(1).fillna(0.0)
        df["returns_4h"] = close.pct_change(4).fillna(0.0)
        df["returns_24h"] = close.pct_change(24).fillna(0.0)

        # 4. Volatility 20
        df["volatility_20"] = df["returns_1h"].rolling(window=20, min_periods=1).std().fillna(0.0)

        # 5. Volatility ratio (vol_20 / vol_100)
        vol_100 = df["returns_1h"].rolling(window=100, min_periods=1).std().replace(0, 1e-6)
        df["volatility_ratio"] = (df["volatility_20"] / vol_100).fillna(1.0)

        # 6. Price position in 100-bar range
        high_100 = high.rolling(window=100, min_periods=1).max()
        low_100 = low.rolling(window=100, min_periods=1).min()
        denom = (high_100 - low_100).apply(lambda v: 1e-6 if abs(v) < 1e-6 else v)
        df["price_position"] = ((close - low_100) / denom).clip(0.0, 1.0).fillna(0.5)

        # 7. Trend strength: abs(EMA21 - EMA50) / ATR14
        ema21 = close.ewm(span=21, adjust=False).mean()
        ema50 = close.ewm(span=50, adjust=False).mean()
        tr = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1)))).fillna(0.0)
        atr14 = tr.rolling(window=14, min_periods=1).mean().replace(0, 1e-6)
        df["trend_strength"] = (abs(ema21 - ema50) / atr14).fillna(0.0)

        # 8. Momentum: ROC 14
        c_shift = close.shift(14).replace(0, 1e-6)
        df["momentum"] = ((close - c_shift) / c_shift).fillna(0.0)

        # 9. Volume ratio: current vol / SMA(vol, 20)
        vol_sma20 = vol.rolling(window=20, min_periods=1).mean().replace(0, 1e-6)
        df["volume_ratio"] = (vol / vol_sma20).fillna(1.0)

        # 10. Candle body ratio
        hl_diff = (high - low).apply(lambda v: 1e-6 if abs(v) < 1e-6 else v)
        df["candle_body"] = (abs(close - open_p) / hl_diff).clip(0.0, 1.0).fillna(0.5)

        # 11. Upper wick ratio
        max_oc = np.maximum(open_p, close)
        df["upper_wick"] = ((high - max_oc) / hl_diff).clip(0.0, 1.0).fillna(0.0)

        # 12. Lower wick ratio
        min_oc = np.minimum(open_p, close)
        df["lower_wick"] = ((min_oc - low) / hl_diff).clip(0.0, 1.0).fillna(0.0)

        # 13-15. Regime features
        h_val = regime_info.get("hurst", 0.5) if regime_info else 0.5
        ap_val = regime_info.get("atr_percentile", 50.0) if regime_info else 50.0
        r_str = regime_info.get("regime", "TRANSITION") if regime_info else "TRANSITION"

        regime_map = {"TREND": 1, "RANGE": 2, "BREAKOUT": 3, "SQUEEZE": 4, "CRISIS": 5, "TRANSITION": 0}
        df["hurst"] = h_val
        df["atr_percentile"] = ap_val
        df["regime_encoded"] = regime_map.get(r_str, 0)

        # 16-20. Signal features
        sig = signals_dict or {}
        df["funding_rate"] = sig.get("funding_rate", 0.0)
        df["oi_change_pct"] = sig.get("oi_change_pct", 0.0)
        df["long_short_ratio"] = sig.get("long_short_ratio", 1.0)
        df["taker_ratio"] = sig.get("taker_ratio", 1.0)
        df["conviction"] = sig.get("conviction", 50.0)

        # Microstructure Flow & CVD Divergence proxy:
        # Approximate Cumulative Volume Delta (CVD) using signed candle volume
        signed_vol = np.where(close >= open_p, vol, -vol)
        cvd_20 = pd.Series(signed_vol, index=df.index).rolling(window=20, min_periods=1).sum()
        cvd_norm = cvd_20 / (vol.rolling(window=20, min_periods=1).sum().replace(0, 1e-6))
        price_ret_20 = (close - close.shift(20).fillna(close.iloc[0])) / (close.shift(20).replace(0, 1e-6))
        # CVD Divergence: negative if price is rising but volume delta is falling (absorption/exhaustion)
        df["cvd_divergence"] = (cvd_norm - price_ret_20).fillna(0.0)

        # 21-22. Time features
        if "timestamp" in df.columns:
            dt_series = pd.to_datetime(df["timestamp"])
            df["hour_of_day"] = dt_series.dt.hour
            # London (07:00-16:00 UTC) & NY (13:00-20:00 UTC) active hours
            df["is_london_ny"] = ((df["hour_of_day"] >= 7) & (df["hour_of_day"] <= 20)).astype(int)
            # Weekend liquidity thinning flag
            df["is_weekend"] = (dt_series.dt.dayofweek >= 5).astype(int)
        else:
            df["hour_of_day"] = 12
            df["is_london_ny"] = 1
            df["is_weekend"] = 0

        # 23-28. Institutional TA & SMC Indicators (ta & smartmoneyconcepts)
        try:
            import ta
            df["ta_rsi_14"] = ta.momentum.rsi(close, window=14).fillna(50.0) / 100.0
            df["ta_mfi_14"] = ta.volume.money_flow_index(high, low, close, vol, window=14).fillna(50.0) / 100.0
            df["ta_adx_14"] = ta.trend.adx(high, low, close, window=14).fillna(20.0) / 100.0
            bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
            df["ta_bb_pband"] = bb.bollinger_pband().fillna(0.5)
            df["ta_bb_wband"] = bb.bollinger_wband().fillna(0.1)
        except Exception:
            df["ta_rsi_14"] = 0.5
            df["ta_mfi_14"] = 0.5
            df["ta_adx_14"] = 0.2
            df["ta_bb_pband"] = 0.5
            df["ta_bb_wband"] = 0.1

        try:
            from core.signals.alpha_enhancements import SmartMoneyStructureFilter
            smc_res = SmartMoneyStructureFilter.detect_fvg_and_order_blocks(df)
            df["smc_bias"] = smc_res.get("smc_bias", 0)
        except Exception:
            df["smc_bias"] = 0

        feature_cols = [
            "returns_1h", "returns_4h", "returns_24h", "volatility_20", "volatility_ratio",
            "price_position", "trend_strength", "momentum", "volume_ratio", "candle_body",
            "upper_wick", "lower_wick", "hurst", "atr_percentile", "regime_encoded",
            "funding_rate", "oi_change_pct", "long_short_ratio", "taker_ratio", "conviction",
            "cvd_divergence", "hour_of_day", "is_london_ny", "is_weekend",
            "ta_rsi_14", "ta_mfi_14", "ta_adx_14", "ta_bb_pband", "ta_bb_wband", "smc_bias"
        ]
        return df[feature_cols]

    def create_labels(self, df_ohlcv: pd.DataFrame, forward_bars: int = 12, threshold_pct: float = 1.0) -> pd.Series:
        """
        Binary labeling: 1 if price moves >threshold_pct up in forward_bars,
        0 if moves >threshold_pct down, else -1 (dropped).
        """
        close = df_ohlcv["close"]
        forward_returns = (close.shift(-forward_bars) - close) / close * 100.0

        labels = pd.Series(index=df_ohlcv.index, dtype=int)
        labels[forward_returns >= threshold_pct] = 1
        labels[forward_returns <= -threshold_pct] = 0
        labels[(forward_returns < threshold_pct) & (forward_returns > -threshold_pct)] = -1
        labels.fillna(-1, inplace=True)
        return labels
