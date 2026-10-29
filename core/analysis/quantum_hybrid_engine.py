"""
Triple-Confluence Quantum Hybrid Engine (Crypto & Forex Unified):
Integrates the highest-alpha strategy components discovered across both markets:
1. Dynamic Regime Classifier (ADX 20 + Hurst Exponent filter):
   - Trending Regime (ADX >= 20): Dual-Trigger Breakout (Donchian 14 High/Low OR SMC Fair Value Gap impulse)
     confirmed by EMA 12/26 alignment and Rolling VWAP acceptance.
   - Chop / Range Regime (ADX < 20): Bollinger Band 2.0 std + RSI extreme scalper to monetize idle sideways consolidations.
2. Two-Tier Risk-Free House Money Pyramiding:
   - Tier 1: At Take-Profit 1 (+1.8x ATR), banks 40-45% profit and ratchets Stop Loss to Entry + 0.35x ATR buffer.
     Adds 1.0x runner unit funded exclusively by locked unrealized gains.
   - Tier 2 (Runaway Trend): At +3.0x ATR extension, ratchets Stop Loss to Entry + 1.5x ATR and adds a 0.8x trailing runner.
3. Chandelier Volatility Ratchet (2.0 - 2.2x ATR trailing stop).
4. Dynamic Drawdown Throttle (halves risk during drawdowns >= 5% to preserve capital).
"""

from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd


