"""Deep crypto-only ROI validation -- stress-testing the "+25.8%/mo OOS" claim.

Focus (user decision: crypto-only initially). Everything runs on REAL historical
candles with the audited corrected engine (imported, pinned). For every
walk-forward fold we report:

  1. Selection on TRAIN only (rule: max monthly ROI with train DD <= 15%).
  2. Held-out TEST metrics at the baseline fill cost
     (0.05% stop slippage, 0.045% taker) -- comparable to EXP-018.
  3. Fill-cost stress: TEST re-run at (0.15%/0.075%) and (0.30%/0.10%) to test
     whether the edge survives worse fills than modeled.
  4. OOS grid sensitivity: the FULL config grid scored on TEST (sensitivity
     display only -- selection never uses these numbers).
  5. Per-month OOS attribution (was the fold's ROI one lucky month?).
  6. Per-pair OOS attribution (single-pair concentration?).
  7. Leave-one-pair-out robustness on the reference window.

Datasets:
  crypto22  -- 8 perps, 2022-10-30 -> 2023-04-15 (1000 H4 bars)
  crypto24  -- SOL/BNB/LINK, 2024-01-01 -> 2024-06-15 (1000 H4 bars)
Folds per dataset (non-overlapping TEST windows):
  f1: train [0,350) -> test [350,575)
  f2: train [0,575) -> test [575,800)
  f3: train [0,800) -> test [800,1000)
Reference fold (EXP-018 continuity, overlaps f2+f3 -- reported separately):
  ref: train [0,500) -> test [500,1000)

Usage: PYTHONPATH=. python scripts/validate_crypto_deep.py [--record]
"""

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run_dual_slot_shared_pool_benchmark import execute_shared_pool_sim  # noqa: E402
from core.analysis.quantum_hybrid_engine import QuantumHybridEngine  # noqa: E402
from core.execution.live_adapter import SizingViabilityGate  # noqa: E402

RISK_GRID = [0.5, 0.75, 1.0, 1.25, 1.5]
SLOT_GRID = [1, 2]
LEV = 2.0
DD_LIMIT_PCT = 15.0
INITIAL_CAPITAL = 1000.0

BASELINE = {"slip": 0.0005, "taker": 0.045, "label": "baseline (0.05% slip / 0.045% taker)"}
STRESS1 = {"slip": 0.0015, "taker": 0.075, "label": "stress-1 (0.15% slip / 0.075% taker)"}
STRESS2 = {"slip": 0.0030, "taker": 0.100, "label": "stress-2 (0.30% slip / 0.10% taker)"}

FOLDS = [("f1", 350, 575), ("f2", 575, 800), ("f3", 800, 1000)]
REF_FOLD = ("ref", 500, 1000)


