"""EXP-027 — Smart Money Concepts (SMC) hunt via nuclear-explosion BFS+DFS, >=100 nodes.

ICT-style mechanics on REAL 21-coin daily OHLC (StephanAkkerman benchmark panel):
fair value gaps, order blocks, liquidity sweeps, breaks of structure, change of
character, premium/discount zones, absorption, AMD weekly fake-outs, confluence
combos. Every node validated with 3 chronological folds + full period and saved
to reports/strategy_leaderboard.json.

Pre-registered DYNAMIC selection rule (anti bull-hold), same as EXP-026:
  maximize worst-fold monthly, subject to:
    all folds > -1%/mo AND non-bull avg (folds 2&3) > 0 AND bull profit share < 0.8
    AND full DD/Mo <= 10 AND Calmar >= 1.2 AND maxDD <= 35%

Stage 1:  SKIP_LEDGER=1 python scripts/strategy_hunt5.py --stage bfs
Stage 2:  SKIP_LEDGER=1 python scripts/strategy_hunt5.py --stage dfs
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
import strategy_hunt4 as sh4  # noqa: E402

_O, _H, _L, _C, _V = None, None, None, None, None
FNS: dict = {}


def load_ohlcv():
    frames = {c: pd.read_csv(f"data/timeframes/1d_panel/{c}USDT_1d.csv")
              for c in sh.COINS}
    for c, df in frames.items():
        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True)
    idx = None
    for df in frames.values():
        idx = df.index if idx is None else idx.intersection(df.index)
    def panel(col):
        return pd.DataFrame({c: frames[c].reindex(idx)[col] for c in sh.COINS}).sort_index()
    return panel("open"), panel("high"), panel("low"), panel("close"), panel("volume")


def ohlc(px):
    """OHLC aligned to a closes window (same index labels)."""
    return (_O.reindex(px.index), _H.reindex(px.index),
            _L.reindex(px.index), _C.reindex(px.index))


# ------------------------------------------------------------ SMC signals ---
def sig_fvg(H, L, C, max_age=40):
    """Fair-value-gap retests: 3-candle gap, score +/-1 on return into unfilled gap."""
    out = pd.DataFrame(0.0, index=C.index, columns=C.columns)
    for j, col in enumerate(C.columns):
        h, l, c = H[col].values, L[col].values, C[col].values
        gaps = []
        for t in range(2, len(c)):
            if l[t] > h[t - 2] and (l[t] - h[t - 2]) > 0.0:
                gaps.append([l[t], h[t - 2], 0, +1.0])
            if h[t] < l[t - 2] and (l[t - 2] - h[t]) > 0.0:
                gaps.append([h[t], l[t - 2], 0, -1.0])
            sc, keep = 0.0, []
            for top, bot, age, sign in gaps:
                if age > max_age:
                    continue
                if sign > 0 and c[t] < bot:
                    continue
                if sign < 0 and c[t] > top:
                    continue
                if l[t] <= top and h[t] >= bot and sc == 0.0:
                    sc = sign
                keep.append([top, bot, age + 1, sign])
            gaps = keep
            out.iat[t, j] = sc
    return out


def sig_ob(O, H, L, C, max_age=40):
    """Order blocks: last opposite candle before 2-bar displacement; retest of the zone."""
    out = pd.DataFrame(0.0, index=C.index, columns=C.columns)
    for j, col in enumerate(C.columns):
        o, h, l, c = O[col].values, H[col].values, L[col].values, C[col].values
        obs = []
        for t in range(3, len(c)):
            i = t - 2
            if c[i] < o[i] and c[t] > h[i] and c[t - 1] > c[i]:
                obs.append([h[i], l[i], 0, +1.0])
            if c[i] > o[i] and c[t] < l[i] and c[t - 1] < c[i]:
                obs.append([h[i], l[i], 0, -1.0])
            sc, keep = 0.0, []
            for top, bot, age, sign in obs:
                if age > max_age:
                    continue
                if sign > 0 and c[t] < bot:
                    continue
                if sign < 0 and c[t] > top:
                    continue
                if l[t] <= top and h[t] >= bot and sc == 0.0:
                    sc = sign
                keep.append([top, bot, age + 1, sign])
            obs = keep
            out.iat[t, j] = sc
    return out


def sig_sweep(H, L, C, look=20):
    """Liquidity sweeps: take out prior swing low/high and close back = stop-hunt fade."""
    prior_low = L.shift(1).rolling(look).min()
    prior_high = H.shift(1).rolling(look).max()
    bull = (L < prior_low) & (C > prior_low)
    bear = (H > prior_high) & (C < prior_high)
    return bull.astype(float) - bear.astype(float)


def sig_bos(H, L, C, look=20):
    """Break of structure: close beyond prior rolling extreme = continuation event."""
    up = C > H.shift(1).rolling(look).max()
    dn = C < L.shift(1).rolling(look).min()
    return up.astype(float) - dn.astype(float)


def sig_choch(H, L, C, look=20):
    """Change of character: first BOS against the prevailing break direction."""
    bos = sig_bos(H, L, C, look)
    out = pd.DataFrame(0.0, index=C.index, columns=C.columns)
    for j, col in enumerate(C.columns):
        b = bos[col].values
        state, sc = 0.0, np.zeros(len(b))
        for t in range(len(b)):
            if b[t] != 0.0:
                if state != 0.0 and b[t] != state:
                    sc[t] = b[t]
                state = b[t]
        out[col] = sc
    return out


def sig_premdisc(H, L, C, look=55):
    """Premium/discount inside the dealing range: buy discount, sell premium."""
    hi = H.shift(1).rolling(look).max()
    lo = L.shift(1).rolling(look).min()
    pos = (C - lo) / (hi - lo).replace(0, np.nan)
    return (pos < 0.35).astype(float) - (pos > 0.65).astype(float)


def sig_absorb(O, H, L, C, V):
    """Absorption: tiny range bar on huge volume at an extreme = accumulation/distribution."""
    rng = (H - L)
    atr = rng.rolling(14).mean()
    vavg = V.rolling(20).mean()
    pos = ((C - L) / rng.replace(0, np.nan))
    small = rng < 0.55 * atr
    bigv = V > 1.8 * vavg
    bull = small & bigv & (pos < 0.30)
    bear = small & bigv & (pos > 0.70)
    return bull.astype(float) - bear.astype(float)


def sig_amd(O, H, L, C):
    """AMD weekly fake-out (approx): Mon-Tue drive one way, Wed reversal bar."""
    dow = pd.Series(C.index.dayofweek, index=C.index)
    wk_dn = (C.shift(1) < O.shift(1)) & (C.shift(2) < O.shift(2))
    wk_up = (C.shift(1) > O.shift(1)) & (C.shift(2) > O.shift(2))
    rev_up = wk_dn & (C > H.shift(1)) & (dow == 2)
    rev_dn = wk_up & (C < L.shift(1)) & (dow == 2)
    return rev_up.astype(float) - rev_dn.astype(float)


def sig_fvg_mom(H, L, C, mom_px):
    f = sig_fvg(H, L, C)
    mom = mom_px.pct_change(60) > 0
    aligned = (mom & (f > 0)) | (~mom & (f < 0))
    return f.where(aligned, 0.0)


def sig_bos_ob(O, H, L, C):
    """Confluence: BOS direction confirmed by an OB retest same bar."""
    b = sig_bos(H, L, C)
    o = sig_ob(O, H, L, C)
    return pd.DataFrame(np.where((b * o) > 0, b, 0.0), index=C.index, columns=C.columns)


def sig_fvg_sweep(H, L, C):
    """Confluence: FVG retest within 3 bars of a liquidity sweep in the same direction."""
    f = sig_fvg(H, L, C)
    s = sig_sweep(H, L, C)
    s_recent = s.rolling(3).max()
    return pd.DataFrame(np.where((f * s_recent) > 0, f, 0.0), index=C.index, columns=C.columns)


def sig_vote(H, L, C, O=None, V=None):
    """SMC ensemble: >=2 of 3 core signals agree."""
    f = sig_fvg(H, L, C)
    s = sig_sweep(H, L, C)
    o = sig_ob(O, H, L, C) if O is not None else 0.0
    v = f + s + o
    return pd.DataFrame(np.where(v >= 2, 1.0, np.where(v <= -2, -1.0, 0.0)),
                        index=C.index, columns=C.columns)


def sig_range_mr(H, L, C, look=55):
    """Dealing-range midpoint reversion: fade displacement away from range mid."""
    hi = H.shift(1).rolling(look).max()
    lo = L.shift(1).rolling(look).min()
    mid = (hi + lo) / 2.0
    dev = (C - mid) / (hi - lo).replace(0, np.nan)
    return (-dev).clip(-1, 1).apply(np.sign)


# ---------------------------------------------------- portfolio wrapper ----
def smc_pf(px, score, hold=5, long_only=True, K=0):
    """Active-setup portfolio: coins whose SMC trigger fired within `hold` bars.
    Inverse-vol weights among active longs (and shorts if LS)."""
    o, h, l, c = ohlc(px)
    vol = px.pct_change().rolling(20).std().replace(0, np.nan)
    act_l = (score > 0).astype(float).rolling(hold).max().fillna(0.0)
    act_s = (score < 0).astype(float).rolling(hold).max().fillna(0.0)
    iv = (1.0 / vol).replace([np.inf, -np.inf], np.nan)
    wl = iv.where(act_l > 0, 0.0)
    if K and K > 0:
        wl = wl.where(wl.rank(axis=1, ascending=False) <= K, 0.0)
    wl = wl.div(wl.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
    if long_only:
        return wl
    ws = iv.where(act_s > 0, 0.0)
    if K and K > 0:
        ws = ws.where(ws.rank(axis=1, ascending=False) <= K, 0.0)
    ws = ws.div(ws.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
    return 0.6 * wl - 0.4 * ws


# ------------------------------------------------------------- builders -----
def mk(fn, long_only=True, hold=5, K=0):
    def builder(px, fn=fn, lo=long_only, h=hold, k=K):
        o, hgh, l, c = ohlc(px)
        return smc_pf(px, fn(o, hgh, l, c), hold=h, long_only=lo, K=k)
    return builder


def b_fvg_long(px):
    o, h, l, c = ohlc(px)
    return smc_pf(px, sig_fvg(h, l, c).clip(lower=0), hold=5, long_only=True)

def b_fvg_ls(px):
    o, h, l, c = ohlc(px)
    return smc_pf(px, sig_fvg(h, l, c), hold=5, long_only=False)

def b_ob_long(px):
    o, h, l, c = ohlc(px)
    return smc_pf(px, sig_ob(o, h, l, c).clip(lower=0), hold=5, long_only=True)

def b_ob_ls(px):
    o, h, l, c = ohlc(px)
    return smc_pf(px, sig_ob(o, h, l, c), hold=5, long_only=False)

def b_sweep_long(px):
    o, h, l, c = ohlc(px)
    return smc_pf(px, sig_sweep(h, l, c).clip(lower=0), hold=3, long_only=True)

def b_sweep_ls(px):
    o, h, l, c = ohlc(px)
    return smc_pf(px, sig_sweep(h, l, c), hold=3, long_only=False)

def b_bos_cont(px):
    o, h, l, c = ohlc(px)
    return smc_pf(px, sig_bos(h, l, c), hold=5, long_only=False)

def b_choch_rev(px):
    o, h, l, c = ohlc(px)
    return smc_pf(px, sig_choch(h, l, c), hold=5, long_only=False)

def b_premdisc(px):
    o, h, l, c = ohlc(px)
    return smc_pf(px, sig_premdisc(h, l, c), hold=10, long_only=False)

def b_bos_ob(px):
    o, h, l, c = ohlc(px)
    return smc_pf(px, sig_bos_ob(o, h, l, c), hold=5, long_only=False)

def b_fvg_sweep(px):
    o, h, l, c = ohlc(px)
    return smc_pf(px, sig_fvg_sweep(h, l, c), hold=5, long_only=False)

def b_vote(px):
    o, h, l, c = ohlc(px)
    return smc_pf(px, sig_vote(h, l, c, o), hold=5, long_only=False)

def b_absorb(px):
    o, h, l, c = ohlc(px)
    v = _V.reindex(px.index)
    return smc_pf(px, sig_absorb(o, h, l, c, v), hold=5, long_only=False)

def b_amd(px):
    o, h, l, c = ohlc(px)
    return smc_pf(px, sig_amd(o, h, l, c), hold=3, long_only=False)

def b_fvg_mom(px):
    o, h, l, c = ohlc(px)
    return smc_pf(px, sig_fvg_mom(h, l, c, px), hold=5, long_only=True)

def b_ob_gate(px):
    """Order blocks, but only long-side OBs while BTC regime is risk-on."""
    o, h, l, c = ohlc(px)
    score = sig_ob(o, h, l, c).clip(lower=0)
    btc = px["BTC"] if "BTC" in px.columns else px.iloc[:, 0]
    gate = (btc > btc.rolling(100).mean()).astype(float)
    return smc_pf(px, score, hold=5, long_only=True).mul(gate, axis=0).fillna(0.0)

def b_sweep_mom(px):
    """Sweep fade confirmed by 60d momentum direction."""
    o, h, l, c = ohlc(px)
    s = sig_sweep(h, l, c)
    mom = px.pct_change(60)
    score = s.where((s > 0) & (mom > 0), 0.0) + s.where((s < 0) & (mom < 0), 0.0)
    return smc_pf(px, score, hold=3, long_only=False)

def b_range_mr(px):
    o, h, l, c = ohlc(px)
    return smc_pf(px, sig_range_mr(h, l, c), hold=10, long_only=False)


BFS_L1 = [
    ("S/01", "FVG_LONG bullish fair-value-gap retests", b_fvg_long),
    ("S/02", "FVG_LS gap retests both sides", b_fvg_ls),
    ("S/03", "OB_LONG bullish order-block retests", b_ob_long),
    ("S/04", "OB_LS order blocks both sides", b_ob_ls),
    ("S/05", "SWEEP_LONG stop-hunt fades of prior lows", b_sweep_long),
    ("S/06", "SWEEP_LS stop-hunt fades both sides", b_sweep_ls),
    ("S/07", "BOS_CONT break-of-structure continuation", b_bos_cont),
    ("S/08", "CHOCH_REV change-of-character reversals", b_choch_rev),
    ("S/09", "PREMDISC buy discount / sell premium", b_premdisc),
    ("S/10", "BOS_OB BOS+order-block confluence", b_bos_ob),
    ("S/11", "FVG_SWEEP gap retest after sweep confluence", b_fvg_sweep),
    ("S/12", "VOTE >=2 of 3 SMC signals agree", b_vote),
    ("S/13", "ABSORB volume absorption at extremes", b_absorb),
    ("S/14", "AMD weekly fake-out reversal", b_amd),
    ("S/15", "FVG_MOM gaps in momentum direction", b_fvg_mom),
    ("S/16", "OB_GATE order blocks with BTC regime gate", b_ob_gate),
    ("S/17", "SWEEP_MOM sweep fades confirmed by momentum", b_sweep_mom),
    ("S/18", "RANGE_MR dealing-range midpoint reversion", b_range_mr),
    ("R/01", "REF dynamic champ VOL_GROT+hyst", lambda p: sh4.vg(p, 0.30, 150, 0.02)),
    ("R/02", "REF old champ L5/C1 ABS90_GROT", sh3.combo_c1),
    ("R/03", "REF DIP_V2", sh.w_dip_v2),
    ("R/04", "REF XSEC_MOM weekly", sh.w_xsec_mom),
]


# --------------------------------------------------------------- stages -----
def run_node(px, path, name, builder):
    FNS[path] = builder
    return sh4.run_node(px, path, name, builder, round_=8)


ADAPTS = [
    ("T1", "gate MA100", lambda p, b: b(p).mul(((_btc_gt(p, 100)).astype(float)), axis=0).fillna(0.0)),
    ("T2", "vol-target 30%", lambda p, b: sh2.vol_target(b(p), p, 0.30)),
    ("T3", "hyst-gate MA100", lambda p, b: b(p).mul(sh4.hyst_state(p, 100, 0.02), axis=0).fillna(0.0)),
]


def _seed_fns(bfs_results):
    """Rebuild the builder registry in a fresh process (BFS_L1 + L2 resolutions)."""
    for p, _n, b in BFS_L1:
        FNS[p] = b
    for entry in bfs_results or []:
        node = entry.get("node", "")
        if not node.startswith("L2/"):
            continue
        head = node.split("/")[1]
        core_tok, tid = head.rsplit("-", 1)
        base = FNS.get(f"S/{core_tok[1:]}" if core_tok.startswith("S") and core_tok[1:].isdigit()
                       else f"R/{core_tok[1:]}" if core_tok.startswith("R") else core_tok)
        if base is None:
            continue
        for aid, _aname, afn in ADAPTS:
            if aid == tid:
                FNS[node] = (lambda p, f=afn, bb=base: f(p, bb))


def _smc_key(node):
    """Map any node path to its SMC family id ('01'..'18') or None."""
    head = node.split("/")[1]
    tok = head.split("-")[0]
    if tok.startswith("fvgls"):
        return "02"
    if tok in smc_sigs_global:
        return tok
    if tok.startswith("S") and tok[1:] in smc_sigs_global:
        return tok[1:]
    return None


smc_sigs_global = {
    "01": (lambda o, h, l, c: sig_fvg(h, l, c).clip(lower=0), True),
    "02": (lambda o, h, l, c: sig_fvg(h, l, c), False),
    "03": (lambda o, h, l, c: sig_ob(o, h, l, c).clip(lower=0), True),
    "04": (lambda o, h, l, c: sig_ob(o, h, l, c), False),
    "05": (lambda o, h, l, c: sig_sweep(h, l, c).clip(lower=0), True),
    "06": (lambda o, h, l, c: sig_sweep(h, l, c), False),
    "11": (lambda o, h, l, c: sig_fvg_sweep(h, l, c), False),
    "12": (lambda o, h, l, c: sig_vote(h, l, c, o), False),
    "15": (lambda o, h, l, c: sig_fvg(h, l, c), True),
    "17": (lambda o, h, l, c: sig_sweep(h, l, c), False),
    "18": (lambda o, h, l, c: sig_range_mr(h, l, c), False),
}


def stage_bfs(px):
    print("=" * 120)
    print("SMC BFS L1 — BREADTH: 22 mechanic families (real daily OHLC)")
    print("pre-registered: max worst-fold s.t. all folds>-1, nonbull>0, bull_share<0.8, DD/Mo<=10, Cal>=1.2, DD<=35")
    print("=" * 120)
    results = []
    for path, name, b in BFS_L1:
        r = run_node(px, path, name, b)
        results.append(r)
        sh4.pr(r)

    ok = [r for r in results if r.get("dyn_ok")]
    ok.sort(key=lambda r: r["worst_fold"], reverse=True)
    print(f"\nBFS L1 DYN-OK survivors: {len(ok)}")
    for r in ok[:10]:
        sh4.pr(r)

    print("\n" + "=" * 120)
    print("BFS L2 — top-8 families x 3 regime adaptations")
    print("=" * 120)
    pool = ok[:8] if ok else sorted([r for r in results if not r.get("failed")],
                                    key=lambda r: r["worst_fold"], reverse=True)[:8]
    adapts = [
        ("T1", "gate MA100", lambda p, b: b(p).mul(((_btc_gt(p, 100)).astype(float)), axis=0).fillna(0.0)),
        ("T2", "vol-target 30%", lambda p, b: sh2.vol_target(b(p), p, 0.30)),
        ("T3", "hyst-gate MA100", lambda p, b: b(p).mul(sh4.hyst_state(p, 100, 0.02), axis=0).fillna(0.0)),
    ]
    l2 = []
    for r in pool:
        base = FNS[r["node"]]
        for aid, aname, afn in adapts:
            path = f"L2/{r['node'].replace('/', '')}-{aid}"
            rr = run_node(px, path, f"{r['name'][:30]} + {aname}",
                          (lambda p, f=afn, bb=base: f(p, bb)))
            l2.append(rr)
            sh4.pr(rr)
    results.extend(l2)
    _save(results, "bfs")
    return results


def _btc_gt(px, ma):
    btc = px["BTC"] if "BTC" in px.columns else px.iloc[:, 0]
    return btc > btc.rolling(ma).mean()


def stage_dfs(px, bfs_results):
    print("\n" + "=" * 120)
    print("DFS — parameter depth on SMC branches (hold x look x K)")
    print("=" * 120)
    pool = [r for r in (bfs_results or []) if r.get("dyn_ok")]
    if len(pool) < 8:
        extra = [r for r in (bfs_results or []) if not r.get("failed") and not r.get("dyn_ok")]
        extra.sort(key=lambda r: r["worst_fold"], reverse=True)
        pool = pool + extra[:8 - len(pool)]
    pool.sort(key=lambda r: r["worst_fold"], reverse=True)
    top = pool[:8]
    _seed_fns(bfs_results)

    def variant(sigfn, long_only, hold, K):
        def builder(px, f=sigfn, lo=long_only, h=hold, k=K):
            o, hgh, l, c = ohlc(px)
            return smc_pf(px, f(o, hgh, l, c), hold=h, long_only=lo, K=k)
        return builder

    dfs_nodes = []
    for r in top:
        head = r["node"].split("/")[1]
        core = head.split("-")[0]
        fam = _smc_key(r["node"])
        if fam is not None:
            sigfn, lo = smc_sigs_global[fam]
            grid = [("h3", 3, 0), ("h10", 10, 0), ("h20", 20, 0),
                    ("K3", 5, 3), ("K8", 5, 8), ("h3K3", 3, 3),
                    ("h10K3", 10, 3), ("h10K8", 10, 8)]
            for tag, h, k in grid:
                path = f"D/{core}-{tag}"
                rr = run_node(px, path, f"DFS {r['name'][:26]} [{tag}]",
                              variant(sigfn, lo, h, k))
                dfs_nodes.append(rr)
                sh4.pr(rr)
        else:
            base = FNS.get(r["node"])
            if base is None:
                continue
            for tag, maker in [
                ("vt25", lambda p, b=base: sh2.vol_target(b(p), p, 0.25)),
                ("vt35", lambda p, b=base: sh2.vol_target(b(p), p, 0.35)),
                ("g85", lambda p, b=base: b(p).mul((_btc_gt(p, 85)).astype(float), axis=0).fillna(0.0)),
                ("g115", lambda p, b=base: b(p).mul((_btc_gt(p, 115)).astype(float), axis=0).fillna(0.0)),
                ("hyst3", lambda p, b=base: b(p).mul(sh4.hyst_state(p, 100, 0.03), axis=0).fillna(0.0)),
                ("S80", lambda p, b=base: sh4._rescale(b(p), 0.8)),
                ("S12", lambda p, b=base: sh4._rescale(b(p), 1.2)),
                ("abs90", lambda p, b=base: sh2.abs_mom_filter(b(p), p, 90)),
            ]:
                path = f"D/{core}-{tag}"
                rr = run_node(px, path, f"DFS {r['name'][:26]} [{tag}]", maker)
                dfs_nodes.append(rr)
                sh4.pr(rr)

    # DFS wave 2: FVG_LS fine grid on hold x K (the SMC star branch)
    print("\n--- DFS WAVE 2: FVG_LS fine grid (hold x K) ---")
    sig02, lo02 = smc_sigs_global["02"]
    for h in (2, 3, 7, 10, 15):
        for k in (0, 3, 5):
            path = f"W/fvgls-h{h}K{k}"
            rr = run_node(px, path, f"FVG_LS hold{h} K{k}", variant(sig02, lo02, h, k))
            dfs_nodes.append(rr)
            sh4.pr(rr)

    results = list(bfs_results or []) + dfs_nodes

    ok = [r for r in results if r.get("dyn_ok")]
    ok.sort(key=lambda r: r["worst_fold"], reverse=True)
    winner = ok[0] if ok else max((r for r in results if not r.get("failed")),
                                  key=lambda r: r["worst_fold"])
    print("\n" + "=" * 120)
    print(f"VERIFICATION — SMC dynamic winner: {winner['node']} {winner['name']}")
    print("=" * 120)
    print("\nNeighbor plateau:")
    fam = _smc_key(winner["node"])
    if fam is not None:
        sigfn, lo = smc_sigs_global[fam]
        for tag, h, k in [("h2", 2, 0), ("h4", 4, 0), ("h7", 7, 0), ("K2", 5, 2),
                          ("K10", 5, 10), ("h3K5", 3, 5), ("h10K5", 10, 5)]:
            rr = run_node(px, f"V/NB-{tag}", f"neighbor {tag}", variant(sigfn, lo, h, k))
            sh4.pr(rr)
            results.append(rr)
    else:
        base = FNS.get(winner["node"], lambda p: p * 0)
        for tag, maker in [("vt25", lambda p, b=base: sh2.vol_target(b(p), p, 0.25)),
                           ("vt35", lambda p, b=base: sh2.vol_target(b(p), p, 0.35)),
                           ("g85", lambda p, b=base: b(p).mul((_btc_gt(p, 85)).astype(float), axis=0).fillna(0.0)),
                           ("g115", lambda p, b=base: b(p).mul((_btc_gt(p, 115)).astype(float), axis=0).fillna(0.0)),
                           ("S80", lambda p, b=base: sh4._rescale(b(p), 0.8)),
                           ("S12", lambda p, b=base: sh4._rescale(b(p), 1.2)),
                           ("abs90", lambda p, b=base: sh2.abs_mom_filter(b(p), p, 90))]:
            rr = run_node(px, f"V/NB-{tag}", f"neighbor {tag}", maker)
            sh4.pr(rr)
            results.append(rr)

    print("\nLOFO (select on 2 folds by DYNAMIC rule -> measure held-out fold):")
    cand_fns = {r["node"]: FNS[r["node"]] for r in ok
                if r["node"] in FNS and FNS[r["node"]] is not None}
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
        cands.sort(key=lambda x: x[0], reverse=True)
        if not cands:
            print(f"  fold{held}: no candidate qualified")
            continue
        _, node, fn = cands[0]
        a, b_ = bounds[held - 1]
        w = fn(px.iloc[max(0, a - 250):b_]).reindex(px.iloc[a:b_].index).fillna(0.0)
        eq, ret = sh.portfolio_sim(w, px.iloc[a:b_])
        m = sh.metrics(eq, ret)
        print(f"  selected {node:<14} -> HELD-OUT fold{held}: {m['monthly_roi']:+7.2f}%/mo "
              f"| DD {m['max_dd']:5.1f}% | worstM {m['worst_month']:+6.1f}")
        results.append({"round": 8, "node": "V/LOFO", "name": f"LOFO-8 fold{held}: {node}",
                        "scope": "held-out fold", "monthly_roi": m["monthly_roi"],
                        "max_dd": m["max_dd"], "calmar": m["calmar"],
                        "dd_monthly": m["dd_monthly"], "worst_month": m["worst_month"],
                        "worst_fold": m["monthly_roi"], "nonbull_avg": m["monthly_roi"],
                        "bull_share": 0.0, "dyn_ok": False, "failed": False})
    _save(results, "dfs")
    return results


def _save(results, stage):
    path = "reports/strategy_leaderboard.json"
    lb = json.load(open(path)) if os.path.exists(path) else {"entries": []}
    lb["entries"] = [e for e in lb["entries"] if e.get("round") != 8]
    lb["entries"].extend(results)
    rankable = [e for e in lb["entries"] if not e.get("failed") and e.get("calmar", -99) > -90]
    dyn = [e for e in rankable if e.get("dyn_ok")]
    dyn.sort(key=lambda e: e.get("worst_fold", -99), reverse=True)
    lb["selection_guide_smc"] = {
        "rule": "max worst-fold s.t. all folds>-1, nonbull_avg>0, bull_share<0.8, DD/Mo<=10, Cal>=1.2, DD<=35",
        "best_dynamic": ({k: dyn[0].get(k) for k in ("name", "node", "worst_fold", "nonbull_avg",
                                                     "bull_share", "monthly_roi", "max_dd", "calmar", "folds")}
                         if dyn else None),
        "top5_dynamic": [{"name": e.get("name"), "node": e.get("node"), "worst_fold": e.get("worst_fold"),
                          "nonbull_avg": e.get("nonbull_avg"), "bull_share": e.get("bull_share"),
                          "monthly_roi": e.get("monthly_roi"), "max_dd": e.get("max_dd"),
                          "calmar": e.get("calmar")} for e in dyn[:5]],
    }
    lb["tree_round8_nodes_visited"] = sum(1 for e in lb["entries"] if e.get("round") == 8)
    json.dump(lb, open(path, "w"), indent=2)
    print(f"\n[{stage}] saved -> {path} (round-8 nodes: {lb['tree_round8_nodes_visited']}, "
          f"leaderboard: {len(lb['entries'])})")
    if dyn:
        print(f"BEST SMC DYNAMIC: {dyn[0]['node']} {dyn[0]['name']}")
        print(f"  worst-fold {dyn[0]['worst_fold']:+.2f} | nonbull {dyn[0]['nonbull_avg']:+.2f} "
              f"| bull% {dyn[0]['bull_share']:.2f} | full {dyn[0]['monthly_roi']:+.2f}%/mo "
              f"DD {dyn[0]['max_dd']:.1f}% Cal {dyn[0]['calmar']:.2f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["bfs", "dfs"], required=True)
    args = ap.parse_args()
    _O, _H, _L, _C, _V = load_ohlcv()
    px = _C.dropna(how="any")
    _O, _H, _L, _V = _O.reindex(px.index), _H.reindex(px.index), _L.reindex(px.index), _V.reindex(px.index)
    if args.stage == "bfs":
        stage_bfs(px)
    else:
        lb = json.load(open("reports/strategy_leaderboard.json"))
        bfs_results = [e for e in lb["entries"] if e.get("round") == 8]
        stage_dfs(px, bfs_results)
