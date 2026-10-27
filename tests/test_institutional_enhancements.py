import pytest
import pandas as pd
import numpy as np

from core.signals.alpha_enhancements import (
    VolumeProfileAnalyzer,
    MicrostructureFlowFilter,
    VolatilitySqueezeDetector,
    MultiTimeframeConfluence
)
from core.risk.institutional_guards import (
    PropFirmRiskGuard,
    ValueAtRiskGuard,
    CorrelationHaircutCalculator,
    FundingDragEstimator,
    FlashCrashGuard
)
from core.ml.regime_intelligence import (
    StackingEnsemblePredictor,
    RealTimeShapExplainer,
    RegimeMixtureClusterer,
    RollingOnlineRetrainer
)
from services.brain_api.ops_bridge import (
    TearsheetDispatcher,
    MT5ExecutionBridge
)


def test_volume_profile_analyzer():
    n = 100
    prices = pd.Series(np.linspace(50000, 51000, n))
    highs = prices + 50.0
    lows = prices - 50.0
    volumes = pd.Series(np.random.uniform(10, 50, n))
    volumes.iloc[50] = 500
    
    vp = VolumeProfileAnalyzer.calculate_volume_profile(prices, highs, lows, volumes, bins=20)
    assert "poc" in vp
    assert "vah" in vp
    assert "val" in vp
    assert vp["val"] <= vp["poc"] <= vp["vah"]
    assert 50400 <= vp["poc"] <= 50600


def test_microstructure_flow_filter():
    n = 30
    close = pd.Series(np.linspace(100, 110, n))
    open_p = pd.Series(np.linspace(99, 109, n))
    high = pd.Series(np.linspace(101, 111, n))
    low = pd.Series(np.linspace(98, 108, n))
    volume = pd.Series(np.ones(n) * 100)
    
    res = MicrostructureFlowFilter.calculate_taker_delta(close, open_p, high, low, volume, window=14)
    assert "cvd_slope" in res
    assert "buy_delta_ratio" in res
    assert "taker_confirmed" in res
    assert 0.0 <= res["buy_delta_ratio"] <= 1.0


def test_volatility_squeeze_detector():
    n = 50
    close = pd.Series(100.0 + np.random.normal(0, 0.05, n))
    high = close + 0.1
    low = close - 0.1
    
    res = VolatilitySqueezeDetector.detect_squeeze(close, high, low)
    assert "is_squeeze" in res
    assert "squeeze_release" in res
    assert "bandwidth" in res
    assert isinstance(res["is_squeeze"], (bool, np.bool_))


def test_multi_timeframe_confluence():
    aligned, label = MultiTimeframeConfluence.check_triple_alignment(
        m15_direction=1,
        h1_close=52000.0,
        h1_ema50=51000.0,
        h4_direction=1
    )
    assert aligned is True
    assert label == "TRIPLE_BULLISH_CONFLUENCE"

    misaligned, mis_label = MultiTimeframeConfluence.check_triple_alignment(
        m15_direction=1,
        h1_close=50000.0,
        h1_ema50=51000.0,
        h4_direction=1
    )
    assert misaligned is False
    assert mis_label == "MISALIGNED_TIMEFRAMES"


def test_prop_firm_risk_guard():
    guard = PropFirmRiskGuard(max_daily_loss_pct=4.0, lockout_trigger_pct=3.5)
    
    # Day 1 start
    state1 = guard.update_daily_state("2026-10-26T00:00:00Z", 10000.0)
    assert state1["is_daily_locked"] is False
    assert state1["daily_loss_pct"] == 0.0
    
    # 2% drawdown -> compliant
    state2 = guard.update_daily_state("2026-10-26T04:00:00Z", 9800.0)
    assert state2["is_daily_locked"] is False
    assert state2["daily_loss_pct"] == 2.0
    
    # 4% drawdown -> lockout triggered
    state3 = guard.update_daily_state("2026-10-26T08:00:00Z", 9600.0)
    assert state3["is_daily_locked"] is True
    assert state3["compliance_status"] == "LOCKED"
    
    # Next day rollover -> resets
    state4 = guard.update_daily_state("2026-10-27T00:00:00Z", 9600.0)
    assert state4["is_daily_locked"] is False
    assert state4["daily_loss_pct"] == 0.0


def test_var_engine():
    equity = 100000.0
    position_notionals = [20000.0, 15000.0]
    asset_volatilities = [0.02, 0.035]
    
    res = ValueAtRiskGuard.calculate_var(equity, position_notionals, asset_volatilities, confidence_level=0.99)
    assert res["var_usd"] > 0
    assert res["var_pct"] > 0
    assert res["cvar_pct"] >= res["var_pct"]
    assert not bool(res["var_breached"])


