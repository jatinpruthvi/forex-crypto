"""Post-bugfix ROI validation on REAL historical data -- walk-forward, out-of-sample.

No synthetic data, no in-sample contamination, no hand-picked windows:

  Datasets (all real historical candles shipped in data/):
    A. crypto22 -- 8 USDT perps, 2022-10-30 -> 2023-04-15 (1000 synced H4 bars)
    B. crypto24 -- 4 pairs, 2024-01-01 -> 2024-03-24 (500 synced H4 bars, bull regime)
    C. forex    -- 6 FX/macro pairs, 2012-11 -> 2022-03 (~9.3 years, 14,400 H4 bars)

  Method (per dataset):
    1. Indicators computed once on the full history (causal, past-only).
    2. Expanding-window walk-forward folds: config grid is scored on the TRAIN
       window ONLY; the champion is chosen by rule (max monthly ROI among
       configs with train max-DD <= 15%, the crypto-futures prop limit;
       tie-break lower DD).
    3. The selected config is then run ONCE on the held-out TEST window and
       those numbers -- and only those numbers -- are reported as OOS ROI.

  Fill model: the audited corrected engine (bar-start stop snapshot, stop fills
  FIRST on ambiguous bars with taker fee + 0.05% slippage, net-trade wins),
  imported from run_dual_slot_shared_pool_benchmark.execute_shared_pool_sim
  (single source of truth, pinned against EXP-016 to the cent).

Usage:
    PYTHONPATH=. python scripts/validate_roi_postfix.py [--record]
    (--record appends EXP-018* entries to reports/roi_progress_ledger.json)
"""

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run_dual_slot_shared_pool_benchmark import execute_shared_pool_sim  # noqa: E402
from core.analysis.quantum_hybrid_engine import QuantumHybridEngine  # noqa: E402

RISK_GRID = [0.5, 0.75, 1.0, 1.25, 1.5]
SLOT_GRID = [1, 2]
LEV = 2.0
DD_LIMIT_PCT = 15.0  # crypto-futures prop constraint (task requirement)
INITIAL_CAPITAL = 1000.0


# ----------------------------------------------------------------------------
# Data loading (real CSVs only)
# ----------------------------------------------------------------------------

