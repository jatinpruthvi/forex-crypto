"""
Signal Generation Route:
Processes incoming OHLCV + Account info through:
1. Drawdown & Kill-Switch Guard
2. Event Calendar Filter (news lockouts)
3. Regime Detector (Hurst + ATR percentile)
4. Signal Fusion Engine (Conviction 0-100)
5. ML Filter (XGBoost prediction probability)
6. Dynamic Position Sizing (Lots & ATR stops)
"""
from fastapi import APIRouter, HTTPException
from datetime import datetime, timezone
import pandas as pd
import numpy as np

from services.brain_api.models.request import SignalRequest
from services.brain_api.models.response import SignalResponse

from core.regime.detector import RegimeDetector
from core.signals.fusion import SignalFusion
from core.signals.event_filter import EventFilter
from core.signals.cross_asset import CrossAssetMonitor
from core.risk.dd_protocol import DrawdownProtocol
from core.risk.kill_switch import KillSwitchManager
from core.risk.position_sizer import PositionSizer
from core.ml.predict import MLPredictor
from core.ml.features import FeatureEngineer

router = APIRouter()

# Instantiate singletons
regime_detector = RegimeDetector()
signal_fusion = SignalFusion()
event_filter = EventFilter()
cross_asset_monitor = CrossAssetMonitor()
dd_protocol = DrawdownProtocol()
kill_switch_manager = KillSwitchManager()
position_sizer = PositionSizer(default_risk_pct=0.5)
ml_predictor = MLPredictor()
feature_engineer = FeatureEngineer()

# Global state tracker
system_state = {
    "starting_equity": 10000.0,
    "last_signal": {},
    "regimes": {},
}


