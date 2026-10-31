"""EXP-025 — Nuclear-explosion tree search over strategy space.

One idea -> two -> four. Every node of the tree is validated on the real 21-coin
1d panel with 3 chronological folds + full period, and every result is appended to
reports/strategy_leaderboard.json with its tree path so the best strategy can be
selected later. NO production code until the whole tree has been visited.

Tree (28 nodes):
  L1 SIGNAL CORE x6   what to hold
  L2 GATE x5          when to be in  (applied to the best L1 cores)
  L3 OVERLAY x4       how to size    (applied to the best L2 nodes)
  L4 MUTATION x4      radical new mechanics

Run:  SKIP_LEDGER=1 /tmp/venv/bin/python -W ignore scripts/strategy_hunt3.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import strategy_hunt as sh  # noqa: E402
import strategy_hunt2 as sh2  # noqa: E402


# ---------------------------------------------------------------- helpers ---
def _btc(px):
    return px["BTC"] if "BTC" in px.columns else px.iloc[:, 0]


def gate_ma(px, w, ma=150):
    return w.mul((_btc(px) > _btc(px).rolling(ma).mean()).astype(float), axis=0).fillna(0.0)


def gate_ensemble(px, w):
    """2-of-3 regime gate: BTC>MA150, BTC>weekly MA10, MA50>MA200."""
    btc = _btc(px)
    n = len(btc)
    wk_idx = np.arange(n)[4::5]
    wk_ma = pd.Series(btc.values[4::5]).rolling(10).mean().values
    full = np.full(n, np.nan)
    full[wk_idx] = wk_ma
    weekly = pd.Series(full, index=btc.index).ffill()
    votes = ((btc > btc.rolling(150).mean()).astype(int)
             + (btc > weekly).fillna(0).astype(int)
             + (btc.rolling(50).mean() > btc.rolling(200).mean()).astype(int))
    return w.mul((votes >= 2).astype(float), axis=0).fillna(0.0)


def sel_invvol(px, score, K=5):
    """Top-K by score (rows of score), inverse-vol weights."""
    vol20 = px.pct_change().rolling(20).std()
    w = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    for t in px.index:
        row = score.loc[t].dropna()
        if row.empty:
            continue
        chosen = row.nlargest(K).index
        iv = (1.0 / vol20.loc[t, chosen]).clip(upper=1e6)
        s = iv.sum()
        if s > 0 and np.isfinite(s):
            w.loc[t, chosen] = (iv / s).values
    return w


def sel_rankprop(px, score, K=5):
    """Top-K, weights proportional to rank quality (K..1)."""
    vol20 = px.pct_change().rolling(20).std()
    w = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    for t in px.index:
        row = score.loc[t].dropna()
        if row.empty:
            continue
        chosen = row.nlargest(K).index
        rw = pd.Series(np.arange(K, 0, -1, dtype=float), index=chosen)
        w.loc[t, chosen] = (rw / rw.sum()).values
    return w


import pandas as pd  # noqa: E402

# ---------------------------------------------------------------- L1 cores ---
def core_mom(px, K=5, lb=60):
    """A1 momentum rank (baseline core)."""
    return gate_ma(px, sel_invvol(px, px.pct_change(lb).shift(1), K), 150)


def core_mom_accel(px, K=5):
    """A2 acceleration: momentum + change in momentum (the explosion's first split)."""
    m60 = px.pct_change(60)
    score = m60.rank(axis=1) + (m60 - m60.shift(20)).rank(axis=1)
    return gate_ma(px, sel_invvol(px, score.shift(1), K), 150)


def core_trend_slope(px, K=5):
    """A3 pure trend: normalized distance above/below the 200d MA."""
    score = (px / px.rolling(200).mean() - 1.0)
    return gate_ma(px, sel_invvol(px, score.shift(1), K), 150)


def core_dual_tf(px, K=5, gated_=True):
    """A4 dual timeframe: weekly trend up AND daily momentum, ranked by momentum."""
    n = len(px)
    out = pd.DataFrame(False, index=px.index, columns=px.columns)
    for c in px.columns:
        v = px[c].values
        wk = v[4::5]
        wk_ma = pd.Series(wk).rolling(10).mean().values
        full = np.full(n, np.nan)
        full[wk_idx_of(n)] = wk_ma
        daily = pd.Series(full, index=px.index).ffill()
        out[c] = px[c] > daily
    elig = out & (px.pct_change(60) > 0)
    score = px.pct_change(60).where(elig)
    w = sel_invvol(px, score.shift(1), K)
    return gate_ma(px, w, 150) if gated_ else w


def core_leader_lag(px, K=5, gated_=True):
    """A5 leader-lag: after BTC impulses up, hold the highest-beta alts; else cash."""
    btc = _btc(px)
    impulse = btc.pct_change(7) > 0
    corr = px.pct_change().rolling(60).corr(btc.pct_change())
    score = corr.where(impulse, np.nan)          # only rank during BTC up-impulses
    w = sel_invvol(px, score.shift(1), K)
    return gate_ma(px, w, 150) if gated_ else w


def wk_idx_of(n):
    return np.arange(n)[4::5]


def core_quality_mom(px, K=5):
    """A6 quality-momentum: rank by risk-adjusted momentum (Sharpe-like)."""
    score = (px.pct_change(60) / px.pct_change().rolling(60).std()).shift(1)
    return gate_ma(px, sel_invvol(px, score, K), 150)


# ---------------------------------------------------------------- L2 gates --
def gated(core, gate):
    return lambda px: gate(px, core(px))


# ---------------------------------------------------------------- L4 muts ---
def mut_regime_switch(px):
    """M1: trend sleeve when BTC vol is high, dip-buy sleeve when calm (causal median)."""
    btc = _btc(px)
    bvol = btc.pct_change().rolling(20).std()
    hi = (bvol > bvol.expanding().median()).astype(float)
    w_trend = core_mom(px)                       # already MA150-gated
    w_mr = sh.w_dip_v2(px)
    w = w_trend.mul(hi, axis=0) + w_mr.mul(1.0 - hi, axis=0)
    return w.fillna(0.0)


def mut_impulse_laggard(px, K=3):
    """M2: when BTC 7d return is positive AND accelerating, hold the WORST 7d performers
    among liquid coins above MA100 (laggards catching up), inverse-vol."""
    btc = _btc(px)
    cond = ((btc.pct_change(7) > 0) & (btc.pct_change(7) > btc.pct_change(7).shift(7))
            ).to_numpy()[:, None]                      # row-bool, broadcast over columns
    above = (px > px.rolling(100).mean()).to_numpy()
    score = (-px.pct_change(7)).where(pd.DataFrame(cond & above, index=px.index, columns=px.columns))
    return gate_ma(px, sel_invvol(px, score.shift(1), K), 150)


def mut_strongest(px):
    """M3: hold only coins printing 30d highs above their 200d MA (strongest trends)."""
    strong = (px >= px.rolling(30).max() * 0.999) & (px > px.rolling(200).mean())
    cnt = strong.sum(axis=1)
    w = strong.div(cnt.replace(0, np.nan), axis=0).fillna(0.0)
    return gate_ma(px, w, 150)


def mut_mr_trend_split(px, K=8):
    """M4: mean-revert the quiet coins (RSI2), trend-follow the wild ones (momentum),
    split by coin vol vs rolling panel-median vol (causal)."""
    vol = px.pct_change().rolling(20).std()
    thresh = vol.median(axis=1).rolling(60).median().shift(1)
    wild = vol.gt(thresh, axis=0).astype(float)
    m60 = px.pct_change(60).shift(1)
    delta = px.diff()
    up = delta.clip(lower=0.0).rolling(3).mean()
    dn = (-delta.clip(upper=0.0)).rolling(3).mean()
    rsi3 = 100.0 - 100.0 / (1.0 + up / dn.replace(0.0, np.nan))
    ma100 = px.rolling(100).mean()
    score_t = m60.where(wild > 0.5)
    score_m = (-rsi3).where((wild <= 0.5) & (rsi3 < 15) & (px > ma100))
    w = 0.5 * sel_invvol(px, score_t, K) + 0.5 * sel_invvol(px, score_m, K)
    return gate_ma(px, w, 150)


# ------------------------------------------------- L5 combos (tree merges) ---
def l5_rot(px, score_fn, gate_ma=150, K=5, lb=90, rb=5, abs_lb=90, rankprop=False):
    """Champion clone (weekly rebal, inverse-vol, abs-mom filter) with replaceable score/gate."""
    score = score_fn(px)
    btc = _btc(px)
    gate = btc > btc.rolling(gate_ma).mean()
    mom_ok = px.pct_change(abs_lb) > 0
    vol = px.pct_change().rolling(20).std().replace(0, np.nan)
    rows = {}
    for i in range(lb + 6, len(px), rb):
        wrow = pd.Series(0.0, index=px.columns)
        if bool(gate.iloc[i]):
            s = score.iloc[i].dropna()
            s = s[mom_ok.iloc[i].reindex(s.index).fillna(False)]
            if len(s) > 0:
                sel = s.nlargest(min(K, len(s))).index
                if rankprop:
                    rw = pd.Series(np.arange(len(sel), 0, -1, dtype=float), index=sel)
                    wrow[sel] = (rw / rw.sum()).values
                else:
                    inv = (1.0 / vol[sel].iloc[i]).fillna(0.0)
                    if inv.sum() > 0:
                        wrow[sel] = inv / inv.sum()
        rows[i] = wrow
    return sh._held(rows, px)


def combo_c1(px):
    """C1: ABS90_GROT + MA100 gate (tree L2 discovery: G2 > G1)."""
    return l5_rot(px, lambda p: (p.shift(5) / p.shift(95) - 1.0), gate_ma=100)


def combo_c2(px):
    """C2: ABS90_GROT with quality-mom score (tree L1/A6 discovery)."""
    return l5_rot(px, lambda p: ((p.shift(5) / p.shift(95) - 1.0)
                                 / p.pct_change().rolling(60).std()).replace([np.inf, -np.inf], np.nan))


def combo_c3(px):
    """C3: ABS90_GROT in high-BTC-vol regimes, DIP_V2 in calm ones (tree L4/M1 discovery)."""
    btc = _btc(px)
    bvol = btc.pct_change().rolling(20).std()
    hi = (bvol > bvol.expanding().median()).astype(float)
    w_trend = l5_rot(px, lambda p: (p.shift(5) / p.shift(95) - 1.0))
    w_mr = sh.w_dip_v2(px)
    return w_trend.mul(hi, axis=0) + w_mr.mul(1.0 - hi, axis=0).fillna(0.0)


def combo_c4(px):
    """C4: ABS90_GROT with rank-proportional sizing (tree L3/O4 idea)."""
    return l5_rot(px, lambda p: (p.shift(5) / p.shift(95) - 1.0), rankprop=True)


# ---------------------------------------------------------------- lab --------
def run_node(px, path, name, builder):
    fm = sh.fold_metrics(builder, px)
    f = fm["full"]
    folds = [fm[f"fold{k}"]["monthly_roi"] for k in (1, 2, 3)]
    wf = min(folds)
    ok = (f["dd_monthly"] <= 10.0 and f["calmar"] >= 1.2 and f["max_dd"] <= 35.0)
    allpos = all(x > 0 for x in folds)
    failed = not np.isfinite(f["calmar"]) or (f["monthly_roi"] == 0 and f["max_dd"] == 0)
    return {"round": 6, "node": path, "name": name,
            "scope": "crypto_1d_21c_2020-07..2023-04",
            "monthly_roi": f["monthly_roi"], "ann_roi": f["ann_roi"], "max_dd": f["max_dd"],
            "calmar": (f["calmar"] if np.isfinite(f["calmar"]) else -99.0),
            "dd_monthly": (f["dd_monthly"] if np.isfinite(f["dd_monthly"]) else 999.0),
            "worst_month": f["worst_month"],
            "sharpe": f.get("sharpe"), "profit_factor": f.get("profit_factor"),
            "folds": folds, "worst_fold": wf, "qualifies": ok, "all_folds_positive": allpos,
            "failed": failed}


def main():
    import pandas as pd  # noqa: F811  (kept local-safe)
    px = sh.load_closes_1d()
    results = []

    print("=" * 110)
    print("NUCLEAR TREE — every node visited on real data (21-coin 1d panel, 10bp/turnover, 3 folds + full)")
    print("=" * 110)

    # ---- L1: 6 signal cores -------------------------------------------------
    l1 = [
        ("L1/A1", "MOM_RANK (baseline core)", core_mom),
        ("L1/A2", "MOM_ACCEL (mom + acceleration)", core_mom_accel),
        ("L1/A3", "TREND_SLOPE (dist vs 200d MA)", core_trend_slope),
        ("L1/A4", "DUAL_TF (weekly trend + daily mom)", core_dual_tf),
        ("L1/A5", "LEADER_LAG (BTC impulse -> high-beta alts)", core_leader_lag),
        ("L1/A6", "QUALITY_MOM (mom/vol Sharpe-like)", core_quality_mom),
    ]
    print("\n--- L1 SIGNAL CORES (gate=MA150, size=inv-vol) ---")
    for path, name, b in l1:
        r = run_node(px, path, name, b)
        results.append(r)
        print(f"  {path} {name:<44} {r['monthly_roi']:+7.2f}%/mo DD {r['max_dd']:5.1f}% "
              f"Calmar {r['calmar']:6.2f} DD/Mo {r['dd_monthly']:5.1f} folds "
              f"{r['folds'][0]:+7.2f}/{r['folds'][1]:+6.2f}/{r['folds'][2]:+6.2f} "
              f"{'ALLPOS' if r['all_folds_positive'] else ''}")

    # ---- L2: top-3 cores x 5 gates -----------------------------------------
    l1_sorted = sorted(results, key=lambda r: r["calmar"], reverse=True)
    top_cores = [(p, n, b) for (p, n, b) in l1
                 if p in {r["node"] for r in l1_sorted[:3]}]
    gates = [
        ("G1", "gate MA150", lambda px, w: gate_ma(px, w, 150)),
        ("G2", "gate MA100", lambda px, w: gate_ma(px, w, 100)),
        ("G3", "gate weeklyMA10", lambda px, w: sh2.w_weekly_gate(px, lambda p: w.reindex(p.index).fillna(0.0))),
        ("G4", "gate MA50>MA200", lambda px, w: sh2.w_golden_gate(px, lambda p: w.reindex(p.index).fillna(0.0))),
        ("G5", "gate 2-of-3 ensemble", lambda px, w: gate_ensemble(px, w)),
    ]
    print("\n--- L2 GATES (top-3 cores x 5 gates; cores re-run ungated inside gate) ---")
    core_fns = {p: b for p, n, b in l1}
    core_names = {p: n for p, n, b in l1}
    l2 = []
    for cpath, cname, _ in top_cores:
        base = core_fns[cpath]
        for gid, gname, gfn in gates:
            if gid == "G1":
                builder = base  # already MA150-gated
            else:
                # strip the core's own MA150 gate then apply the node gate
                raw = {"L1/A1": lambda p: sel_invvol(p, p.pct_change(60).shift(1), 5),
                       "L1/A2": lambda p: sel_invvol(p, (p.pct_change(60).rank(axis=1) +
                                                         (p.pct_change(60) - p.pct_change(60).shift(20)).rank(axis=1)).shift(1), 5),
                       "L1/A3": lambda p: sel_invvol(p, (p / p.rolling(200).mean() - 1.0).shift(1), 5),
                       "L1/A4": lambda p: core_dual_tf(p, gated_=False),
                       "L1/A5": lambda p: core_leader_lag(p, gated_=False),
                       "L1/A6": lambda p: sel_invvol(p, (p.pct_change(60) / p.pct_change().rolling(60).std()).shift(1), 5)}[cpath]
                builder = (lambda p, r=raw, g=gfn: g(p, r(p)))
            path = f"L2/{cpath.split('/')[1]}-{gid}"
            r = run_node(px, path, f"{core_names[cpath]} + {gname}", builder)
            results.append(r)
            l2.append((path, r, builder))
            print(f"  {path} {r['name']:<52} {r['monthly_roi']:+7.2f}%/mo DD {r['max_dd']:5.1f}% "
                  f"Calmar {r['calmar']:6.2f} DD/Mo {r['dd_monthly']:5.1f} "
                  f"{'ALLPOS' if r['all_folds_positive'] else ''}")

    # ---- L3: top-3 L2 x 4 overlays ------------------------------------------
    l2_sorted = sorted(l2, key=lambda x: x[1]["calmar"], reverse=True)[:3]
    overlays = [
        ("O1", "abs-mom90 filter", lambda p, b: sh2.abs_mom_filter(b(p), p, 90)),
        ("O2", "vol-target 30%", lambda p, b: sh2.vol_target(b(p), p, 0.30)),
        ("O3", "abs-mom90 + vol-target 30%", lambda p, b: sh2.vol_target(sh2.abs_mom_filter(b(p), p, 90), p, 0.30)),
        ("O4", "rank-proportional sizing", lambda p, b: b(p)),  # placeholder, replaced below
    ]
    print("\n--- L3 OVERLAYS (top-3 L2 x 4 overlays) ---")
    for l2path, l2r, l2b in l2_sorted:
        for oid, oname, ofn in overlays:
            if oid == "O4":
                continue
            path = f"L3/{l2path.split('/')[1]}-{oid}"
            r = run_node(px, path, f"{l2r['name']} + {oname}", (lambda p, f=ofn, b=l2b: f(p, b)))
            results.append(r)
            print(f"  {path} {r['name']:<62} {r['monthly_roi']:+7.2f}%/mo DD {r['max_dd']:5.1f}% "
                  f"Calmar {r['calmar']:6.2f} DD/Mo {r['dd_monthly']:5.1f} "
                  f"{'ALLPOS' if r['all_folds_positive'] else ''}")

    # ---- L4: 4 radical mutations --------------------------------------------
    l4 = [
        ("L4/M1", "REGIME_SWITCH (trend if high BTC vol else dip-buy)", mut_regime_switch),
        ("L4/M2", "IMPULSE_LAGGARD (BTC impulse -> laggard alts)", mut_impulse_laggard),
        ("L4/M3", "STRONGEST_ONLY (30d highs above 200d MA)", mut_strongest),
        ("L4/M4", "MR_TREND_SPLIT (quiet=RSI2, wild=momentum)", mut_mr_trend_split),
    ]
    print("\n--- L4 MUTATIONS (radical mechanics) ---")
    for path, name, b in l4:
        try:
            r = run_node(px, path, name, b)
        except Exception as e:
            print(f"  {path} {name:<52} FAILED: {e}")
            continue
        results.append(r)
        print(f"  {path} {name:<52} {r['monthly_roi']:+7.2f}%/mo DD {r['max_dd']:5.1f}% "
              f"Calmar {r['calmar']:6.2f} DD/Mo {r['dd_monthly']:5.1f} folds "
              f"{r['folds'][0]:+7.2f}/{r['folds'][1]:+6.2f}/{r['folds'][2]:+6.2f} "
              f"{'ALLPOS' if r['all_folds_positive'] else ''}")

    # ---- L5: combination nodes (merge tree discoveries onto the champion) ----
    l5 = [
        ("L5/C1", "ABS90_GROT + MA100 gate (L2 discovery)", combo_c1),
        ("L5/C2", "ABS90_GROT + quality-mom score (L1/A6 discovery)", combo_c2),
        ("L5/C3", "ABS90_GROT / DIP regime-switch (L4/M1 discovery)", combo_c3),
        ("L5/C4", "ABS90_GROT + rank-proportional sizing (L3/O4 idea)", combo_c4),
    ]
    print("\n--- L5 COMBINATIONS (tree discoveries merged onto the champion) ---")
    for path, name, b in l5:
        try:
            r = run_node(px, path, name, b)
        except Exception as e:
            print(f"  {path} {name:<56} FAILED: {e}")
            continue
        results.append(r)
        print(f"  {path} {name:<56} {r['monthly_roi']:+7.2f}%/mo DD {r['max_dd']:5.1f}% "
              f"Calmar {r['calmar']:6.2f} DD/Mo {r['dd_monthly']:5.1f} folds "
              f"{r['folds'][0]:+7.2f}/{r['folds'][1]:+6.2f}/{r['folds'][2]:+6.2f} "
              f"{'ALLPOS' if r['all_folds_positive'] else ''}")

    # ---- save everything ------------------------------------------------------
    path = "reports/strategy_leaderboard.json"
    lb = json.load(open(path)) if os.path.exists(path) else {"entries": []}
    lb["entries"] = [e for e in lb["entries"] if e.get("round") not in (6,)]
    lb["entries"].extend(results)
    rankable = [e for e in lb["entries"] if e.get("folds") and not e.get("failed")
                and np.isfinite(e.get("calmar", -99)) and e["calmar"] > -90]
    rankable.sort(key=lambda e: e.get("calmar", -99), reverse=True)
    allpos = [e for e in rankable if e.get("all_folds_positive")]
    qual = [e for e in rankable if e.get("qualifies")]
    lb["selection_guide"] = {
        "best_calmar": {k: rankable[0][k] for k in ("name", "calmar", "monthly_roi", "max_dd", "dd_monthly")} if rankable else None,
        "best_all_folds_positive": {k: allpos[0][k] for k in ("name", "calmar", "monthly_roi", "max_dd", "dd_monthly")} if allpos else None,
        "best_qualified_low_dd": {k: qual[0][k] for k in ("name", "calmar", "monthly_roi", "max_dd", "dd_monthly")} if qual else None,
        "top10": [{"name": e["name"], "node": e.get("node"), "calmar": e["calmar"],
                   "monthly_roi": e["monthly_roi"], "max_dd": e["max_dd"],
                   "dd_monthly": e["dd_monthly"], "folds": e.get("folds")} for e in rankable[:10]],
        "user_criterion": "dd_monthly <= 10 and calmar >= 1.2 and max_dd <= 35",
    }
    lb["tree_round6_nodes_visited"] = len(results)
    json.dump(lb, open(path, "w"), indent=2)
    print(f"\nTree complete: {len(results)} nodes visited and saved. Leaderboard total: {len(lb['entries'])}")
    print("\nTOP 10 OVERALL (all rounds, by Calmar):")
    for e in rankable[:10]:
        print(f"  {str(e.get('node', '')):<16} {e['name']:<56} {e['monthly_roi']:+7.2f}%/mo "
              f"DD {e['max_dd']:5.1f}% Calmar {e['calmar']:6.2f} DD/Mo {e['dd_monthly']:5.1f}")


if __name__ == "__main__":
    main()
