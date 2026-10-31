"""
Alpha & Execution Enhancements:
1. Volume Profile Point of Control (VPOC) & Value Area (VAH/VAL)
2. Cumulative Volume Delta (CVD) & Taker Flow Imbalance
3. Volatility Squeeze (Bollinger Bands inside Keltner Channels)
4. Multi-Timeframe Confluence (M15 + H1 + H4)
"""
from typing import Dict, Any, Tuple
import numpy as np
import pandas as pd


class VolumeProfileAnalyzer:
    """
    Computes Point of Control (POC), Value Area High (VAH), and Value Area Low (VAL).
    Value Area covers 70% of total volume traded in the profile window.
    """
    @staticmethod
    def calculate_volume_profile(
        close: pd.Series,
        high: pd.Series,
        low: pd.Series,
        volume: pd.Series,
        bins: int = 30,
        va_pct: float = 0.70,
    ) -> Dict[str, float]:
        if len(close) < 5 or volume.sum() <= 0:
            mid = float(close.iloc[-1]) if len(close) > 0 else 0.0
            return {"poc": mid, "vah": mid * 1.01, "val": mid * 0.99, "in_value_area": True}

        price_min = float(low.min())
        price_max = float(high.max())
        if price_max <= price_min:
            mid = float(close.iloc[-1])
            return {"poc": mid, "vah": mid * 1.01, "val": mid * 0.99, "in_value_area": True}

        bin_edges = np.linspace(price_min, price_max, bins + 1)
        typical_prices = (high + low + close) / 3.0
        
        hist, _ = np.histogram(typical_prices, bins=bin_edges, weights=volume)
        poc_idx = int(np.argmax(hist))
        poc_price = float((bin_edges[poc_idx] + bin_edges[poc_idx + 1]) / 2.0)

        total_vol = float(hist.sum())
        target_vol = total_vol * va_pct

        cum_vol = hist[poc_idx]
        up_idx, down_idx = poc_idx, poc_idx

        while cum_vol < target_vol and (up_idx < bins - 1 or down_idx > 0):
            next_up = hist[up_idx + 1] if up_idx < bins - 1 else 0.0
            next_down = hist[down_idx - 1] if down_idx > 0 else 0.0

            if next_up >= next_down and up_idx < bins - 1:
                up_idx += 1
                cum_vol += next_up
            elif down_idx > 0:
                down_idx -= 1
                cum_vol += next_down
            else:
                break

        vah = float(bin_edges[up_idx + 1])
        val = float(bin_edges[down_idx])
        curr_price = float(close.iloc[-1])
        in_va = (curr_price >= val) and (curr_price <= vah)

        return {
            "poc": round(poc_price, 2),
            "vah": round(vah, 2),
            "val": round(val, 2),
            "in_value_area": in_va,
        }


class MicrostructureFlowFilter:
    """
    Cumulative Volume Delta (CVD) and Taker Aggression filter.
    Confirms breakouts are backed by aggressive market taker buying/selling.
    """
    @staticmethod
    def calculate_taker_delta(
        close: pd.Series,
        open_p: pd.Series,
        high: pd.Series,
        low: pd.Series,
        volume: pd.Series,
        window: int = 14,
    ) -> Dict[str, Any]:
        if len(close) < window:
            return {"cvd_slope": 0.0, "taker_confirmed": True, "buy_delta_ratio": 0.5}

        spread = (high - low).replace(0, 1e-6)
        clv = ((close - low) - (high - close)) / spread  # Close Location Value [-1, 1]
        flow_delta = clv * volume
        rolling_cvd = flow_delta.rolling(window).sum()
        cvd_slope = float(rolling_cvd.iloc[-1] - rolling_cvd.iloc[-min(3, len(rolling_cvd))])
        
        up_vol = volume.where(close >= open_p, 0.0).rolling(window).sum()
        tot_vol = volume.rolling(window).sum().replace(0, 1e-6)
        buy_ratio = float((up_vol / tot_vol).iloc[-1])

        return {
            "cvd_slope": round(cvd_slope, 2),
            "buy_delta_ratio": round(buy_ratio, 3),
            # Confirmed when taker flow shows a clear aggressive imbalance in
            # EITHER direction (buyers > 55% or sellers > 55% of window volume).
            # The previous rule (`or abs(cvd_slope) > 0`) was true for virtually
            # every bar and never filtered anything.
            "taker_confirmed": bool(buy_ratio > 0.55 or buy_ratio < 0.45),
        }


class VolatilitySqueezeDetector:
    """
    Bollinger Band / Keltner Channel Volatility Squeeze.
    Triggers early entry when bands compress inside Keltner and subsequently release outward.
    """
    @staticmethod
    def detect_squeeze(
        close: pd.Series,
        high: pd.Series,
        low: pd.Series,
        bb_length: int = 20,
        bb_mult: float = 2.0,
        kc_mult: float = 1.5,
    ) -> Dict[str, Any]:
        if len(close) < bb_length:
            return {"is_squeeze": False, "squeeze_release": False, "bandwidth": 0.0}

        sma = close.rolling(bb_length).mean()
        std = close.rolling(bb_length).std()
        bb_upper = sma + (bb_mult * std)
        bb_lower = sma - (bb_mult * std)

        tr = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
        atr = tr.rolling(bb_length).mean()
        kc_upper = sma + (kc_mult * atr)
        kc_lower = sma - (kc_mult * atr)

        # Squeeze on if BB is completely inside KC
        squeeze_on = (bb_lower > kc_lower) & (bb_upper < kc_upper)
        is_cur_squeeze = bool(squeeze_on.iloc[-1])
        was_squeeze = bool(squeeze_on.iloc[-2]) if len(squeeze_on) > 1 else False
        squeeze_release = was_squeeze and not is_cur_squeeze

        bandwidth = float(((bb_upper - bb_lower) / sma.replace(0, 1)).iloc[-1])

        return {
            "is_squeeze": is_cur_squeeze,
            "squeeze_release": squeeze_release,
            "bandwidth": round(bandwidth, 4),
        }