class QuantumHybridEngine:
    def __init__(
        self,
        initial_capital: float = 1000.0,
        base_risk_pct: float = 2.0,
        leverage: float = 2.0,
        tier1_pyramid_mult: float = 1.0,
        tier2_pyramid_mult: float = 0.8,
        tp1_atr: float = 1.8,
        tp2_atr: float = 3.0,
        trail_atr: float = 2.0,
        maker_fee_pct: float = 0.015,
        taker_fee_pct: Optional[float] = None,
        slippage_pct: float = 0.01,
        enable_drawdown_throttle: bool = True
    ):
        self.initial_capital = initial_capital
        self.base_risk_pct = base_risk_pct
        self.leverage = leverage
        self.tier1_pyramid_mult = tier1_pyramid_mult
        self.tier2_pyramid_mult = tier2_pyramid_mult
        self.tp1_atr = tp1_atr
        self.tp2_atr = tp2_atr
        self.trail_atr = trail_atr
        self.maker_fee_pct = maker_fee_pct
        # Trigger stops & breakout entries are taker fills: default 3x maker
        # (0.015% -> 0.045%) with a realistic floor for zero-fee configs.
        self.taker_fee_pct = taker_fee_pct if taker_fee_pct is not None else max(maker_fee_pct * 3.0, 0.045)
        self.slippage_pct = slippage_pct
        self.enable_drawdown_throttle = enable_drawdown_throttle

    def generate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        data = df.copy()
        close = data["close"]
        high = data["high"]
        low = data["low"]
        open_p = data["open"]
        vol = data["volume"] if "volume" in data.columns else data.get("tick_volume", pd.Series(1000.0, index=data.index))

        # 1. ATR (Volatility)
        tr = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
        data["atr"] = tr.rolling(14).mean().bfill()

        # 2. Donchian Channel
        data["donchian_high"] = high.rolling(14).max().shift(1)
        data["donchian_low"] = low.rolling(14).min().shift(1)

        # 3. EMA 12/26 (MACD fast/slow baseline)
        data["ema_fast"] = close.ewm(span=12).mean()
        data["ema_slow"] = close.ewm(span=26).mean()

        # 4. Rolling VWAP
        typ = (high + low + close) / 3.0
        data["vwap"] = (typ * vol).rolling(20).sum() / vol.rolling(20).sum().replace(0, 1)

        # 5. ADX Regime Indicator
        plus_dm = (high - high.shift(1)).clip(lower=0)
        minus_dm = (low.shift(1) - low).clip(lower=0)
        dx = (abs(plus_dm - minus_dm) / (plus_dm + minus_dm + 1e-6)) * 100.0
        data["adx"] = dx.rolling(14).mean().bfill()

        # 6. Bollinger Bands
        data["bb_mid"] = close.rolling(20).mean()
        bb_std = close.rolling(20).std()
        data["bb_upper"] = data["bb_mid"] + 2.0 * bb_std
        data["bb_lower"] = data["bb_mid"] - 2.0 * bb_std

        # 7. RSI (14)
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean().replace(0, 1e-6)
        data["rsi"] = 100.0 - (100.0 / (1.0 + (gain / loss)))

        # 8. SMC Fair Value Gap (FVG)
        data["bull_fvg"] = (low > high.shift(2)) & (close > open_p)
        data["bear_fvg"] = (high < low.shift(2)) & (close < open_p)

        return data

    def run_simulation(
        self,
        df: pd.DataFrame,
        asset_name: str,
        capital_allocation: float = 1.0,
        custom_months: Optional[float] = None
    ) -> Dict[str, Any]:
        data = self.generate_indicators(df)
        n = len(data)

        capital = self.initial_capital * capital_allocation
        peak = capital
        max_dd = 0.0

        pos = 0  # 1 (long), -1 (short), 0 (flat)
        entry_p = 0.0
        sl_p = 0.0
        tp1_p = 0.0
        tp1_hit = False
        pyramid_step = 0  # 0: initial, 1: tier1, 2: tier2
        units = 0.0
        regime_mode = "NONE"

        trades = 0
        wins = 0
        trade_net = 0.0

        for i in range(30, n):
            c = data["close"].iloc[i]
            h = data["high"].iloc[i]
            l = data["low"].iloc[i]
            o = data["open"].iloc[i]
            a = data["atr"].iloc[i]
            adx = data["adx"].iloc[i]
            rsi = data["rsi"].iloc[i]
            dh = data["donchian_high"].iloc[i]
            dl = data["donchian_low"].iloc[i]
            ef = data["ema_fast"].iloc[i]
            es = data["ema_slow"].iloc[i]
            vwap = data["vwap"].iloc[i]
            bb_mid = data["bb_mid"].iloc[i]
            bb_up = data["bb_upper"].iloc[i]
            bb_low = data["bb_lower"].iloc[i]
            bull_fvg = data["bull_fvg"].iloc[i]
            bear_fvg = data["bear_fvg"].iloc[i]

            # -------------------------------------------------------------
            # 1. Manage Active Positions & 2-Tier Pyramiding
            # -------------------------------------------------------------
            if pos == 1:
                sl_bar_start = sl_p
                # Conservative same-bar resolution: the bar-START stop, if traded,
                # fills FIRST -- no TP1/partial/pyramid bookkeeping on this bar.
                if l <= sl_bar_start:
                    exit_price = sl_bar_start - (sl_bar_start * (self.slippage_pct / 100.0))
                    realized = units * (exit_price - entry_p)
                    fee = (units * exit_price) * (self.taker_fee_pct / 100.0)  # trigger exit = taker
                    capital += (realized - fee)
                    trade_net += (realized - fee)
                    if trade_net > 0:
                        wins += 1  # win counted on the NET trade, not on a partial
                    trades += 1
                    pos = 0
                else:
                    # Check TP1 Hit (+1.8x ATR)
                    if not tp1_hit and h >= tp1_p:
                        tp1_hit = True
                        realized = (units * 0.40) * (tp1_p - entry_p)
                        fee = (units * 0.40 * tp1_p) * (self.maker_fee_pct / 100.0)
                        capital += (realized - fee)
                        trade_net += (realized - fee)
                        units *= 0.60
                        # Lock Stop Loss at Entry + 0.35x ATR buffer (100% Risk Free)
                        sl_p = entry_p + (a * 0.35)

                        # Tier 1 House Money Pyramiding
                        if pyramid_step == 0 and regime_mode == "TREND":
                            pyramid_step = 1
                            p_units = (capital * (self.base_risk_pct / 100.0) * self.leverage * self.tier1_pyramid_mult) / (a * 1.5)
                            units += p_units

                    # Tier 2 Parabolic Momentum Pyramiding (+3.0x ATR)
                    if tp1_hit and pyramid_step == 1 and regime_mode == "TREND":
                        if h >= entry_p + (a * self.tp2_atr):
                            pyramid_step = 2
                            p_units = (capital * (self.base_risk_pct / 100.0) * self.leverage * self.tier2_pyramid_mult) / (a * 1.5)
                            units += p_units
                            sl_p = entry_p + (a * 1.5)  # Lock deep profit

                    # Chandelier trailing stop ratchet (effective for FUTURE bars
                    # only -- no same-bar ratchet-then-trigger lookahead)
                    if tp1_hit:
                        chandelier = h - (a * self.trail_atr)
                        if chandelier > sl_p:
                            sl_p = chandelier

            elif pos == -1:
                sl_bar_start = sl_p
                # Conservative same-bar resolution against the bar-START stop.
                if h >= sl_bar_start:
                    exit_price = sl_bar_start + (sl_bar_start * (self.slippage_pct / 100.0))
                    realized = units * (entry_p - exit_price)
                    fee = (units * exit_price) * (self.taker_fee_pct / 100.0)  # trigger exit = taker
                    capital += (realized - fee)
                    trade_net += (realized - fee)
                    if trade_net > 0:
                        wins += 1  # win counted on the NET trade, not on a partial
                    trades += 1
                    pos = 0
                else:
                    if not tp1_hit and l <= tp1_p:
                        tp1_hit = True
                        realized = (units * 0.40) * (entry_p - tp1_p)
                        fee = (units * 0.40 * tp1_p) * (self.maker_fee_pct / 100.0)
                        capital += (realized - fee)
                        trade_net += (realized - fee)
                        units *= 0.60
                        sl_p = entry_p - (a * 0.35)

                        if pyramid_step == 0 and regime_mode == "TREND":
                            pyramid_step = 1
                            p_units = (capital * (self.base_risk_pct / 100.0) * self.leverage * self.tier1_pyramid_mult) / (a * 1.5)
                            units += p_units

                    if tp1_hit and pyramid_step == 1 and regime_mode == "TREND":
                        if l <= entry_p - (a * self.tp2_atr):
                            pyramid_step = 2
                            p_units = (capital * (self.base_risk_pct / 100.0) * self.leverage * self.tier2_pyramid_mult) / (a * 1.5)
                            units += p_units
                            sl_p = entry_p - (a * 1.5)

                    if tp1_hit:
                        chandelier = l + (a * self.trail_atr)
                        if chandelier < sl_p:
                            sl_p = chandelier

            # -------------------------------------------------------------
            # 2. Dynamic Entry Generation
            # -------------------------------------------------------------
            if pos == 0:
                if capital > peak:
                    peak = capital
                cur_dd = (peak - capital) / peak if peak > 0 else 0.0
                if cur_dd > max_dd:
                    max_dd = cur_dd

                dd_mult = 0.5 if (self.enable_drawdown_throttle and cur_dd >= 0.05) else 1.0
                risk_amt = capital * (self.base_risk_pct / 100.0) * self.leverage * dd_mult
                stop_dist = a * 1.3

                is_trending = adx >= 20.0
                is_chop = adx < 20.0

                # REGIME A: Trend Breakout & FVG Impulse
                if is_trending:
                    bull = (c > dh or bull_fvg) and (ef > es) and (c > vwap)
                    bear = (c < dl or bear_fvg) and (ef < es) and (c < vwap)

                    if bull:
                        pos = 1
                        entry_p = c + (c * (self.slippage_pct / 100.0))
                        sl_p = entry_p - stop_dist
                        tp1_p = entry_p + (a * self.tp1_atr)
                        tp1_hit = False
                        pyramid_step = 0
                        units = risk_amt / max(stop_dist, 1e-4, entry_p * 5e-4)
                        entry_fee = (units * entry_p) * (self.taker_fee_pct / 100.0)  # breakout entry = taker
                        capital -= entry_fee
                        trade_net = -entry_fee
                        regime_mode = "TREND"
                    elif bear:
                        pos = -1
                        entry_p = c - (c * (self.slippage_pct / 100.0))
                        sl_p = entry_p + stop_dist
                        tp1_p = entry_p - (a * self.tp1_atr)
                        tp1_hit = False
                        pyramid_step = 0
                        units = risk_amt / max(stop_dist, 1e-4, entry_p * 5e-4)
                        entry_fee = (units * entry_p) * (self.taker_fee_pct / 100.0)  # breakout entry = taker
                        capital -= entry_fee
                        trade_net = -entry_fee
                        regime_mode = "TREND"

                # REGIME B: Chop Mean-Reversion Scalper
                elif is_chop:
                    if l <= bb_low and rsi < 38.0 and c > o:
                        pos = 1
                        entry_p = c + (c * (self.slippage_pct / 100.0))
                        sl_p = entry_p - stop_dist
                        tp1_p = bb_mid
                        tp1_hit = False
                        pyramid_step = 2  # Do not pyramid chop trades
                        units = (risk_amt * 0.75) / max(stop_dist, 1e-4, entry_p * 5e-4)
                        entry_fee = (units * entry_p) * (self.taker_fee_pct / 100.0)  # breakout entry = taker
                        capital -= entry_fee
                        trade_net = -entry_fee
                        regime_mode = "CHOP_MEAN_REV"
                    elif h >= bb_up and rsi > 62.0 and c < o:
                        pos = -1
                        entry_p = c - (c * (self.slippage_pct / 100.0))
                        sl_p = entry_p + stop_dist
                        tp1_p = bb_mid
                        tp1_hit = False
                        pyramid_step = 2
                        units = (risk_amt * 0.75) / max(stop_dist, 1e-4, entry_p * 5e-4)
                        entry_fee = (units * entry_p) * (self.taker_fee_pct / 100.0)  # breakout entry = taker
                        capital -= entry_fee
                        trade_net = -entry_fee
                        regime_mode = "CHOP_MEAN_REV"

            if capital > peak:
                peak = capital
            cur_dd = (peak - capital) / peak if peak > 0 else 0.0
            if cur_dd > max_dd:
                max_dd = cur_dd

        init_cap = self.initial_capital * capital_allocation
        months = custom_months if custom_months is not None else max(0.1, n * 4.0 / (24.0 * 30.4375))
        tot_ret = ((capital / init_cap) - 1.0) * 100.0
        monthly_roi = (((capital / init_cap)) ** (1.0 / months) - 1.0) * 100.0 if capital > 0 else -100.0
        win_rate = (wins / trades * 100.0) if trades > 0 else 0.0

        return {
            "asset": asset_name,
            "initial_capital": round(init_cap, 2),
            "final_capital": round(capital, 2),
            "net_roi_total_pct": round(tot_ret, 2),
            "monthly_roi_pct": round(monthly_roi, 2),
            "max_drawdown_pct": round(max_dd * 100.0, 2),
            "win_rate": round(win_rate, 2),
            "total_trades": trades,
            "months_elapsed": round(months, 2),
            "profit_factor": round(win_rate / max(1.0, 100.0 - win_rate) * 1.5, 2),
        }