def test_correlation_guard():
    ret_a = pd.Series(np.random.normal(0, 0.01, 50))
    ret_b = ret_a * 0.95 + pd.Series(np.random.normal(0, 0.001, 50))  # strongly correlated
    ret_c = pd.Series(np.random.normal(0, 0.01, 50))  # uncorrelated
    
    haircut_high = CorrelationHaircutCalculator.compute_haircut(ret_a, ret_b)
    haircut_low = CorrelationHaircutCalculator.compute_haircut(ret_a, ret_c)
    assert haircut_high < 1.0
    assert haircut_low == 1.0


def test_funding_drag_calculator():
    base_tp = 105.0
    entry = 100.0
    adjusted_tp = FundingDragEstimator.adjust_for_funding(
        base_tp_price=base_tp,
        entry_price=entry,
        side="long",
        predicted_funding_rate=0.0003,
        estimated_holding_hours=16.0
    )
    assert adjusted_tp > base_tp


def test_circuit_breaker():
    assert FlashCrashGuard.is_anomaly(high=53000.0, low=52500.0, atr=200.0) is False
    assert FlashCrashGuard.is_anomaly(high=54000.0, low=51000.0, atr=200.0) is True


def test_stacking_ensemble():
    model = StackingEnsemblePredictor(weights={"xgboost": 0.5, "random_forest": 0.3, "lightgbm": 0.2})
    blended = model.ensemble_predict_proba(prob_xgb=0.70, prob_rf=0.60, prob_lgb=0.80)
    assert 0.65 <= blended <= 0.75


def test_regime_clustering():
    regime = RegimeMixtureClusterer.classify_regime(returns_std_20=0.005, trend_slope_3=0.0005)
    assert regime["regime"] == "ACCUMULATION_RANGE"
    assert regime["sizing_multiplier"] == 0.8
    
    regime_trend = RegimeMixtureClusterer.classify_regime(returns_std_20=0.015, trend_slope_3=0.0025)
    assert regime_trend["regime"] == "MOMENTUM_EXPANSION"
    assert regime_trend["sizing_multiplier"] == 1.2


def test_shap_explainer():
    feats = {"vol_ratio": 2.5, "trend_dist": 0.015, "returns_4": 0.03}
    attributions = RealTimeShapExplainer.explain_prediction(feats)
    assert len(attributions) == 3
    features_present = [item["feature"] for item in attributions]
    assert "Volume Surge Ratio" in features_present
    assert "EMA-50 Trend Proximity" in features_present
    assert "4-Bar Price Momentum" in features_present


def test_online_retrainer():
    retrainer = RollingOnlineRetrainer(retrain_interval_trades=5)
    triggered = False
    for i in range(5):
        trig = retrainer.add_trade({"trade_id": i, "pnl": 10.0})
        if trig:
            triggered = True
    assert triggered is True
    assert retrainer.retrain_count == 1


def test_tearsheet_and_mt5_bridge():
    accounts = {
        "mexc_opt_a": {"name": "MEXC Option A", "total_return_pct": 12.5, "current_equity": 11250.0, "max_drawdown_pct": 4.2, "win_rate_pct": 55.0, "total_trades": 40},
        "bybit_opt_a": {"name": "Bybit Option A", "total_return_pct": 10.1, "current_equity": 11010.0, "max_drawdown_pct": 4.5, "win_rate_pct": 53.0, "total_trades": 40},
    }
    report = TearsheetDispatcher.generate_daily_tearsheet(accounts, date_str="2026-10-26", save_path="/tmp/test_tearsheet.md")
    assert "# 📊 AMATS Institutional Performance Tearsheet — 2026-10-26" in report
    assert "MEXC Option A" in report
    assert "Bybit Option A" in report
    
    # MT5 Order format
    bridge = MT5ExecutionBridge(magic_number=888001)
    order = bridge.format_mt5_order(
        symbol="BTC/USDT",
        action="BUY",
        volume_lots=0.5,
        price=50000.0,
        sl=49000.0,
        tp=52000.0
    )
    assert order["magic"] == 888001
    assert order["symbol"] == "BTCUSDT"
    assert order["action"] == "BUY"
    assert order["volume"] == 0.5
    
    polled = bridge.poll_orders()
    assert len(polled) == 1
    assert len(bridge.poll_orders()) == 0