@router.post("/signal", response_model=SignalResponse)
async def generate_signal(req: SignalRequest):
    now_utc = datetime.now(timezone.utc)
    timestamp_str = now_utc.isoformat()

    # 1. Update starting equity baseline if initial
    if system_state["starting_equity"] <= 0:
        system_state["starting_equity"] = req.account_equity

    # 2. Check Drawdown Protocol
    dd_status = dd_protocol.evaluate(
        starting_equity=system_state["starting_equity"],
        current_equity=req.account_equity,
    )

    if dd_status["level"] == "BLACK":
        resp = SignalResponse(
            action="CLOSE_ALL",
            symbol="ALL",
            confidence=0,
            reason=dd_status["reason"],
            regime="CRISIS",
            risk=dd_status,
            expiry_seconds=0,
            timestamp=timestamp_str,
        )
        system_state["last_signal"] = resp.dict()
        return resp

    if dd_status["level"] == "RED":
        resp = SignalResponse(
            action="HOLD",
            symbol=req.symbol,
            confidence=0,
            reason=dd_status["reason"],
            regime="TRANSITION",
            risk=dd_status,
            expiry_seconds=3600,
            timestamp=timestamp_str,
        )
        system_state["last_signal"] = resp.dict()
        return resp

    # 3. Check High-Impact News Window
    is_news, news_event = event_filter.is_high_impact_window(req.symbol, now_utc, window_minutes=30)
    if is_news and news_event:
        title = news_event.get("title", "High-Impact News")
        resp = SignalResponse(
            action="HOLD",
            symbol=req.symbol,
            confidence=20,
            reason=f"News Event Filter: {title} within +/- 30m lockout",
            regime="TRANSITION",
            risk=dd_status,
            expiry_seconds=1800,
            timestamp=timestamp_str,
        )
        system_state["last_signal"] = resp.dict()
        return resp

    # 4. Parse OHLCV bars into DataFrame
    if not req.ohlcv or len(req.ohlcv) < 30:
        return SignalResponse(
            action="HOLD",
            symbol=req.symbol,
            reason="Insufficient OHLCV data (<30 bars)",
            regime="UNKNOWN",
            risk=dd_status,
            expiry_seconds=3600,
            timestamp=timestamp_str,
        )

    # Format dataframe
    cols = ["timestamp", "open", "high", "low", "close", "volume"]
    sample_len = len(req.ohlcv[0])
    if sample_len == 6:
        df = pd.DataFrame(req.ohlcv, columns=cols)
    elif sample_len == 5:
        df = pd.DataFrame(req.ohlcv, columns=["open", "high", "low", "close", "volume"])
        df["timestamp"] = [i for i in range(len(df))]
    else:
        raise HTTPException(status_code=400, detail="Invalid OHLCV format, expected 5 or 6 items per bar")

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    # 5. Regime Detection
    regime_info = regime_detector.get_latest_regime(df)
    current_regime = regime_info["regime"]
    system_state["regimes"][req.symbol] = current_regime

    if current_regime in ["CRISIS", "SQUEEZE"]:
        reason_msg = "Regime CRISIS (extreme volatility)" if current_regime == "CRISIS" else "Regime SQUEEZE (wait for breakout)"
        resp = SignalResponse(
            action="HOLD",
            symbol=req.symbol,
            reason=reason_msg,
            regime=current_regime,
            regime_detail=regime_info,
            risk=dd_status,
            expiry_seconds=3600,
            timestamp=timestamp_str,
        )
        system_state["last_signal"] = resp.dict()
        return resp

    # 6. Signal Fusion (Funding, OI, L/S, Taker)
    price_change = (df["close"].iloc[-1] - df["close"].iloc[-2]) / df["close"].iloc[-2] * 100.0 if len(df) > 1 else 0.0
    fusion_result = signal_fusion.calculate_conviction(
        req.symbol,
        price_change_pct=price_change,
        signals_override=req.signals_override,
    )
    conviction = fusion_result["conviction"]
    signal_dir = fusion_result["direction"]

    # Conviction minimum constraint
    conv_min = dd_status["conviction_min"]
    if conviction < conv_min:
        resp = SignalResponse(
            action="HOLD",
            symbol=req.symbol,
            confidence=int(conviction),
            reason=f"Conviction ({conviction:.1f}) below threshold ({conv_min:.1f})",
            regime=current_regime,
            regime_detail=regime_info,
            conviction_breakdown=fusion_result["breakdown"],
            risk=dd_status,
            expiry_seconds=3600,
            timestamp=timestamp_str,
        )
        system_state["last_signal"] = resp.dict()
        return resp

    # 7. ML Probability Filter
    features_df = feature_engineer.create_features(
        df,
        signals_dict={**fusion_result["signals"], "conviction": conviction},
        regime_info=regime_info,
    )
    ml_prob = ml_predictor.predict_probability(features_df)

    # ML minimum threshold constraint
    ml_min = dd_status["ml_threshold"]
    if ml_prob < ml_min:
        resp = SignalResponse(
            action="HOLD",
            symbol=req.symbol,
            confidence=int(conviction),
            reason=f"ML probability ({ml_prob:.2f}) below threshold ({ml_min:.2f})",
            regime=current_regime,
            regime_detail=regime_info,
            ml_probability=round(ml_prob, 3),
            conviction_breakdown=fusion_result["breakdown"],
            risk=dd_status,
            expiry_seconds=3600,
            timestamp=timestamp_str,
        )
        system_state["last_signal"] = resp.dict()
        return resp

    # 8. Technical Indicator Rules by Regime
    latest_close = df["close"].iloc[-1]
    ema21 = df["close"].ewm(span=21, adjust=False).mean().iloc[-1]
    ema50 = df["close"].ewm(span=50, adjust=False).mean().iloc[-1]
    tr = np.maximum(df["high"] - df["low"], np.maximum(abs(df["high"] - df["close"].shift(1)), abs(df["low"] - df["close"].shift(1))))
    atr = tr.rolling(window=14, min_periods=1).mean().iloc[-1]
    if atr <= 0:
        atr = latest_close * 0.005

    action = "HOLD"
    reason_parts = [f"Regime {current_regime}", f"Conviction {conviction:.0f}"]

    if current_regime == "TREND":
        ema50_series = df["close"].ewm(span=50, adjust=False).mean()
        ema50_slope_up = ema50_series.iloc[-1] > ema50_series.iloc[-4] if len(df) > 4 else True
        ema50_slope_down = ema50_series.iloc[-1] < ema50_series.iloc[-4] if len(df) > 4 else True

        # Calculate 30-period rolling VWAP for institutional bias
        typical_p = (df["high"] + df["low"] + df["close"]) / 3.0
        rolling_vol = df["volume"].rolling(30, min_periods=1).sum().replace(0, 1)
        rolling_vwap = (typical_p * df["volume"]).rolling(30, min_periods=1).sum() / rolling_vol
        latest_vwap = rolling_vwap.iloc[-1]

        if ema21 > ema50 and ema50_slope_up and latest_close > latest_vwap and signal_dir in ["LONG", "NEUTRAL"]:
            action = "BUY"
            reason_parts.append("Bullish EMA trend + VWAP institutional confirmation")
        elif ema21 < ema50 and ema50_slope_down and latest_close < latest_vwap and signal_dir in ["SHORT", "NEUTRAL"]:
            action = "SELL"
            reason_parts.append("Bearish EMA trend + VWAP institutional confirmation")
    elif current_regime == "RANGE":
        sma20 = df["close"].rolling(window=20, min_periods=1).mean().iloc[-1]
        std20 = df["close"].rolling(window=20, min_periods=1).std().iloc[-1]
        lower_bb = sma20 - (2.0 * std20)
        upper_bb = sma20 + (2.0 * std20)

        if latest_close <= lower_bb and signal_dir != "SHORT":
            action = "BUY"
            reason_parts.append("Mean Reversion Lower BB Touch")
        elif latest_close >= upper_bb and signal_dir != "LONG":
            action = "SELL"
            reason_parts.append("Mean Reversion Upper BB Touch")
    elif current_regime == "BREAKOUT":
        highest_20 = df["high"].iloc[-21:-1].max() if len(df) > 20 else df["high"].max()
        lowest_20 = df["low"].iloc[-21:-1].min() if len(df) > 20 else df["low"].min()

        if latest_close > highest_20 and signal_dir != "SHORT":
            action = "BUY"
            reason_parts.append("Donchian Breakout High")
        elif latest_close < lowest_20 and signal_dir != "LONG":
            action = "SELL"
            reason_parts.append("Donchian Breakout Low")

    if action == "HOLD":
        resp = SignalResponse(
            action="HOLD",
            symbol=req.symbol,
            confidence=int(conviction),
            reason=f"Technical condition not satisfied for regime {current_regime}",
            regime=current_regime,
            regime_detail=regime_info,
            ml_probability=round(ml_prob, 3),
            conviction_breakdown=fusion_result["breakdown"],
            risk=dd_status,
            expiry_seconds=3600,
            timestamp=timestamp_str,
        )
        system_state["last_signal"] = resp.dict()
        return resp

    # 10. Stop Loss & Take Profit calculations
    # Optimized Strategy Parameters from Ralph Loop:
    # sl_mult = 1.6x ATR, tp_mult = 2.4x ATR, trailing = 2.5x ATR
    sl_mult = 1.6
    tp_mult = 2.4
    sl_dist = atr * sl_mult
    tp_dist = atr * tp_mult

    if action == "BUY":
        sl = round(latest_close - sl_dist, 5)
        tp = round(latest_close + tp_dist, 5)
    else:
        sl = round(latest_close + sl_dist, 5)
        tp = round(latest_close - tp_dist, 5)

    # 11. Limit Order Routing Optimization (Post-Only Maker Pricing)
    # Market taker orders incur 0.055% fee + 0.1% slippage.
    # By placing passive post-only limit orders at or inside the best bid/ask (0.05x ATR offset),
    # the system captures maker rebate (-0.02% fee) and eliminates slippage.
    limit_entry_price = latest_close
    limit_offset = atr * 0.05
    if action == "BUY":
        limit_entry_price = round(latest_close - limit_offset, 5)
    elif action == "SELL":
        limit_entry_price = round(latest_close + limit_offset, 5)

    # 12. Position Sizing with ML Dynamic Conviction Adjustment & Covariance Deflation
    # If ML strongly confirms direction (BUY & prob >= 0.53 or SELL & prob <= 0.47) -> boost 1.35x
    # If ML diverges (BUY & prob <= 0.47 or SELL & prob >= 0.53) -> damp 0.40x
    ml_size_mult = 1.0
    if action == "BUY":
        if ml_prob >= 0.53:
            ml_size_mult = 1.35
            reason_parts.append(f"ML Confirmed Buy (P={ml_prob:.2f}, 1.35x size)")
        elif ml_prob <= 0.47:
            ml_size_mult = 0.40
            reason_parts.append(f"ML Divergence (P={ml_prob:.2f}, 0.40x damp)")
    elif action == "SELL":
        if ml_prob <= 0.47:
            ml_size_mult = 1.35
            reason_parts.append(f"ML Confirmed Sell (P={ml_prob:.2f}, 1.35x size)")
        elif ml_prob >= 0.53:
            ml_size_mult = 0.40
            reason_parts.append(f"ML Divergence (P={ml_prob:.2f}, 0.40x damp)")

    combined_size_mult = dd_status["size_multiplier"] * ml_size_mult

    # Check Macro DXY Beta Inversion Filter
    dxy_eval = cross_asset_monitor.evaluate_dxy_liquidity_filter(dxy_daily_change_pct=0.0)
    if action == "BUY" and dxy_eval["dollar_squeeze"]:
        combined_size_mult *= dxy_eval["risk_multiplier"]
        reason_parts.append(f"DXY Squeeze Long Throttling ({dxy_eval['risk_multiplier']:.2f}x)")

    # Check Portfolio Covariance Deflation if open positions exist
    cov_deflation = cross_asset_monitor.check_correlation_risk(req.open_positions) if req.open_positions else 1.0
    if cov_deflation < 1.0:
        reason_parts.append(f"Covariance Risk Deflation ({cov_deflation:.2f}x)")

    # Forex pip sizing approximation (EURUSD pip ~ 0.0001)
    pip_scale = 0.0001 if latest_close < 500 else 1.0
    sl_pips = max(5.0, sl_dist / pip_scale)
    sized = position_sizer.calculate_lot_size(
        account_equity=req.account_equity,
        sl_distance_pips=sl_pips,
        pip_value=10.0 if pip_scale == 0.0001 else 1.0,
        size_multiplier=combined_size_mult,
        covariance_deflation_factor=cov_deflation,
        max_lot=1.0,
        min_lot=0.01,
    )

    final_confidence = int(min(100, (conviction * 0.6) + (ml_prob * 100.0 * 0.4)))

    resp = SignalResponse(
        action=action,
        symbol=req.symbol,
        lots=sized["lots"],
        sl=sl,
        tp=tp,
        limit_price=limit_entry_price,
        confidence=final_confidence,
        reason=" + ".join(reason_parts),
        regime=current_regime,
        regime_detail=regime_info,
        ml_probability=round(ml_prob, 3),
        conviction_breakdown=fusion_result["breakdown"],
        risk={
            **dd_status,
            "lots": sized["lots"],
            "risk_amount_usd": sized["risk_amount"],
        },
        expiry_seconds=3600,
        timestamp=timestamp_str,
    )

    system_state["last_signal"] = resp.dict()
    return resp
