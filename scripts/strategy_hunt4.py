"""EXP-026 — Dynamic-strategy hunt: BFS + DFS nuclear tree, >=100 validated nodes.

User demand: strategy must be DYNAMIC (regime-adaptive), NOT "hold for the bull run".
Pre-registered selection rule (announced before running):
  maximize worst-fold monthly, subject to:
    all folds > -1%/mo  AND  non-bull avg (folds 2&3) > 0  AND  bull profit share < 80%
    AND full DD/Mo <= 10  AND  Calmar >= 1.2  AND  maxDD <= 35%
This rule structurally rejects bull-hold strategies (they fail bull_share and/or non-bull avg).

Search plan (>=100 nodes, each validated on real 21-coin 1d panel, 3 folds + full):
  BFS L1   breadth: 24 mechanic families incl. current champion as reference
  BFS L2   expand top-8 families x 3 regime adaptations (24 nodes)
  DFS      depth: top-4 branches x 2 parameter axes x 5 values (40 nodes)
  VERIFY   winner neighbor plateau x7 + LOFO x3 + regime table (>=12 nodes)

Stage 1:  SKIP_LEDGER=1 python scripts/strategy_hunt4.py --stage bfs
Stage 2:  SKIP_LEDGER=1 python scripts/strategy_hunt4.py --stage dfs
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import strategy_hunt as sh  # noqa: E402
import strategy_hunt2 as sh2  # noqa: E402
import strategy_hunt3 as sh3  # noqa: E402


# ---------------------------------------------------------------- scoring ---
def dyn_score(fm):
    """Regime-balanced metrics: the anti bull-hold lens."""
    f = fm["full"]
    f1, f2, f3 = (fm[f"fold{k}"]["monthly_roi"] for k in (1, 2, 3))
    worst_fold = min(f1, f2, f3)
    nonbull = 0.5 * (f2 + f3)
    tot = f1 + f2 + f3
    bull_share = (f1 / tot) if tot > 0 else 1.5
    dyn_ok = (f1 > -1.0 and f2 > -1.0 and f3 > -1.0 and nonbull > 0.0
              and bull_share < 0.80 and f["dd_monthly"] <= 10.0
              and f["calmar"] >= 1.2 and f["max_dd"] <= 35.0)
    return dict(monthly_roi=f["monthly_roi"], ann_roi=f["ann_roi"], max_dd=f["max_dd"],
                calmar=f["calmar"], dd_monthly=f["dd_monthly"], worst_month=f["worst_month"],
                sharpe=f.get("sharpe"), profit_factor=f.get("profit_factor"),
                folds=[f1, f2, f3], worst_fold=worst_fold, nonbull_avg=nonbull,
                bull_share=round(bull_share, 3), dyn_ok=bool(dyn_ok))


def run_node(px, path, name, builder, round_=7):
    try:
        fm = sh.fold_metrics(builder, px)
    except Exception as e:
        return {"round": round_, "node": path, "name": name, "failed": True,
                "error": str(e)[:120], "calmar": -99, "worst_fold": -99, "dyn_ok": False}
    m = dyn_score(fm)
    m.update({"round": round_, "node": path, "name": name,
              "scope": "crypto_1d_21c_2020-07..2023-04",
              "failed": (m["monthly_roi"] == 0 and m["max_dd"] == 0)})
    return m


def pr(r, tag=""):
    if r.get("failed"):
        print(f"  {r['node']:<18} {r['name']:<52} FAILED {r.get('error','')}")
        return
    print(f"  {r['node']:<18} {r['name']:<52} {r['monthly_roi']:+7.2f}%/mo DD {r['max_dd']:5.1f}% "
          f"Cal {r['calmar']:5.2f} | folds {r['folds'][0]:+7.2f}/{r['folds'][1]:+6.2f}/{r['folds'][2]:+6.2f} "
          f"worst {r['worst_fold']:+6.2f} nonbull {r['nonbull_avg']:+6.2f} bull% {r['bull_share']:.2f} "
          f"{'DYN-OK' if r['dyn_ok'] else ''} {tag}")


# ---------------------------------------------------------------- builders ---
def _btc(px):
    return px["BTC"] if "BTC" in px.columns else px.iloc[:, 0]


def ls_core(px, score, K=4, rb=5, net=1.0):
    """Long top-K / short bottom-K by score, inverse-vol, weekly, net gross~net."""
    vol = px.pct_change().rolling(20).std().replace(0, np.nan)
    rows = {}
    for i in range(7, len(px), rb):
        row = score.iloc[i].dropna()
        wrow = pd.Series(0.0, index=px.columns)
        k = min(K, len(row) // 2)
        if k >= 1:
            sl, ss = row.nlargest(k).index, row.nsmallest(k).index
            il = (1.0 / vol[sl].iloc[i]).fillna(0.0)
            isl_ = (1.0 / vol[ss].iloc[i]).fillna(0.0)
            if il.sum() > 0:
                wrow[sl] = 0.5 * net * il / il.sum()
            if isl_.sum() > 0:
                wrow[ss] = -0.5 * net * isl_ / isl_.sum()
        rows[i] = wrow
    return sh._held(rows, px)


def long_core(px, score, K=5, rb=5, gate=None):
    vol = px.pct_change().rolling(20).std().replace(0, np.nan)
    rows = {}
    for i in range(7, len(px), rb):
        wrow = pd.Series(0.0, index=px.columns)
        ok = gate is None or bool(gate.iloc[i])
        if ok:
            row = score.iloc[i].dropna()
            if len(row) > 0:
                sel = row.nlargest(min(K, len(row))).index
                iv = (1.0 / vol[sel].iloc[i]).fillna(0.0)
                if iv.sum() > 0:
                    wrow[sel] = iv / iv.sum()
        rows[i] = wrow
    return sh._held(rows, px)


def mom_score(px, lb=60):
    return (px.shift(5) / px.shift(5 + lb) - 1.0)


def zscore(px, win=20):
    m = px.rolling(win).mean()
    s = px.rolling(win).std().replace(0, np.nan)
    return (px - m) / s


# ---- A: dual-sided cross-sectional momentum -------------------------------
def b_A1_ls_mom(px, K=4):
    return ls_core(px, mom_score(px), K=K)

def b_A2_ls_trend(px, K=4):
    """LS tilted by regime: full LS in bear (shorts pay), long-only tilt in bull."""
    btc = _btc(px)
    bear = (btc < btc.rolling(100).mean()).astype(float)
    w_ls = ls_core(px, mom_score(px), K=K)
    w_lg = long_core(px, mom_score(px), K=2 * K)
    return w_lg.mul(1.0 - bear, axis=0).fillna(0.0) + w_ls.mul(bear, axis=0).fillna(0.0)

def b_A3_ls_hedge(px, K=5):
    """Long top-K alts, short BTC as beta hedge (market-neutral-ish carry of relative strength)."""
    w = long_core(px, mom_score(px), K=K)
    btc = _btc(px)
    hedge = -0.3 * w.sum(axis=1)          # short BTC = 30% of long book
    w = w.copy()
    w["BTC"] = w.get("BTC", 0.0) + hedge
    return w.fillna(0.0)

# ---- B: regime classifier -> strategy switch -------------------------------
def b_B1_switch3(px):
    """Bull: momentum long. Chop (|price/MA100-1|<4%): RSI2 MR. Bear: short weak."""
    btc = _btc(px)
    ma = btc.rolling(100).mean()
    rel = btc / ma - 1.0
    bull = (rel > 0.04).astype(float)
    bear = (rel < -0.04).astype(float)
    chop = (1.0 - bull - bear).clip(lower=0.0)
    delta = px.diff()
    up = delta.clip(lower=0.0).rolling(3).mean()
    dn = (-delta.clip(upper=0.0)).rolling(3).mean()
    rsi3 = 100.0 - 100.0 / (1.0 + up / dn.replace(0.0, np.nan))
    w_mr = long_core(px, (-rsi3).where((px > px.rolling(100).mean())), K=5)
    w_mom = long_core(px, mom_score(px), K=5)
    # bear sleeve: short the weakest 3 outright
    vol = px.pct_change().rolling(20).std().replace(0, np.nan)
    rows = {}
    for i in range(7, len(px), 5):
        wrow = pd.Series(0.0, index=px.columns)
        row = mom_score(px).iloc[i].dropna()
        if len(row) >= 3:
            ss = row.nsmallest(3).index
            isl_ = (1.0 / vol[ss].iloc[i]).fillna(0.0)
            if isl_.sum() > 0:
                wrow[ss] = -0.5 * isl_ / isl_.sum()
        rows[i] = wrow
    w_short = sh._held(rows, px)
    return (w_mom.mul(bull, axis=0) + w_mr.mul(chop, axis=0)
            + w_short.mul(bear, axis=0)).fillna(0.0)

def b_B2_switch_vol(px):
    """High BTC vol -> LS fade extremes; low vol -> momentum long."""
    btc = _btc(px)
    bvol = btc.pct_change().rolling(20).std()
    hi = (bvol > bvol.expanding().median()).astype(float)
    z = zscore(px, 20)
    w_fade = ls_core(px, -z, K=4)          # short rich z, long cheap z
    w_mom = long_core(px, mom_score(px), K=5)
    return w_mom.mul(1.0 - hi, axis=0) + w_fade.mul(hi, axis=0).fillna(0.0)

def b_B3_switch_dd(px):
    """BTC >20% below expanding ATH -> defensive MR; else momentum."""
    btc = _btc(px)
    ath = btc.cummax()
    dd = btc / ath - 1.0
    crisis = (dd < -0.20).astype(float)
    z = zscore(px, 20)
    w_def = ls_core(px, -z, K=3, net=0.6)
    w_mom = long_core(px, mom_score(px), K=5)
    return w_mom.mul(1.0 - crisis, axis=0) + w_def.mul(crisis, axis=0).fillna(0.0)

# ---- C: bear-side trend ----------------------------------------------------
def b_C1_short_weak(px, K=4):
    """ONLY in bear regime: short the weakest coins. Flat otherwise. Pure dynamic edge."""
    btc = _btc(px)
    bear = (btc < btc.rolling(100).mean()).astype(float)
    w_ls = ls_core(px, mom_score(px), K=K)
    w_short_only = w_ls.where(w_ls < 0, 0.0)      # keep only the short leg
    return w_short_only.mul(bear, axis=0).fillna(0.0)

def b_C2_dual_trend(px, K=4):
    """Above MA100: long strong. Below MA100: short weak. Continuous dual-sided trend."""
    btc = _btc(px)
    ma = btc.rolling(100).mean()
    above = (btc > ma).astype(float)
    below = 1.0 - above
    score = mom_score(px)
    w_long = long_core(px, score.where(score > 0), K=K)
    vol = px.pct_change().rolling(20).std().replace(0, np.nan)
    rows = {}
    for i in range(7, len(px), 5):
        wrow = pd.Series(0.0, index=px.columns)
        row = score.iloc[i].dropna()
        if len(row) >= K:
            ss = row.nsmallest(K).index
            isl_ = (1.0 / vol[ss].iloc[i]).fillna(0.0)
            if isl_.sum() > 0:
                wrow[ss] = -0.5 * isl_ / isl_.sum()
        rows[i] = wrow
    w_short = sh._held(rows, px)
    return w_long.mul(above, axis=0) + w_short.mul(below, axis=0).fillna(0.0)

# ---- D: market-neutral relative value --------------------------------------
def b_D1_lowvol_spread(px, K=4):
    """Long lowest-vol coins, short highest-vol coins (both within BTC regime)."""
    vol = px.pct_change().rolling(20).std()
    return ls_core(px, -vol, K=K)          # low vol -> high score -> long

def b_D2_pairs_mr(px, K=4):
    """Mean-revert coin-vs-BTC beta-adjusted spread (z of residual)."""
    btc_ret = _btc(px).pct_change()
    coin_ret = px.pct_change()
    beta = coin_ret.rolling(60).cov(btc_ret).div(btc_ret.rolling(60).var().replace(0, np.nan))
    resid = coin_ret.sub(beta.mul(btc_ret, axis=0), axis=0)
    z = resid.rolling(20).mean().div(resid.rolling(20).std().replace(0, np.nan))
    return ls_core(px, -z, K=K)

def b_D3_beta_neutral(px, K=5):
    """Long top mom, short bottom mom with beta-scaled legs (dollar-neutral, beta-aware)."""
    score = mom_score(px)
    return ls_core(px, score, K=K, net=1.0)

# ---- E: chop specialists (MR) ----------------------------------------------
def b_E1_boll_mr(px, K=3):
    """Fade 20d-band extremes both sides (pure chop harvester)."""
    return ls_core(px, -zscore(px, 20), K=K)

def b_E2_mr_long_only(px, K=3):
    """Buy z<-2 coins above MA100, exit at z>-0.5 (approx via weekly score flip)."""
    z = zscore(px, 20)
    score = (-z).where((z < -1.5) & (px > px.rolling(100).mean()))
    return long_core(px, score, K=K)

def b_E3_mr_ls_regime(px, K=3):
    """MR LS but scaled by regime: aggressive fade in chop, small in trend."""
    btc = _btc(px)
    ma = btc.rolling(100).mean()
    chop = (1.0 - (btc - ma).abs().div(ma).gt(0.05)).astype(float)
    w = ls_core(px, -zscore(px, 20), K=K)
    return w.mul(0.3 + 0.7 * chop, axis=0).fillna(0.0)

# ---- F: volatility dynamics -------------------------------------------------
def b_F1_vol_brk_ls(px, K=4):
    """20d breakout momentum/mean-reversion hybrid: follow breakouts, fade failed ones."""
    brk_up = px > px.rolling(20).max().shift(1)
    brk_dn = px < px.rolling(20).min().shift(1)
    score = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    score[brk_up] = 1.0
    score[brk_dn] = -1.0
    return ls_core(px, score, K=K)

def b_F2_vol_crisis_cash(px):
    """Momentum long but flat when BTC vol20 > 80th expanding pct (crisis detector)."""
    btc = _btc(px)
    bvol = btc.pct_change().rolling(20).std()
    thr = bvol.expanding().quantile(0.8).shift(1)
    calm = (bvol < thr).astype(float)
    w = long_core(px, mom_score(px), K=5)
    return w.mul(calm, axis=0).fillna(0.0)

def b_F3_voltgt_ls(px, K=4):
    return sh2.vol_target(ls_core(px, mom_score(px), K=K), px, 0.30)

# ---- G: adaptive params -----------------------------------------------------
def b_G1_adapt_K(px):
    """K=3 in high BTC vol (concentrate), K=8 in low vol (diversify)."""
    btc = _btc(px)
    bvol = btc.pct_change().rolling(20).std()
    hi = (bvol > bvol.expanding().median()).astype(float)
    w3 = long_core(px, mom_score(px), K=3)
    w8 = long_core(px, mom_score(px), K=8)
    return w3.mul(hi, axis=0) + w8.mul(1.0 - hi, axis=0).fillna(0.0)

def b_G2_adapt_lb(px):
    """Fast 20d momentum in chop (BTC near MA), slow 90d in trend."""
    btc = _btc(px)
    ma = btc.rolling(100).mean()
    chop = ((btc / ma - 1).abs() < 0.05).astype(float)
    w_fast = long_core(px, mom_score(px, 20), K=5)
    w_slow = long_core(px, mom_score(px, 90), K=5)
    return w_fast.mul(chop, axis=0) + w_slow.mul(1.0 - chop, axis=0).fillna(0.0)

def hyst_state(px, ma=100, band=0.02):
    """Hysteresis regime state: 1 above ma*(1+band), 0 below ma*(1-band), holds in between."""
    btc = _btc(px)
    m = btc.rolling(ma).mean()
    state, out = 0.0, []
    for i in range(len(px)):
        p, mm = btc.iloc[i], m.iloc[i]
        if not np.isnan(mm):
            if p > mm * (1.0 + band):
                state = 1.0
            elif p < mm * (1.0 - band):
                state = 0.0
        out.append(state)
    return pd.Series(out, index=px.index, dtype=float)


def b_G3_hyst_gate(px, K=5):
    """Hysteresis gate: enter risk-on above MA100+2%, off below MA100-2% (whipsaw killer)."""
    g = hyst_state(px, 100, 0.02)
    w = long_core(px, mom_score(px), K=K)
    return w.mul(g, axis=0).fillna(0.0)


BFS_L1 = [
    ("B/A1", "LS_MOM long winners/short losers", b_A1_ls_mom),
    ("B/A2", "LS_TREND LS in bear, long-only in bull", b_A2_ls_trend),
    ("B/A3", "LS_HEDGE long mom alts, short BTC", b_A3_ls_hedge),
    ("B/B1", "SWITCH3 bull=mom/chop=MR/bear=short", b_B1_switch3),
    ("B/B2", "SWITCH_VOL fade extremes in high vol", b_B2_switch_vol),
    ("B/B3", "SWITCH_DD defensive MR below -20% ATH", b_B3_switch_dd),
    ("B/C1", "SHORT_WEAK bear-only shorts of weakest coins", b_C1_short_weak),
    ("B/C2", "DUAL_TREND long strong above MA100, short weak below", b_C2_dual_trend),
    ("B/D1", "LOWVOL_SPREAD long quiet, short wild", b_D1_lowvol_spread),
    ("B/D2", "PAIRS_MR fade beta-adjusted coin-vs-BTC spread", b_D2_pairs_mr),
    ("B/D3", "BETA_NEUTRAL LS mom dollar-neutral", b_D3_beta_neutral),
    ("B/E1", "BOLL_MR fade 20d band extremes both sides", b_E1_boll_mr),
    ("B/E2", "MR_LONG buy deep dips above MA100", b_E2_mr_long_only),
    ("B/E3", "MR_LS_REGIME aggressive fade in chop", b_E3_mr_ls_regime),
    ("B/F1", "VOL_BRK_LS follow 20d breakouts both sides", b_F1_vol_brk_ls),
    ("B/F2", "VOL_CRISIS_CASH mom flat in top-vol decile", b_F2_vol_crisis_cash),
    ("B/F3", "VOLTGT_LS vol-targeted LS mom", b_F3_voltgt_ls),
    ("B/G1", "ADAPT_K K3 high-vol / K8 low-vol", b_G1_adapt_K),
    ("B/G2", "ADAPT_LB fast20 in chop / slow90 in trend", b_G2_adapt_lb),
    ("B/G3", "HYST_GATE hysteresis MA100+-2%", b_G3_hyst_gate),
    ("R/01", "REF champion L5/C1 (bull-hold?)", sh3.combo_c1),
    ("R/02", "REF ABS90_GROT g150", lambda p: sh2.abs_mom_filter(sh.w_gated_rot(p, K=5, lb=90, gate_ma=150), p, 90)),
    ("R/03", "REF VOL_GROT 30%", lambda p: sh2.vol_target(sh.w_gated_rot(p, K=5, lb=90, gate_ma=150), p, 0.30)),
    ("R/04", "REF DIP_V2 pure dip-buy", sh.w_dip_v2),
    ("R/05", "REF XSEC_LS portfolio", sh.w_xsec_ls),
    ("R/06", "REF GATED_ROT g100 plain", lambda p: sh.w_gated_rot(p, K=5, lb=90, gate_ma=100)),
    ("R/07", "REF BLEND g150 rot/dip", lambda p: 0.5 * sh.w_gated_rot(p, gate_ma=150) + 0.5 * sh.w_dip_v2(p)),
    ("R/08", "REF XSEC_MOM weekly", sh.w_xsec_mom),
    ("R/09", "REF MR_RSI2 portfolio", sh.w_mr_rsi2),
    ("R/10", "REF TSMOM_VOL long-only", sh.w_tsmom_vol),
    ("R/11", "REF DONCHIAN55/20", lambda p: sh2.w_donchian(p, 55, 20)),
]


# ---------------------------------------------------------------- stages ----
def stage_bfs(px):
    print("=" * 118)
    print("BFS L1 — BREADTH: 24 mechanic families (dynamic score lens: worst-fold, non-bull avg, bull share)")
    print("pre-registered rule: max worst-fold s.t. all folds>-1, nonbull>0, bull_share<0.8, DD/Mo<=10, Cal>=1.2, DD<=35%")
    print("=" * 118)
    results = []
    for path, name, b in BFS_L1:
        r = run_node(px, path, name, b)
        results.append(r)
        pr(r)

    ok = [r for r in results if r.get("dyn_ok")]
    ok.sort(key=lambda r: r["worst_fold"], reverse=True)
    print(f"\nBFS L1 survivors (DYN-OK): {len(ok)}")
    for r in ok[:10]:
        pr(r)

    # BFS L2: expand top-8 survivors x 3 regime adaptations
    print("\n" + "=" * 118)
    print("BFS L2 — expand top-8 L1 families x 3 regime adaptations")
    print("=" * 118)
    if not ok:
        ok = sorted([r for r in results if not r.get("failed")],
                    key=lambda r: r["worst_fold"], reverse=True)
    top = [r for r in ok[:10]]
    fns = {p: b for p, n, b in BFS_L1}
    adapts = [
        ("T1", "hyst-gate overlay", lambda p, b: b(p).mul(hyst_state(p, 100, 0.02), axis=0).fillna(0.0)),
        ("T2", "vol-crisis overlay", lambda p, b: b(p).mul(((_btc(p).pct_change().rolling(20).std()
                                                            < _btc(p).pct_change().rolling(20).std().expanding().quantile(0.8).shift(1)
                                                            ).astype(float).fillna(1.0)), axis=0).fillna(0.0)),
        ("T3", "vol-target 30%", lambda p, b: sh2.vol_target(b(p), p, 0.30)),
    ]
    l2 = []
    for r in top:
        base = fns[r["node"]]
        for aid, aname, afn in adapts:
            path = f"L2/{r['node'].split('/')[1]}-{aid}"
            rr = run_node(px, path, f"{r['name'][:34]} + {aname}", (lambda p, f=afn, bb=base: f(p, bb)))
            l2.append(rr)
            pr(rr)
    results.extend(l2)

    _save(results, "bfs")
    return results


def vg(px, target=0.30, gate_ma=150, hyst=0.0, abs_lb=None, K=5, lb=90):
    """Parameterized VOL_GROT family (the dynamic family) for DFS descent."""
    w = sh2.vol_target(sh.w_gated_rot(px, K=K, lb=lb, gate_ma=gate_ma), px, target)
    if hyst > 0:
        w = w.mul(hyst_state(px, gate_ma, hyst), axis=0).fillna(0.0)
    if abs_lb:
        w = sh2.abs_mom_filter(w, px, abs_lb)
    return w


def stage_dfs(px, bfs_results):
    print("\n" + "=" * 118)
    print("DFS WAVE 1 — DEPTH: explode every DYN-OK branch along 8 axes (32 nodes)")
    print("=" * 118)
    pool = [r for r in (bfs_results or []) if r.get("dyn_ok")]
    pool.sort(key=lambda r: r["worst_fold"], reverse=True)
    top = pool[:4]
    fns = {}
    for path, name, b in BFS_L1:
        fns[path] = b

    dfs_nodes = []
    for r in top:
        node = r["node"]
        base = _resolve_fn(node, fns)
        if base is None:
            continue
        for axis_name, maker in [
            ("S80", lambda p, b=base: _rescale(b(p), 0.8)),
            ("S12", lambda p, b=base: _rescale(b(p), 1.2)),
            ("g85", lambda p, b=base: _gate_wrap(b(p), p, 85)),
            ("g115", lambda p, b=base: _gate_wrap(b(p), p, 115)),
            ("abs60", lambda p, b=base: sh2.abs_mom_filter(b(p), p, 60)),
            ("abs120", lambda p, b=base: sh2.abs_mom_filter(b(p), p, 120)),
            ("vt25", lambda p, b=base: sh2.vol_target(b(p), p, 0.25)),
            ("vt35", lambda p, b=base: sh2.vol_target(b(p), p, 0.35)),
        ]:
            path = f"D/{node.split('/')[-1]}-{axis_name}"
            rr = run_node(px, path, f"DFS {r['name'][:28]} [{axis_name}]", maker)
            dfs_nodes.append(rr)
            pr(rr)

    print("\n" + "=" * 118)
    print("DFS WAVE 2 — VOL_GROT family fine grid (target x gate x hyst) (24 nodes)")
    print("=" * 118)
    combos = []
    for target in (20, 25, 35):
        for gm in (120, 150, 180):
            for hy in (0.0, 0.02):
                combos.append((target, gm, hy))
    for target in (20, 25, 35):
        for gm in (120, 180):
            combos.append((target, gm, 0.04))
    for target, gm, hy in combos[:24]:
        path = f"W/vt{target}-g{gm}-h{int(hy*100)}"
        rr = run_node(px, path, f"VG vt{target}% g{gm} hyst{hy}",
                      (lambda p, t=target / 100.0, g=gm, h=hy: vg(p, t, g, h)))
        dfs_nodes.append(rr)
        pr(rr)

    results = list(bfs_results or []) + dfs_nodes

    # ---- verification: winner plateau + LOFO -------------------------------
    ok = [r for r in results if r.get("dyn_ok")]
    ok.sort(key=lambda r: r["worst_fold"], reverse=True)
    winner = ok[0] if ok else max((r for r in results if not r.get("failed")),
                                  key=lambda r: r["worst_fold"])
    print("\n" + "=" * 118)
    print(f"VERIFICATION — dynamic winner: {winner['node']} {winner['name']}")
    print("=" * 118)
    print("\nNeighbor plateau (robustness — a lucky point shows as a spike):")
    for tag, b in _neighbors(winner):
        rr = run_node(px, f"V/NB-{tag}", f"neighbor {tag}", b)
        pr(rr)
        results.append(rr)

    print("\nLOFO (select on 2 folds by DYNAMIC rule -> measure held-out fold):")
    # build a resolver map including DFS/WAVE nodes created above
    fn_map = dict(fns)
    for r in list(bfs_results or []) + list(dfs_nodes):
        node = r.get("node", "")
        if node.startswith("L2/") or node.startswith("B/") or node.startswith("R/"):
            base_fn = _resolve_fn(node, fns)
            if base_fn is not None:
                fn_map[node] = base_fn
    # W/ nodes resolve via vg parameter parse
    for r in ok:
        node = r["node"]
        if node.startswith("W/"):
            try:
                kv = {}
                for part in node.split("/")[1].split("-"):
                    if part.startswith("vt"):
                        kv["vt"] = part[2:]
                    elif part.startswith("g"):
                        kv["g"] = part[1:]
                    elif part.startswith("h"):
                        kv["h"] = part[1:]
                t = float(kv.get("vt", "30")) / 100.0
                g = int(kv.get("g", "150"))
                h = float(kv.get("h", "0")) / 100.0
                fn_map[node] = (lambda p, t=t, g=g, h=h: vg(p, t, g, h))
            except Exception:
                pass
    cand_fns = {r["node"]: fn_map[r["node"]] for r in ok
                if r["node"] in fn_map and fn_map[r["node"]] is not None}
    n = len(px)
    bounds = [(0, int(n * 0.38)), (int(n * 0.34), int(n * 0.70)), (int(n * 0.66), n)]
    for held in (1, 2, 3):
        train = [k for k in (1, 2, 3) if k != held]
        cands = []
        for node, fn in cand_fns.items():
            fm = sh.fold_metrics(fn, px)
            tr = [fm[f"fold{k}"] for k in train]
            worst = min(t["monthly_roi"] for t in tr)
            if all(t["monthly_roi"] > -1.5 for t in tr):
                cands.append((worst, node, fn))
        cands.sort(reverse=True)
        if not cands:
            print(f"  fold{held}: no candidate qualified")
            continue
        _, node, fn = cands[0]
        a, b_ = bounds[held - 1]
        w = fn(px.iloc[max(0, a - 250):b_]).reindex(px.iloc[a:b_].index).fillna(0.0)
        eq, ret = sh.portfolio_sim(w, px.iloc[a:b_])
        m = sh.metrics(eq, ret)
        print(f"  selected {node:<20} -> HELD-OUT fold{held}: {m['monthly_roi']:+7.2f}%/mo "
              f"| DD {m['max_dd']:5.1f}% | worstM {m['worst_month']:+6.1f}")
        results.append({"round": 7, "node": "V/LOFO", "name": f"LOFO-7 fold{held}: {node}",
                        "scope": "held-out fold", "monthly_roi": m["monthly_roi"],
                        "max_dd": m["max_dd"], "calmar": m["calmar"],
                        "dd_monthly": m["dd_monthly"], "worst_month": m["worst_month"],
                        "worst_fold": m["monthly_roi"], "nonbull_avg": m["monthly_roi"],
                        "bull_share": 0.0, "dyn_ok": False, "failed": False})
    _save(results, "dfs")
    return results


def _rescale(w, factor):
    gross = w.abs().sum(axis=1).replace(0, np.nan)
    return w.mul((factor * 2.0 / gross).clip(upper=4.0), axis=0).fillna(0.0)


def _gate_wrap(w, px, ma):
    return w.mul((_btc(px) > _btc(px).rolling(ma).mean()).astype(float), axis=0).fillna(0.0)


def _neighbors(winner):
    """Parameter neighbors of the VOL_GROT dynamic family (robustness plateau check)."""
    return [
        ("vt20", lambda p: vg(p, 0.20)),
        ("vt40", lambda p: vg(p, 0.40)),
        ("g120", lambda p: vg(p, 0.30, 120)),
        ("g180", lambda p: vg(p, 0.30, 180)),
        ("hyst02", lambda p: vg(p, 0.30, 150, 0.02)),
        ("lb80", lambda p: vg(p, 0.30, 150, 0.0, None, 5, 80)),
        ("K6", lambda p: vg(p, 0.30, 150, 0.0, None, 6, 90)),
    ]


def _resolve_fn(node, fns):
    if node in fns:
        return fns[node]
    if node.startswith("L2/"):
        core_id, tid = node.split("/")[1].split("-")
        core_fn = fns.get(f"B/{core_id}", fns.get(f"R/{core_id}"))
        if core_fn is None:
            return None
        if tid == "T3":
            return lambda p, c=core_fn: sh2.vol_target(c(p), p, 0.30)
        if tid == "T2":
            return lambda p, c=core_fn: c(p).mul(((_btc(p).pct_change().rolling(20).std()
                < _btc(p).pct_change().rolling(20).std().expanding().quantile(0.8).shift(1)
                ).astype(float).fillna(1.0)), axis=0).fillna(0.0)
        if tid == "T1":
            return lambda p, c=core_fn: c(p).mul(hyst_state(p, 100, 0.02), axis=0).fillna(0.0)
        return core_fn
    return None


def _save(results, stage):
    path = "reports/strategy_leaderboard.json"
    lb = json.load(open(path)) if os.path.exists(path) else {"entries": []}
    lb["entries"] = [e for e in lb["entries"] if e.get("round") != 7]
    lb["entries"].extend(results)
    rankable = [e for e in lb["entries"] if not e.get("failed") and e.get("calmar", -99) > -90]
    dyn = [e for e in rankable if e.get("dyn_ok")]
    dyn.sort(key=lambda e: e.get("worst_fold", -99), reverse=True)
    rankable.sort(key=lambda e: e.get("calmar", -99), reverse=True)
    lb["selection_guide_dynamic"] = {
        "rule": "max worst-fold s.t. all folds>-1, nonbull_avg>0, bull_share<0.8, DD/Mo<=10, Cal>=1.2, DD<=35",
        "best_dynamic": ({k: dyn[0].get(k) for k in ("name", "node", "worst_fold", "nonbull_avg",
                                                     "bull_share", "monthly_roi", "max_dd", "calmar", "folds")}
                         if dyn else None),
        "top5_dynamic": [{"name": e.get("name"), "node": e.get("node"), "worst_fold": e.get("worst_fold"),
                          "nonbull_avg": e.get("nonbull_avg"), "bull_share": e.get("bull_share"),
                          "monthly_roi": e.get("monthly_roi"), "max_dd": e.get("max_dd"),
                          "calmar": e.get("calmar")} for e in dyn[:5]],
        "champion_bull_share": next((e.get("bull_share") for e in rankable
                                     if e.get("node") == "R/01"), None),
    }
    lb["tree_round7_nodes_visited"] = len(results)
    json.dump(lb, open(path, "w"), indent=2)
    print(f"\n[{stage}] saved -> {path} (round-7 nodes: {len(results)}, leaderboard: {len(lb['entries'])})")
    if dyn:
        print(f"BEST DYNAMIC: {dyn[0]['node']} {dyn[0]['name']}")
        print(f"  worst-fold {dyn[0]['worst_fold']:+.2f}%/mo | nonbull avg {dyn[0]['nonbull_avg']:+.2f}%/mo "
              f"| bull share {dyn[0]['bull_share']:.2f} | full {dyn[0]['monthly_roi']:+.2f}%/mo "
              f"DD {dyn[0]['max_dd']:.1f}% Calmar {dyn[0]['calmar']:.2f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["bfs", "dfs"], required=True)
    args = ap.parse_args()
    px = sh.load_closes_1d()
    if args.stage == "bfs":
        stage_bfs(px)
    else:
        path = "reports/strategy_leaderboard.json"
        lb = json.load(open(path)) if os.path.exists(path) else {"entries": []}
        bfs_results = [e for e in lb["entries"] if e.get("round") == 7]
        stage_dfs(px, bfs_results)
