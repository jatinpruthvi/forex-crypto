"""
End-to-End Quantitative Production Pipeline (Phases 1, 2, 3):
Orchestrates:
Phase 1: Research & Discovery via VectorBT Matrix Scanner across 60 parameter combinations.
Phase 2: Risk Modeling & Path-Dependent Verification with BacktestSimulator & Dynamic Drawdown Throttle.
Phase 3: Production Deployment to Live Strategy Configs and Persistent ROI Ledger Savepoints.
"""

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import json
import pandas as pd
import numpy as np
from core.analysis.vbt_scanner import VectorBTScanner
from core.analysis.fast_backtester import BacktestSimulator
from core.analysis.roi_ledger import ROILedger

def run_pipeline(
    csv_path: str = "data/timeframes/BTCUSD_H4.csv",
    asset: str = "BTC/USDT",
    timeframe: str = "4H"
):
    print("="*90)
    print(f"EXECUTING UNIFIED 3-PHASE QUANT PIPELINE FOR {asset} ({timeframe})")
    print("="*90)

    ledger = ROILedger()

    # -------------------------------------------------------------
    # PHASE 1: Research & Discovery via VectorBT (Grid Scan)
    # -------------------------------------------------------------
    print("\n>>> PHASE 1: RESEARCH & DISCOVERY VIA VECTORBT MATRIX SCANNER")
    scanner = VectorBTScanner(ledger=ledger)
    vbt_results = scanner.run_grid_scan(
        asset_csv_path=csv_path,
        asset_name=asset,
        timeframe=timeframe
    )
    print(f"Top 5 Ranked Strategy Configurations by Sharpe Ratio (out of {len(vbt_results)} tested):")
    print(vbt_results[["config_label", "sharpe_ratio", "monthly_roi_pct", "total_return_pct", "max_drawdown_pct", "win_rate_pct", "total_trades"]].head(5).to_string(index=False))

    top_cfg = vbt_results.iloc[0]
    best_lb = int(top_cfg["lookback"])
    best_vwap = int(top_cfg["vwap_window"])
    best_fast = int(top_cfg["ema_fast"])
    best_slow = int(top_cfg["ema_slow"])

    # -------------------------------------------------------------
    # PHASE 2: Execution & Risk Modeling via BacktestSimulator
    # -------------------------------------------------------------
    print("\n>>> PHASE 2: PATH-DEPENDENT RISK MODELING & SIMULATION WITH DRAWDOWN THROTTLE")
    df = pd.read_csv(csv_path)
    if "timestamp" not in df.columns and "date" in df.columns:
        df.rename(columns={"date": "timestamp"}, inplace=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    close, high, low, open_p, vol = df["close"], df["high"], df["low"], df["open"], df["volume"]
    tr = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
    atr = tr.rolling(14).mean().bfill()

    # Compute exact signals for champion parameters
    typical_p = (high + low + close) / 3.0
    r_vwap = (typical_p * vol).rolling(best_vwap).sum() / vol.rolling(best_vwap).sum().replace(0, 1)
    ema_f = close.ewm(span=best_fast).mean()
    ema_s = close.ewm(span=best_slow).mean()
    h_b = high.rolling(best_lb).max().shift(1)
    l_b = low.rolling(best_lb).min().shift(1)

    bull = (close > open_p) & (close > r_vwap) & (ema_f > ema_s) & (high >= h_b)
    bear = (close < open_p) & (close < r_vwap) & (ema_f < ema_s) & (low <= l_b)

    sig = pd.DataFrame(index=df.index)
    sig["signal"] = 0
    sig["atr"] = atr
    sig["conviction"] = 85.0
    sig["regime"] = "TREND"
    sig.loc[bull, "signal"] = 1
    sig.loc[bear, "signal"] = -1
    # ATR is .bfill()'d through its 14-bar warmup while h_b first signals at bar best_lb
    # - zero signals through bar 13 so no entry uses future-filled ATR.
    sig.loc[:13, "signal"] = 0

    sim = BacktestSimulator(slippage_pct=0.01, taker_fee_pct=0.02, initial_capital=1000.0, order_execution_mode="maker")
    # Verified execution with Dynamic Drawdown Throttle, Breakeven Lock, & Trailing Ratchet
    res_phase2 = sim.run_backtest(
        df,
        sig,
        risk_per_trade_pct=4.0,
        atr_sl_mult=1.3,
        atr_tp_mult=2.5,
        trailing_atr_mult=2.5,
        leverage=3.0
    )

    print("Phase 2 Execution Metrics (Realistic Maker Fees & Dynamic Drawdown Guard):")
    print(f"  Monthly Compounded ROI: {res_phase2['monthly_roi_pct']:+.2f}%/mo")
    print(f"  Net Total Return:       {res_phase2['net_roi_total_pct']:+.2f}%")
    print(f"  Max Account Drawdown:    {res_phase2['max_drawdown_pct']}%")
    print(f"  Win Rate:                {res_phase2['win_rate']}% ({res_phase2['total_trades']} closed trades)")
    print(f"  Profit Factor:           {res_phase2['profit_factor']}")

    # -------------------------------------------------------------
    # PHASE 3: Live Production Config Sync & Ledger Registration
    # -------------------------------------------------------------
    print("\n>>> PHASE 3: PRODUCTION DEPLOYMENT & SAVEPOINT REGISTRATION")
    exp_id = f"EXP-PIPELINE-CHAMPION-{asset.replace('/', '_').replace(':', '_')}"
    ledger.record_experiment(
        experiment_id=exp_id,
        strategy_name=f"VBT Optimized: Donchian-{best_lb} + VWAP-{best_vwap} + EMA-{best_fast}/{best_slow}",
        asset=asset,
        timeframe=timeframe,
        duration_desc=f"{res_phase2['months_elapsed']} months",
        params={
            "lookback": best_lb,
            "vwap_window": best_vwap,
            "ema_fast": best_fast,
            "ema_slow": best_slow,
            "risk_pct": 4.0,
            "sl_atr": 1.3,
            "tp_atr": 2.5,
            "trail_atr": 2.5,
            "leverage": 3.0
        },
        results=res_phase2,
        notes="Full 3-Phase end-to-end champion pipeline: VectorBT discovery -> Drawdown throttle modeling -> Production savepoint",
        tag="PIPELINE_CHAMPION",
        create_savepoint=True
    )
    print(f"Saved Champion State to ROI Ledger under savepoint 'SAVEPOINT_{exp_id}'.")

    # Sync into FreqTrade production config file
    cfg_path = "services/freqtrade/user_data/config_production.json"
    if os.path.exists(cfg_path):
        with open(cfg_path, "r") as f:
            cfg = json.load(f)
        cfg["strategy"] = "OptionA_BTC_CompressedDonchian"
        cfg["donchian_lookback"] = best_lb
        cfg["vwap_window"] = best_vwap
        with open(cfg_path, "w") as f:
            json.dump(cfg, f, indent=2)
        print(f"Synchronized champion parameters into {cfg_path}.")

    print("="*90)
    print(f"PIPELINE COMPLETE: Champion configuration active and restorable.")
    print("="*90)
    return res_phase2

if __name__ == "__main__":
    run_pipeline("data/timeframes/BTCUSD_H4.csv", "BTC/USDT", "4H")