def _load_csv(path):
    df = pd.read_csv(path)
    if "date" in df.columns and "timestamp" not in df.columns:
        df.rename(columns={"date": "timestamp"}, inplace=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    if "volume" not in df.columns and "tick_volume" in df.columns:
        df.rename(columns={"tick_volume": "volume"}, inplace=True)
    if "volume" not in df.columns:
        df["volume"] = 0.0
    return df[["timestamp", "open", "high", "low", "close", "volume"]]


def _resample_h4(df, label):
    """Force true H4 bars (EURJPY source file is H1)."""
    span = (df["timestamp"].iloc[-1] - df["timestamp"].iloc[0]).total_seconds() / 3600.0
    if len(df) > 1.5 * (span / 4.0):
        print(f"  [resample] {label}: {len(df)} rows are sub-4H -- aggregating to H4 OHLC")
        df = (df.set_index("timestamp")
                .resample("4h")
                .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
                .dropna()
                .reset_index())
    return df


def load_panel(specs, label):
    """Load -> indicator -> align on common timestamps. Returns (timestamps, aligned_dfs)."""
    engine = QuantumHybridEngine(
        initial_capital=INITIAL_CAPITAL, base_risk_pct=1.5, leverage=LEV,
        tier1_pyramid_mult=1.0, tier2_pyramid_mult=0.8, tp1_atr=1.8,
        tp2_atr=3.0, trail_atr=2.0, maker_fee_pct=0.015,
        enable_drawdown_throttle=True,
    )
    dfs = {}
    for sym, path in specs:
        df = _resample_h4(_load_csv(path), sym)
        dfs[sym] = engine.generate_indicators(df)
    timestamps = sorted(set.intersection(*[set(dfs[s]["timestamp"]) for s in dfs]))
    aligned = {}
    for sym in dfs:
        aligned[sym] = (dfs[sym][dfs[sym]["timestamp"].isin(timestamps)]
                        .sort_values("timestamp").reset_index(drop=True))
    span_days = (timestamps[-1] - timestamps[0]).total_seconds() / 86400.0
    print(f"[{label}] {len(specs)} pairs | {len(timestamps)} synced H4 bars | "
          f"{timestamps[0]} -> {timestamps[-1]} ({span_days / 30.4375:.2f} months)")
    return engine, timestamps, aligned


DATASETS = {
    "crypto22": {
        "asset": "8 Synchronized Crypto Pairs (BTC, ETH, BNB, XRP, ADA, DOGE, LTC, LINK)",
        "specs": [
            ("DOGE/USDT", "data/timeframes/bench_panel/DOGEUSDT_H4.csv"),
            ("BNB/USDT", "data/timeframes/bench_panel/BNBUSDT_H4.csv"),
            ("XRP/USDT", "data/timeframes/bench_panel/XRPUSDT_H4.csv"),
            ("ADA/USDT", "data/timeframes/bench_panel/ADAUSDT_H4.csv"),
            ("BTC/USDT", "data/timeframes/bench_panel/BTCUSDT_4h.csv"),
            ("LTC/USDT", "data/timeframes/bench_panel/LTCUSDT_H4.csv"),
            ("ETH/USDT", "data/timeframes/bench_panel/ETHUSDT_H4.csv"),
            ("LINK/USDT", "data/timeframes/bench_panel/LINKUSDT_H4.csv"),
        ],
        # (train_end_idx, test_end_idx) on the synced timeline
        "folds": [(500, 1000)],
    },
    "crypto24": {
        "asset": "4 Crypto Pairs (BTC, SOL, BNB, LINK) -- 2024 bull regime",
        "specs": [
            ("BTC/USDT", "data/timeframes/BTCUSD_H4.csv"),
            ("SOL/USDT", "data/timeframes/SOLUSDT_H4.csv"),
            ("BNB/USDT", "data/timeframes/BNBUSDT_H4.csv"),
            ("LINK/USDT", "data/timeframes/LINKUSDT_H4.csv"),
        ],
        "folds": [(250, 500)],
    },
    "forex": {
        "asset": "6 Macro Pairs (GBPJPY, XAUUSD, EURJPY, GBPUSD, AUDUSD, USDJPY)",
        "specs": [
            ("GBP/JPY", "data/forex/GBPJPY_H4.csv"),
            ("Gold (XAU/USD)", "data/forex/XAUUSD_H4.csv"),
            ("EUR/JPY", "data/forex/EURJPY_H4.csv"),
            ("GBP/USD", "data/forex/GBPUSD_H4.csv"),
            ("AUD/USD", "data/forex/AUDUSD_H4.csv"),
            ("USD/JPY", "data/forex/USDJPY_H4.csv"),
        ],
        "folds": [(4800, 7200), (7200, 9600), (9600, 12000), (12000, 14400)],
    },
}


# ----------------------------------------------------------------------------
# Walk-forward machinery
# ----------------------------------------------------------------------------

def slice_window(timestamps, aligned, i0, i1):
    ts = timestamps[i0:i1]
    ali = {s: df.iloc[i0:i1].reset_index(drop=True) for s, df in aligned.items()}
    months = (ts[-1] - ts[0]).total_seconds() / 86400.0 / 30.4375
    return ts, ali, months


def run_config(engine, ts, ali, months, risk, slots, gate_fn):
    return execute_shared_pool_sim(
        ts, ali, engine, months, gate_fn=gate_fn,
        max_slots=slots, risk_pct=risk, lev=LEV,
    )


def select_config(engine, ts_tr, ali_tr, months_tr, gate_fn):
    """Grid scored on TRAIN only. Rule: max monthly ROI with train max-DD <= 15%."""
    rows = []
    for risk in RISK_GRID:
        for slots in SLOT_GRID:
            r = run_config(engine, ts_tr, ali_tr, months_tr, risk, slots, gate_fn)
            rows.append({"risk": risk, "slots": slots, **r})
    eligible = [r for r in rows if r["max_drawdown"] <= DD_LIMIT_PCT]
    pool = eligible if eligible else rows  # never cherry-pick: rule falls back to min-DD
    if eligible:
        best = max(pool, key=lambda r: (r["monthly_roi"], -r["max_drawdown"]))
    else:
        best = min(pool, key=lambda r: r["max_drawdown"])
    return best, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", action="store_true",
                    help="append EXP-018* entries to reports/roi_progress_ledger.json")
    args = ap.parse_args()

    all_summaries = []
    selected_by_ds = {}

    for ds_name, ds in DATASETS.items():
        print("\n" + "=" * 105)
        print(f"WALK-FORWARD VALIDATION: {ds_name.upper()}  ({ds['asset']})")
        print("=" * 105)
        engine, timestamps, aligned = load_panel(ds["specs"], ds_name)
        gate_fn = None if ds_name == "forex" else _venue_gate  # FX OTC: no exchange lot gate
        gate_note = ("no venue lot gate (OTC FX)" if gate_fn is None
                     else "MEXC lot/min-notional gate active")

        fold_reports = []
        for k, (train_end, test_end) in enumerate(ds["folds"], start=1):
            ts_tr, ali_tr, m_tr = slice_window(timestamps, aligned, 0, train_end)
            ts_te, ali_te, m_te = slice_window(timestamps, aligned, train_end, test_end)
            print(f"\n--- Fold {k}: TRAIN {ts_tr[0]} -> {ts_tr[-1]} ({m_tr:.2f} mo) | "
                  f"TEST {ts_te[0]} -> {ts_te[-1]} ({m_te:.2f} mo) | {gate_note} ---")
            print(f"{'config':<22} | {'train $':>12} | {'train %/mo':>10} | {'train DD':>8} | "
                  f"{'trades':>6} | {'WR':>6} | {'PF':>5}")
            best, rows = select_config(engine, ts_tr, ali_tr, m_tr, gate_fn)
            for r in rows:
                marker = " <-- selected" if r is best else ""
                print(f"{('risk %.2f%% / %d slot%s' % (r['risk'], r['slots'], 's' if r['slots'] > 1 else '')):<22} "
                      f"| ${r['final_equity']:>11,.2f} | {r['monthly_roi']:>9.2f}% "
                      f"| {r['max_drawdown']:>7.2f}% | {r['total_trades']:>6d} "
                      f"| {r['win_rate']:>5.1f}% | {r['profit_factor']:>5.2f}{marker}")

            oos = run_config(engine, ts_te, ali_te, m_te, best["risk"], best["slots"], gate_fn)
            print(f">>> OOS Fold {k} (risk {best['risk']}%, {best['slots']} slot(s)):")
            print(f"    TEST  {ts_te[0]} -> {ts_te[-1]}  ({m_te:.2f} months)")
            open_note = ("" if oos.get("open_positions_at_end", 0) == 0 else
                         f" (incl. {oos['open_positions_at_end']} position(s) still open at window end, marked to market)")
            print(f"    monthly ROI {oos['monthly_roi']:+.2f}%/mo | max DD {oos['max_drawdown']:.2f}% "
                  f"| trades {oos['total_trades']} | WR {oos['win_rate']:.1f}% | PF {oos['profit_factor']:.2f} "
                  f"| final ${oos['final_equity']:,.2f} on ${INITIAL_CAPITAL:,.0f}{open_note}")
            ok = "PASS" if oos["max_drawdown"] <= DD_LIMIT_PCT else "BREACH"
            print(f"    prop-firm DD check (<= {DD_LIMIT_PCT}%): {ok}")
            selected_by_ds[ds_name] = (best["risk"], best["slots"])
            fold_reports.append({"fold": k, "train_months": round(m_tr, 2),
                                 "test_months": round(m_te, 2),
                                 "selected": {"risk_pct": best["risk"], "max_slots": best["slots"]},
                                 "oos": {key: oos[key] for key in
                                         ("final_equity", "monthly_roi", "max_drawdown",
                                          "total_trades", "win_rate", "profit_factor")}})

        # Aggregate OOS across folds (compound the TEST windows sequentially)
        oos_months = sum(f["test_months"] for f in fold_reports)
        oos_growth = 1.0
        for f in fold_reports:
            oos_growth *= (1.0 + f["oos"]["monthly_roi"] / 100.0) ** f["test_months"]
        oos_monthly = (oos_growth ** (1.0 / oos_months) - 1.0) * 100.0
        worst_dd = max(f["oos"]["max_drawdown"] for f in fold_reports)
        total_trades = sum(f["oos"]["total_trades"] for f in fold_reports)
        print(f"\n>>> {ds_name} OOS AGGREGATE ({len(fold_reports)} held-out folds, "
              f"{oos_months:.2f} unseen months total):")
        print(f"    compounded OOS monthly ROI: {oos_monthly:+.2f}%/mo")
        print(f"    worst fold max DD:          {worst_dd:.2f}%  "
              f"({'PASS' if worst_dd <= DD_LIMIT_PCT else 'BREACH'} vs {DD_LIMIT_PCT}% limit)")
        print(f"    total OOS trades:           {total_trades}")
        all_summaries.append({
            "dataset": ds_name, "asset": ds["asset"], "folds": fold_reports,
            "oos_months": round(oos_months, 2),
            "oos_monthly_roi_pct": round(oos_monthly, 2),
            "worst_oos_max_drawdown_pct": round(worst_dd, 2),
            "total_oos_trades": total_trades,
        })

    # ------------------------------------------------------------------
    print("\n" + "=" * 105)
    print("POST-FIX ROI VALIDATION SUMMARY (real historical data, strictly out-of-sample)")
    print("=" * 105)
    print(f"{'dataset':<10} | {'unseen months':>13} | {'OOS ROI/mo':>10} | {'worst DD':>8} | {'trades':>6}")
    for s in all_summaries:
        print(f"{s['dataset']:<10} | {s['oos_months']:>13.2f} | {s['oos_monthly_roi_pct']:>+9.2f}% "
              f"| {s['worst_oos_max_drawdown_pct']:>7.2f}% | {s['total_oos_trades']:>6d}")

    # Cross-dataset transfer: config selected on crypto22 TRAIN -> crypto24 FULL window.
    # Zero overlap between the two windows (2022-10..2023-04 vs 2024-01..2024-03).
    transfer = None
    if "crypto22" in selected_by_ds and "crypto24" in DATASETS:
        risk, slots = selected_by_ds["crypto22"]
        ds = DATASETS["crypto24"]
        engine_t, timestamps_t, aligned_t = load_panel(ds["specs"], "crypto24-transfer")
        ts_t, ali_t, m_t = slice_window(timestamps_t, aligned_t, 0, len(timestamps_t))
        tr = run_config(engine_t, ts_t, ali_t, m_t, risk, slots, _venue_gate)
        print(f"\nCROSS-DATASET TRANSFER: crypto22-selected config (risk {risk}%, {slots} slots) "
              f"-> FULL crypto24 window (2024 bull regime, unseen):")
        print(f"    monthly ROI {tr['monthly_roi']:+.2f}%/mo | max DD {tr['max_drawdown']:.2f}% "
              f"| trades {tr['total_trades']} | WR {tr['win_rate']:.1f}% | PF {tr['profit_factor']:.2f}"
              + ("" if tr.get("open_positions_at_end", 0) == 0
                 else f" (incl. {tr['open_positions_at_end']} open at end)"))
        print(f"    prop-firm DD check (<= {DD_LIMIT_PCT}%): "
              f"{'PASS' if tr['max_drawdown'] <= DD_LIMIT_PCT else 'BREACH'}")
        transfer = {"from": "crypto22", "to": "crypto24", "risk_pct": risk, "max_slots": slots,
                    "oos": {k2: tr[k2] for k2 in ("final_equity", "monthly_roi", "max_drawdown",
                                                 "total_trades", "win_rate", "profit_factor")},
                    "open_positions_at_end": tr.get("open_positions_at_end", 0),
                    "months": round(m_t, 2)}

    if args.record:
        from core.analysis.roi_ledger import ROILedger
        ledger = ROILedger()
        for s in all_summaries:
            exp_id = {"crypto22": "EXP-018A-WALKFORWARD-CRYPTO22-OOS",
                      "crypto24": "EXP-018B-WALKFORWARD-CRYPTO24-OOS",
                      "forex": "EXP-018C-WALKFORWARD-FOREX-OOS"}[s["dataset"]]
            ledger.record_experiment(
                experiment_id=exp_id,
                strategy_name="Dual-Slot Shared Pool -- Walk-Forward OOS Validation (post-bugfix)",
                asset=s["asset"],
                timeframe="H4 Actual Historical Candles",
                duration_desc=f"{len(s['folds'])} held-out fold(s), {s['oos_months']} unseen months",
                params={
                    "risk_grid_pct": RISK_GRID, "slot_grid": SLOT_GRID, "leverage": LEV,
                    "selection_rule": f"max train monthly ROI with train max-DD <= {DD_LIMIT_PCT}%",
                    "fill_model": "audited corrected model (bar-start SL-first, taker+slippage, net-trade wins)",
                    "folds": s["folds"],
                },
                results={
                    "months_elapsed": s["oos_months"],
                    "monthly_roi_pct": s["oos_monthly_roi_pct"],
                    "max_drawdown_pct": s["worst_oos_max_drawdown_pct"],
                    "total_trades": s["total_oos_trades"],
                    "initial_capital": INITIAL_CAPITAL,
                },
                notes=("Strictly out-of-sample walk-forward on real historical candles: config selected "
                       "on TRAIN window only, metrics reported from held-out TEST window only. OOS ROI "
                       "compounds the unseen folds sequentially; worst DD is the worst held-out fold. "
                       "No in-sample trades are included in reported metrics."
                       + ("" if not (s["dataset"] == "crypto24" and transfer) else
                          f" Cross-dataset transfer check (crypto22-selected risk {transfer['risk_pct']}%/"
                          f"{transfer['max_slots']} slots on the full unseen crypto24 window): "
                          f"{transfer['oos']['monthly_roi']:+.2f}%/mo, DD {transfer['oos']['max_drawdown']:.2f}%.")),
                tag="POSTFIX_WALKFORWARD_OOS",
                create_savepoint=True,
            )
        print("\nRecorded EXP-018A/B/C into reports/roi_progress_ledger.json")


def _venue_gate(sym, eq, price, atr, risk, leverage, dd_mult, stop_atr_mult=1.5):
    from core.execution.live_adapter import SizingViabilityGate
    gate = SizingViabilityGate.check(
        sym, equity=eq, price=price, atr=atr, risk_pct=risk,
        leverage=leverage, dd_factor=dd_mult, stop_atr_mult=stop_atr_mult,
        max_error_pct=float(os.getenv("MICRO_MAX_SIZING_ERROR_PCT", "5.0")),
        venue=os.getenv("LOT_VENUE", "mexc"),
    )
    return gate["stepped_qty"] if gate["viable"] else 0.0


if __name__ == "__main__":
    main()