def _load_csv(path):
    df = pd.read_csv(path)
    if "date" in df.columns and "timestamp" not in df.columns:
        df.rename(columns={"date": "timestamp"}, inplace=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df[["timestamp", "open", "high", "low", "close"]]


def load_panel(specs, label):
    engine = QuantumHybridEngine(
        initial_capital=INITIAL_CAPITAL, base_risk_pct=1.5, leverage=LEV,
        tier1_pyramid_mult=1.0, tier2_pyramid_mult=0.8, tp1_atr=1.8,
        tp2_atr=3.0, trail_atr=2.0, maker_fee_pct=0.015,
        enable_drawdown_throttle=True,
    )
    dfs = {sym: engine.generate_indicators(_load_csv(path)) for sym, path in specs}
    timestamps = sorted(set.intersection(*[set(dfs[s]["timestamp"]) for s in dfs]))
    aligned = {sym: dfs[sym][dfs[sym]["timestamp"].isin(timestamps)]
               .sort_values("timestamp").reset_index(drop=True) for sym in dfs}
    print(f"[{label}] {len(specs)} pairs | {len(timestamps)} synced H4 bars | "
          f"{timestamps[0]} -> {timestamps[-1]}")
    return engine, timestamps, aligned


def _venue_gate(sym, eq, price, atr, risk, leverage, dd_mult, stop_atr_mult=1.5):
    gate = SizingViabilityGate.check(
        sym, equity=eq, price=price, atr=atr, risk_pct=risk,
        leverage=leverage, dd_factor=dd_mult, stop_atr_mult=stop_atr_mult,
        max_error_pct=float(os.getenv("MICRO_MAX_SIZING_ERROR_PCT", "5.0")),
        venue=os.getenv("LOT_VENUE", "mexc"),
    )
    return gate["stepped_qty"] if gate["viable"] else 0.0


def slice_window(timestamps, aligned, i0, i1, drop=None):
    ts = timestamps[i0:i1]
    ali = {s: df.iloc[i0:i1].reset_index(drop=True)
           for s, df in aligned.items() if s != drop}
    months = (ts[-1] - ts[0]).total_seconds() / 86400.0 / 30.4375
    return ts, ali, months


def run_cfg(engine, ts, ali, months, risk, slots, cost):
    return execute_shared_pool_sim(
        ts, ali, engine, months, gate_fn=_venue_gate,
        max_slots=slots, risk_pct=risk, lev=LEV,
        stop_slippage=cost["slip"], taker_fee_pct=cost["taker"],
    )


def select_config(engine, ts_tr, ali_tr, m_tr):
    rows = [run_cfg(engine, ts_tr, ali_tr, m_tr, r, s, BASELINE)
            for r in RISK_GRID for s in SLOT_GRID]
    eligible = [x for x in rows if x["max_drawdown"] <= DD_LIMIT_PCT]
    if eligible:
        best = max(eligible, key=lambda x: (x["monthly_roi"], -x["max_drawdown"]))
    else:
        best = min(rows, key=lambda x: x["max_drawdown"])
    return best, rows


def monthly_attribution(trade_log):
    by_month = {}
    for t in trade_log:
        m = str(t["time"])[:7]
        d = by_month.setdefault(m, {"pnl": 0.0, "trades": 0, "wins": 0})
        d["pnl"] += t["pnl"]
        d["trades"] += 1
        if t["pnl"] > 0:
            d["wins"] += 1
    return by_month


def fmt_res(r, cost_label=None):
    extra = f" [{cost_label}]" if cost_label else ""
    open_note = ("" if r.get("open_positions_at_end", 0) == 0
                 else f", {r['open_positions_at_end']} open@end")
    return (f"{r['monthly_roi']:+.2f}%/mo | DD {r['max_drawdown']:.2f}% | "
            f"trades {r['total_trades']} | WR {r['win_rate']:.1f}% | "
            f"PF {r['profit_factor']:.2f} | ${r['final_equity']:,.0f}{open_note}{extra}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", action="store_true")
    args = ap.parse_args()

    datasets = {
        "crypto22": [
            ("DOGE/USDT", "data/timeframes/bench_panel/DOGEUSDT_H4.csv"),
            ("BNB/USDT", "data/timeframes/bench_panel/BNBUSDT_H4.csv"),
            ("XRP/USDT", "data/timeframes/bench_panel/XRPUSDT_H4.csv"),
            ("ADA/USDT", "data/timeframes/bench_panel/ADAUSDT_H4.csv"),
            ("BTC/USDT", "data/timeframes/bench_panel/BTCUSDT_4h.csv"),
            ("LTC/USDT", "data/timeframes/bench_panel/LTCUSDT_H4.csv"),
            ("ETH/USDT", "data/timeframes/bench_panel/ETHUSDT_H4.csv"),
            ("LINK/USDT", "data/timeframes/bench_panel/LINKUSDT_H4.csv"),
        ],
        "crypto24": [
            ("SOL/USDT", "data/timeframes/SOLUSDT_H4.csv"),
            ("BNB/USDT", "data/timeframes/BNBUSDT_H4.csv"),
            ("LINK/USDT", "data/timeframes/LINKUSDT_H4.csv"),
        ],
    }

    summaries = []
    for ds_name, specs in datasets.items():
        print("\n" + "=" * 105)
        print(f"DEEP CRYPTO VALIDATION: {ds_name.upper()}")
        print("=" * 105)
        engine, timestamps, aligned = load_panel(specs, ds_name)
        fold_reports = []

        for fname, i0, i1 in FOLDS + [REF_FOLD]:
            ts_tr, ali_tr, m_tr = slice_window(timestamps, aligned, 0, i0)
            ts_te, ali_te, m_te = slice_window(timestamps, aligned, i0, i1)
            is_ref = (fname == "ref")
            print(f"\n--- {fname.upper()}{' (reference fold, overlaps f2+f3)' if is_ref else ''}: "
                  f"TRAIN {ts_tr[0]} -> {ts_tr[-1]} ({m_tr:.2f} mo) | "
                  f"TEST {ts_te[0]} -> {ts_te[-1]} ({m_te:.2f} mo) ---")

            best, rows = select_config(engine, ts_tr, ali_tr, m_tr)
            sel = f"risk {best['risk_pct']}% / {best['max_slots']} slot(s)"
            print(f"  selected on TRAIN ({sel}): {fmt_res(best)}")

            oos = run_cfg(engine, ts_te, ali_te, m_te, best["risk_pct"], best["max_slots"], BASELINE)
            print(f"  OOS baseline: {fmt_res(oos)}")

            stress_res = {}
            for cost in (STRESS1, STRESS2):
                r = run_cfg(engine, ts_te, ali_te, m_te, best["risk_pct"], best["max_slots"], cost)
                stress_res[cost["label"]] = {k: r[k] for k in
                                             ("monthly_roi", "max_drawdown", "total_trades",
                                              "win_rate", "profit_factor", "final_equity")}
                print(f"  OOS {cost['label']}: {fmt_res(r)}")

            print(f"  OOS grid sensitivity (baseline cost, all configs on TEST -- sensitivity only):")
            for r in RISK_GRID:
                for sl in SLOT_GRID:
                    g = run_cfg(engine, ts_te, ali_te, m_te, r, sl, BASELINE)
                    mark = " <-- selected-config" if (r == best["risk_pct"] and sl == best["max_slots"]) else ""
                    print(f"    risk {r:.2f}% / {sl} slot(s): {fmt_res(g)}{mark}")

            mby = monthly_attribution(oos["trade_log"])
            print(f"  per-month OOS attribution ({ts_te[0].strftime('%Y-%m')} .. {ts_te[-1].strftime('%Y-%m')}):")
            for m in sorted(mby):
                d = mby[m]
                print(f"    {m}: pnl ${d['pnl']:+,.0f} | trades {d['trades']} | wins {d['wins']}"
                      + ("  <-- CLOSED trades only; open positions MTM in fold total"
                         if False else ""))

            cb = oos["coin_breakdown"]
            print(f"  per-pair OOS attribution:")
            for sym in sorted(cb, key=lambda k: -cb[k]["profit"]):
                c = cb[sym]
                print(f"    {sym:<12} trades {c['trades']:>3} | pnl ${c['profit']:>+10,.0f} | wins {c['wins']}")

            fold_reports.append({
                "fold": fname, "is_reference": is_ref,
                "train_months": round(m_tr, 2), "test_months": round(m_te, 2),
                "selected": {"risk_pct": best["risk_pct"], "max_slots": best["max_slots"]},
                "oos_baseline": {k: oos[k] for k in ("final_equity", "monthly_roi", "max_drawdown",
                                                     "total_trades", "win_rate", "profit_factor")},
                "oos_stress": stress_res,
                "per_month": {m: {"pnl": round(v["pnl"], 2), "trades": v["trades"], "wins": v["wins"]}
                              for m, v in mby.items()},
                "per_pair": {s2: {"trades": c["trades"], "pnl": round(c["profit"], 2), "wins": c["wins"]}
                             for s2, c in cb.items()},
            })

        # ---- leave-one-pair-out on the REFERENCE test window (robustness) ----
        ref = [f for f in fold_reports if f["is_reference"]][0]
        ts_tr, ali_tr, m_tr = slice_window(timestamps, aligned, 0, REF_FOLD[1])
        ts_te, ali_te, m_te = slice_window(timestamps, aligned, REF_FOLD[1], REF_FOLD[2])
        sel = ref["selected"]
        print(f"\n  LOPO on REF test window ({sel['risk_pct']}% risk / {sel['max_slots']} slots, baseline cost):")
        lopo = {}
        for sym in list(aligned.keys()):
            r = run_cfg(engine, ts_te, {k: v for k, v in ali_te.items() if k != sym},
                        m_te, sel["risk_pct"], sel["max_slots"], BASELINE)
            lopo[sym] = {"monthly_roi": round(r["monthly_roi"], 2),
                         "max_drawdown": round(r["max_drawdown"], 2)}
            print(f"    without {sym:<12}: {r['monthly_roi']:+.2f}%/mo | DD {r['max_drawdown']:.2f}%")

        # ---- aggregate the 3 NON-overlapping OOS folds ----
        real_folds = [f for f in fold_reports if not f["is_reference"]]
        growth = 1.0
        months = 0.0
        trades = 0
        worst_dd = 0.0
        for f in real_folds:
            b = f["oos_baseline"]
            growth *= (1.0 + b["monthly_roi"] / 100.0) ** f["test_months"]
            months += f["test_months"]
            trades += b["total_trades"]
            worst_dd = max(worst_dd, b["max_drawdown"])
        agg_monthly = (growth ** (1.0 / months) - 1.0) * 100.0
        # stress-2 aggregate
        growth2, worst2 = 1.0, 0.0
        for f in real_folds:
            b2 = f["oos_stress"][STRESS2["label"]]
            growth2 *= (1.0 + b2["monthly_roi"] / 100.0) ** f["test_months"]
            worst2 = max(worst2, b2["max_drawdown"])
        agg2 = (growth2 ** (1.0 / months) - 1.0) * 100.0
        print(f"\n>>> {ds_name} DEEP OOS AGGREGATE (3 non-overlapping folds, {months:.2f} unseen months):")
        print(f"    baseline: {agg_monthly:+.2f}%/mo compounded | worst fold DD {worst_dd:.2f}% "
              f"| {trades} trades | DD<=15%: {'PASS' if worst_dd <= DD_LIMIT_PCT else 'BREACH'}")
        print(f"    stress-2: {agg2:+.2f}%/mo compounded | worst fold DD {worst2:.2f}% "
              f"| DD<=15%: {'PASS' if worst2 <= DD_LIMIT_PCT else 'BREACH'}")
        summaries.append({
            "dataset": ds_name, "folds": fold_reports, "lopo": lopo,
            "oos_months": round(months, 2),
            "agg_monthly_pct": round(agg_monthly, 2),
            "agg_stress2_monthly_pct": round(agg2, 2),
            "worst_dd_pct": round(worst_dd, 2),
            "worst_stress2_dd_pct": round(worst2, 2),
            "total_trades": trades,
        })

    print("\n" + "=" * 105)
    print("DEEP CRYPTO SUMMARY")
    print("=" * 105)
    for s in summaries:
        print(f"{s['dataset']}: {s['oos_months']:.2f} unseen months | "
              f"baseline {s['agg_monthly_pct']:+.2f}%/mo (worst DD {s['worst_dd_pct']:.2f}%) | "
              f"stress-2 {s['agg_stress2_monthly_pct']:+.2f}%/mo (worst DD {s['worst_stress2_dd_pct']:.2f}%) | "
              f"{s['total_trades']} trades")

    if args.record:
        from core.analysis.roi_ledger import ROILedger
        ledger = ROILedger()
        for s in summaries:
            exp_id = {"crypto22": "EXP-019A-CRYPTO22-DEEP-OOS",
                      "crypto24": "EXP-019B-CRYPTO24-DEEP-OOS"}[s["dataset"]]
            ref = [f for f in s["folds"] if f["is_reference"]][0]
            ledger.record_experiment(
                experiment_id=exp_id,
                strategy_name="Dual-Slot Shared Pool -- Deep Crypto-Only Walk-Forward (post-bugfix)",
                asset="Crypto perps only (user decision: crypto-first deployment)",
                timeframe="H4 Actual Historical Candles",
                duration_desc=f"3 non-overlapping OOS folds, {s['oos_months']} unseen months",
                params={
                    "risk_grid_pct": RISK_GRID, "slot_grid": SLOT_GRID, "leverage": LEV,
                    "selection_rule": f"max train monthly ROI with train max-DD <= {DD_LIMIT_PCT}%",
                    "fill_cost_baseline": BASELINE, "fill_cost_stress1": STRESS1,
                    "fill_cost_stress2": STRESS2,
                    "reference_fold_oos": ref["oos_baseline"],
                    "reference_fold_selected": ref["selected"],
                    "lopo_monthly_roi_pct": {k: v["monthly_roi"] for k, v in s["lopo"].items()},
                },
                results={
                    "months_elapsed": s["oos_months"],
                    "monthly_roi_pct": s["agg_monthly_pct"],
                    "max_drawdown_pct": s["worst_dd_pct"],
                    "total_trades": s["total_trades"],
                    "stress2_monthly_roi_pct": s["agg_stress2_monthly_pct"],
                    "stress2_max_drawdown_pct": s["worst_stress2_dd_pct"],
                    "initial_capital": INITIAL_CAPITAL,
                },
                notes=("Deep crypto-only walk-forward: 3 non-overlapping held-out folds per dataset, "
                       "config selected on TRAIN only. Stress runs raise stop slippage to 0.15%/0.30% "
                       "and taker fee to 0.075%/0.10% to test fill-cost sensitivity. LOPO = test-window "
                       "robustness dropping one pair at a time. See docs/CRYPTO_ROI_DEEP_VALIDATION.md."),
                tag="CRYPTO_DEEP_WALKFORWARD_OOS",
                create_savepoint=True,
            )
        print("\nRecorded EXP-019A/B into reports/roi_progress_ledger.json")


if __name__ == "__main__":
    main()