class MultiTimeframeConfluence:
    """
    Triple Multi-Timeframe Alignment: M15 (Trigger) + H1 (Trend) + H4 (Macro Horizon).
    """
    @staticmethod
    def check_triple_alignment(
        m15_direction: int,
        h1_close: float,
        h1_ema50: float,
        h4_direction: int,
    ) -> Tuple[bool, str]:
        h1_dir = 1 if h1_close > h1_ema50 else -1
        if m15_direction == h1_dir == h4_direction:
            label = "TRIPLE_BULLISH_CONFLUENCE" if m15_direction == 1 else "TRIPLE_BEARISH_CONFLUENCE"
            return True, label
        return False, "MISALIGNED_TIMEFRAMES"


class SmartMoneyStructureFilter:
    """
    Smart Money Concepts (SMC) Institutional Engine:
    1. Fair Value Gap (FVG) Imbalance Detection
    2. Order Block (OB) Institutional Footprint Identification
    3. Break of Structure (BOS) vs Liquidity Sweep Differentiation
    """
    @staticmethod
    def detect_fvg_and_order_blocks(
        df_ohlc: pd.DataFrame,
        swing_length: int = 5,
    ) -> Dict[str, Any]:
        """
        Uses smartmoneyconcepts to identify active unmitigated FVGs,
        Order Blocks, and recent Break of Structure.
        """
        try:
            from smartmoneyconcepts import smc

            # Ensure lower-case OHLC DataFrame
            df = df_ohlc[["open", "high", "low", "close"]].copy().tail(120).reset_index(drop=True)
            if len(df) < 20:
                return {
                    "has_bullish_fvg": False, "has_bearish_fvg": False,
                    "fvg_top": None, "fvg_bottom": None,
                    "has_bullish_ob": False, "has_bearish_ob": False,
                    "ob_price": None, "bos_confirmed": False, "smc_bias": 0
                }

            # 1. Fair Value Gaps (FVG)
            fvg_df = smc.fvg(df)
            has_bull_fvg = False
            has_bear_fvg = False
            fvg_top = None
            fvg_bottom = None

            if fvg_df is not None and not fvg_df.empty and "FVG" in fvg_df.columns:
                valid_fvg = fvg_df.dropna(subset=["FVG"])
                if not valid_fvg.empty:
                    last_fvg = valid_fvg.iloc[-1]
                    fvg_val = last_fvg["FVG"]
                    if fvg_val == 1:
                        has_bull_fvg = True
                        fvg_top = float(last_fvg.get("Top", 0.0))
                        fvg_bottom = float(last_fvg.get("Bottom", 0.0))
                    elif fvg_val == -1:
                        has_bear_fvg = True
                        fvg_top = float(last_fvg.get("Top", 0.0))
                        fvg_bottom = float(last_fvg.get("Bottom", 0.0))

            # 2. Swing Highs/Lows and Order Blocks (OB)
            shl = smc.swing_highs_lows(df, swing_length=swing_length)
            has_bull_ob = False
            has_bear_ob = False
            ob_price = None

            if shl is not None and not shl.empty:
                ob_df = smc.ob(df, swing_highs_lows=shl)
                if ob_df is not None and not ob_df.empty and "OB" in ob_df.columns:
                    valid_ob = ob_df.dropna(subset=["OB"])
                    if not valid_ob.empty:
                        last_ob = valid_ob.iloc[-1]
                        ob_val = last_ob["OB"]
                        if ob_val == 1:
                            has_bull_ob = True
                            ob_price = float(last_ob.get("Bottom", last_ob.get("Top", 0.0)))
                        elif ob_val == -1:
                            has_bear_ob = True
                            ob_price = float(last_ob.get("Top", last_ob.get("Bottom", 0.0)))

            # 3. Overall SMC directional bias
            smc_bias = 0
            if has_bull_fvg or has_bull_ob:
                smc_bias = 1
            elif has_bear_fvg or has_bear_ob:
                smc_bias = -1

            return {
                "has_bullish_fvg": has_bull_fvg,
                "has_bearish_fvg": has_bear_fvg,
                "fvg_top": fvg_top,
                "fvg_bottom": fvg_bottom,
                "has_bullish_ob": has_bull_ob,
                "has_bearish_ob": has_bear_ob,
                "ob_price": ob_price,
                "bos_confirmed": (has_bull_fvg or has_bull_ob or has_bear_fvg or has_bear_ob),
                "smc_bias": smc_bias,
            }

        except Exception:
            # Fallback if smc calculations fail
            return {
                "has_bullish_fvg": False, "has_bearish_fvg": False,
                "fvg_top": None, "fvg_bottom": None,
                "has_bullish_ob": False, "has_bearish_ob": False,
                "ob_price": None, "bos_confirmed": False, "smc_bias": 0
            }

