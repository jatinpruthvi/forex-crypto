"""
Regime Detector module implementing Hurst Exponent (R/S) and ATR Percentile Rank.
Classifies market into: TREND, RANGE, BREAKOUT, SQUEEZE, CRISIS, or TRANSITION.
"""
from typing import Tuple, Dict, Any
import numpy as np
import pandas as pd


class RegimeDetector:
    def __init__(
        self,
        hurst_window: int = 100,
        atr_window: int = 200,
        trend_threshold: float = 0.55,
        range_threshold: float = 0.45,
    ):
        self.hurst_window = hurst_window
        self.atr_window = atr_window
        self.trend_threshold = trend_threshold
        self.range_threshold = range_threshold

    @staticmethod
    def calculate_hurst(series: np.ndarray) -> float:
        """
        Fast Rescaled Range (R/S) Hurst Exponent calculation.
        """
        n = len(series)
        if n < 20:
            return 0.5

        # Log returns
        returns = np.diff(np.log(np.maximum(series, 1e-8)))
        if len(returns) < 10:
            return 0.5

        # Sub-sample lags
        max_k = min(len(returns) // 2, 64)
        if max_k < 8:
            return 0.5

        lags = [8, 16, 32, max_k]
        lags = sorted(list(set([lag for lag in lags if lag <= len(returns)])))
        if len(lags) < 2:
            return 0.5

        rs_values = []
        for lag in lags:
            num_chunks = len(returns) // lag
            if num_chunks == 0:
                continue
            rs_chunks = []
            for i in range(num_chunks):
                chunk = returns[i * lag : (i + 1) * lag]
                std = np.std(chunk)
                if std < 1e-12:
                    continue
                mean = np.mean(chunk)
                y = np.cumsum(chunk - mean)
                r = np.max(y) - np.min(y)
                rs_chunks.append(r / std)
            if rs_chunks:
                rs_values.append((lag, np.mean(rs_chunks)))

        if len(rs_values) < 2:
            return 0.5

        x = np.log([item[0] for item in rs_values])
        y = np.log([item[1] for item in rs_values])
        poly = np.polyfit(x, y, 1)
        h = float(poly[0])
        return max(0.0, min(1.0, h))

    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate Average True Range."""
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values

        tr1 = high - low
        tr2 = np.abs(high - np.roll(close, 1))
        tr3 = np.abs(low - np.roll(close, 1))
        tr2[0] = tr1[0]
        tr3[0] = tr1[0]

        tr = np.maximum(tr1, np.maximum(tr2, tr3))
        atr = pd.Series(tr, index=df.index).rolling(window=period, min_periods=1).mean()
        return atr

    def detect(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculates hurst, atr_percentile, and regime for each candle in df.
        """
        res = df.copy()
        if "close" not in res.columns:
            raise ValueError("DataFrame must contain 'close' column")

        close = res["close"].values
        n = len(res)

        hurst_vals = np.full(n, 0.5, dtype=float)
        atr = self.calculate_atr(res, period=14).values

        # Rolling ATR percentile rank over atr_window
        atr_pct_vals = np.full(n, 50.0, dtype=float)
        for i in range(n):
            start_atr = max(0, i - self.atr_window + 1)
            window_atr = atr[start_atr : i + 1]
            if len(window_atr) > 1:
                current = atr[i]
                pct = (np.sum(window_atr <= current) / len(window_atr)) * 100.0
                atr_pct_vals[i] = pct

            # Hurst calculation on rolling window
            if i >= self.hurst_window:
                w_series = close[i - self.hurst_window : i + 1]
                hurst_vals[i] = self.calculate_hurst(w_series)
            elif i >= 30:
                hurst_vals[i] = self.calculate_hurst(close[: i + 1])

        res["hurst"] = hurst_vals
        res["atr_percentile"] = atr_pct_vals

        regimes = []
        for h, ap in zip(hurst_vals, atr_pct_vals):
            regimes.append(self.classify_regime(h, ap))

        res["regime"] = regimes
        return res

    def classify_regime(self, hurst: float, atr_pct: float) -> str:
        """
        2x2 Matrix mapping Hurst & ATR percentile to regime.
        """
        if atr_pct >= 95.0:
            return "CRISIS"
        if atr_pct < 20.0:
            return "SQUEEZE"
        if atr_pct >= 80.0:
            return "BREAKOUT"

        # Normal volatility (20 <= atr_pct < 80)
        if hurst > self.trend_threshold:
            return "TREND"
        if hurst < self.range_threshold:
            return "RANGE"
        return "TRANSITION"

    def get_latest_regime(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Classify the latest candle only."""
        classified = self.detect(df)
        latest = classified.iloc[-1]
        return {
            "regime": str(latest["regime"]),
            "hurst": float(latest["hurst"]),
            "atr_percentile": float(latest["atr_percentile"]),
        }
