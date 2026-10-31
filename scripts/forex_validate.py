"""EXP-028 — Forex validation of the hunt winners (and a forex-native FVG sweep).

User: "verify fine whatever winning hunt strategy for Forex back testing as well;
it might be possible that strategy is well performing for Forex but not crypto."

Real data: 4 forex pairs (EURUSD, GBPUSD, EURJPY, XAUUSD), H4 -> daily OHLC,
2012-11 -> 2022-03 (~9.4y). Fees 5bp/turnover side (FX spread proxy). Every node
gets 3 chronological folds + full period with the same dyn_score lens, saved to
reports/strategy_leaderboard.json (round 9, scope=forex).

Run:  SKIP_LEDGER=1 /tmp/venv/bin/python -W ignore scripts/forex_validate.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import strategy_hunt as sh  # noqa: E402
import strategy_hunt2 as sh2  # noqa: E402
import strategy_hunt3 as sh3  # noqa: E402
import strategy_hunt4 as sh4  # noqa: E402
import strategy_hunt5 as sh5  # noqa: E402

FEE_FX = 0.0005  # 5 bps per side of turnover


def load_forex_ohlcv():
    frames = {}
    for name, path in [("EURUSD", "data/forex/EURUSD_H4.csv"), ("GBPUSD", "data/forex/GBPUSD_H4.csv"),
                       ("EURJPY", "data/forex/EURJPY_H4.csv"), ("XAUUSD", "data/forex/XAUUSD_H4.csv")]:
        df = pd.read_csv(path)
        tcol = "timestamp" if "timestamp" in df.columns else df.columns[0]
        df[tcol] = pd.to_datetime(df[tcol])
        df = df.set_index(tcol)
        spec = {"open": "first", "high": "max", "low": "min", "close": "last"}
        if "tick_volume" in df.columns:
            spec["tick_volume"] = "sum"
        elif "volume" in df.columns:
            spec["volume"] = "sum"
        agg = df.resample("1D").agg(spec).dropna(subset=["open", "high", "low", "close"])
        frames[name] = agg
    idx = None
    for agg in frames.values():
        idx = agg.index if idx is None else idx.intersection(agg.index)

    def panel(col):
        frames_ok = {k: frames[k].reindex(idx)[col] for k in frames
                     if col in frames[k].columns}
        return pd.DataFrame(frames_ok).sort_index()
    return panel("open"), panel("high"), panel("low"), panel("close"), panel("tick_volume")


def run_node_fx(px, path, name, builder):
    try:
        fm = sh.fold_metrics(builder, px, fee=FEE_FX)
    except Exception as e:
        return {"round": 9, "node": path, "name": name, "scope": "forex_4p_daily_2012-11..2022-03",
                "failed": True, "error": str(e)[:120], "calmar": -99, "worst_fold": -99,
                "dyn_ok": False}
    m = sh4.dyn_score(fm)
    m.update({"round": 9, "node": path, "name": name,
              "scope": "forex_4p_daily_2012-11..2022-03",
              "failed": (m["monthly_roi"] == 0 and m["max_dd"] == 0)})
    return m


def main():
    O, H, L, C, V = load_forex_ohlcv()
    px = C.dropna(how="any")
    if V.shape[1] == 0:
        V = px * 0.0  # volume not needed by most SMC signals; zeros for absorption node
    # wire OHLC into the SMC harness
    sh5._O, sh5._H, sh5._L, sh5._C, sh5._V = (O.reindex(px.index), H.reindex(px.index),
                                              L.reindex(px.index), px, V.reindex(px.index))
    print(f"Forex daily panel: {len(px)} bars, {px.index[0].date()} .. {px.index[-1].date()}, "
          f"pairs: {list(px.columns)}")

    def variant(sigfn, long_only, hold, K):
        def builder(p, f=sigfn, lo=long_only, h=hold, k=K):
            o, hgh, l, c = sh5.ohlc(p)
            return sh5.smc_pf(p, f(o, hgh, l, c), hold=h, long_only=lo, K=k)
        return builder

    fvg = sh5.smc_sigs_global["02"][0]
    fvg_long = sh5.smc_sigs_global["01"][0]
    ob = sh5.smc_sigs_global["04"][0]
    ob_long = sh5.smc_sigs_global["03"][0]
    sweep = sh5.smc_sigs_global["06"][0]
    sweep_long = sh5.smc_sigs_global["05"][0]

    def fvg_age(age, h=3, K=0):
        return variant((lambda o, hgh, l, c, a=age: sh5.sig_fvg(hgh, l, c, max_age=a)), False, h, K)

    nodes = [
        # ---- crypto winners transferred verbatim ----
        ("FX/01", "FVG_LS age15 h3 (CRYPTO CHAMPION params)", fvg_age(15, 3, 0)),
        ("FX/02", "FVG_LS age20 h3", fvg_age(20, 3, 0)),
        ("FX/03", "FVG_LS age40 h3 (base params)", fvg_age(40, 3, 0)),
        ("FX/04", "FVG_LS age15 h5", fvg_age(15, 5, 0)),
        ("FX/05", "FVG_LS age15 K2 (selective, 4 pairs)", fvg_age(15, 3, 2)),
        ("FX/06", "FVG_LONG age15 h3 (buy-only)", variant(
            (lambda o, hgh, l, c: sh5.sig_fvg(hgh, l, c, max_age=15).clip(lower=0)), True, 3, 0)),
        # ---- rest of SMC family ----
        ("FX/07", "OB_LS h5", variant(ob, False, 5, 0)),
        ("FX/08", "OB_LONG h5", variant(ob_long, True, 5, 0)),
        ("FX/09", "SWEEP_LS h3", variant(sweep, False, 3, 0)),
        ("FX/10", "SWEEP_LONG h3", variant(sweep_long, True, 3, 0)),
        ("FX/11", "BOS_CONT", lambda p: sh5.smc_pf(p, sh5.sig_bos(sh5.ohlc(p)[1], sh5.ohlc(p)[2], sh5.ohlc(p)[3]), hold=5, long_only=False)),
        ("FX/12", "CHOCH_REV", lambda p: sh5.smc_pf(p, sh5.sig_choch(sh5.ohlc(p)[1], sh5.ohlc(p)[2], sh5.ohlc(p)[3]), hold=5, long_only=False)),
        ("FX/13", "PREMDISC", lambda p: sh5.smc_pf(p, sh5.sig_premdisc(sh5.ohlc(p)[1], sh5.ohlc(p)[2], sh5.ohlc(p)[3]), hold=10, long_only=False)),
        ("FX/14", "RANGE_MR", lambda p: sh5.smc_pf(p, sh5.sig_range_mr(sh5.ohlc(p)[1], sh5.ohlc(p)[2], sh5.ohlc(p)[3]), hold=10, long_only=False)),
        ("FX/15", "VOTE h3", lambda p: sh5.smc_pf(p, sh5.sig_vote(sh5.ohlc(p)[1], sh5.ohlc(p)[2], sh5.ohlc(p)[3], sh5.ohlc(p)[0]), hold=3, long_only=False)),
        ("FX/16", "ABSORB", lambda p: sh5.smc_pf(p, sh5.sig_absorb(sh5.ohlc(p)[0], sh5.ohlc(p)[1], sh5.ohlc(p)[2], sh5.ohlc(p)[3], sh5._V.reindex(p.index)), hold=5, long_only=False)),
        # ---- rotation family transferred (K=2 for 4 pairs; gate falls back to col0) ----
        ("FX/20", "GATED_ROT K2 lb60 g150", lambda p: sh.w_gated_rot(p, K=2, lb=60, gate_ma=150)),
        ("FX/21", "GATED_ROT K2 lb90 g150", lambda p: sh.w_gated_rot(p, K=2, lb=90, gate_ma=150)),
        ("FX/22", "VOL_GROT 30% K2 (EXP-026 family)", lambda p: sh2.vol_target(sh.w_gated_rot(p, K=2, lb=90, gate_ma=150), p, 0.30)),
        ("FX/23", "VOL_GROT 30% + hyst K2 (EXP-026 CHAMPION)", lambda p: sh4.vg(p, 0.30, 150, 0.02, None, 2, 90)),
        ("FX/24", "ABS90_GROT K2 (EXP-025 family)", lambda p: sh2.abs_mom_filter(sh.w_gated_rot(p, K=2, lb=90, gate_ma=100), p, 90)),
        ("FX/25", "XSEC_MOM K2 weekly", lambda p: sh.w_xsec_mom(p, K=2)),
        ("FX/26", "DIP_V2", sh.w_dip_v2),
        ("FX/27", "TSMOM_VOL", sh.w_tsmom_vol),
        ("FX/28", "MR_RSI2", sh.w_mr_rsi2),
    ]
    # ---- forex-native FVG sweep (does FX want different gap params?) ----
    for age in (10, 20, 30, 60):
        for h in (2, 3, 5):
            nodes.append((f"FX/W-age{age}h{h}", f"FVG_LS age{age} hold{h} [FX-native]",
                          fvg_age(age, h, 0)))

    print("=" * 118)
    print("FOREX VALIDATION — crypto winners vs FX-native grid (fee 5bp, 3 folds + full)")
    print("=" * 118)
    results = []
    for path, name, b in nodes:
        r = run_node_fx(px, path, name, b)
        results.append(r)
        sh4.pr(r)

    rankable = [r for r in results if not r.get("failed")]
    dyn = [r for r in rankable if r.get("dyn_ok")]
    rankable.sort(key=lambda r: r.get("calmar", -99), reverse=True)
    dyn.sort(key=lambda r: r.get("worst_fold", -99), reverse=True)
    print("\nFOREX TOP by Calmar:")
    for r in rankable[:8]:
        sh4.pr(r)
    print("\nFOREX DYN-OK (all folds>-1, nonbull>0, bull%<0.8, DD/Mo<=10, Cal>=1.2, DD<=35):")
    for r in dyn[:8]:
        sh4.pr(r)

    path_ = "reports/strategy_leaderboard.json"
    lb = json.load(open(path_))
    lb["entries"] = [e for e in lb["entries"] if e.get("round") != 9]
    lb["entries"].extend(results)
    lb["selection_guide_forex"] = {
        "scope": "forex_4p_daily_2012-11..2022-03, fee 5bp",
        "best_calmar": {k: rankable[0].get(k) for k in ("name", "node", "calmar", "monthly_roi",
                                                        "max_dd", "dd_monthly", "folds")}
        if rankable else None,
        "best_dynamic": {k: dyn[0].get(k) for k in ("name", "node", "worst_fold", "nonbull_avg",
                                                    "bull_share", "monthly_roi", "max_dd", "calmar", "folds")}
        if dyn else None,
        "crypto_champion_fx_result": {k: next((e.get(k) for e in results
                                               if e.get("node") == "FX/01"), None)
                                      for k in ("monthly_roi", "max_dd", "calmar", "folds",
                                                "worst_fold", "nonbull_avg", "bull_share")},
    }
    lb["tree_round9_nodes_visited"] = len(results)
    json.dump(lb, open(path_, "w"), indent=2)
    print(f"\nSaved round-9 forex nodes: {len(results)} (leaderboard: {len(lb['entries'])})")


if __name__ == "__main__":
    main()
