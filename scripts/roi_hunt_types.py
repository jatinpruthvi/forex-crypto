"""EXP-045 (2026-10-30): BEST-OF-BEST ROI HUNT across 20 NEW strategy types.

User: "think different types of strategy and try to hunt best of best roi strategy."

PRE-REGISTERED (67 nodes, 5y panel 2021-01..2026-07, FEE 10bp/side = commission+spread).
RANKED BY %/mo (ROI) subject to DD<=40 and minYr>=-1.5. New types never tested:
  FACTOR-ZOO cross-sectional (long top-K / short bottom-K, rebal 5d, K{3,5}):
    skewness fade/chase, beta-to-BTC low/high, Calmar ranking, win-rate, volume-share
    rotation, residual momentum (beta-adj), lottery max-ret fade, Amihud illiquidity,
    multi-horizon consensus momentum, 12-1 skip momentum, momentum-per-vol    -> 44
  TIMING (BTC/EQ): turn-of-month, post-crash rebound, breakout-retest, inside-bar,
    monthly-VWAP deviation, BTC/ETH relative-strength rotation, calm-regime long,
    range-expansion continuation, daily squeeze breakout                          -> 17
  PAIRS / STAT-ARB (NEW type): ETH/BTC, LTC/BTC, XRP/BTC log-ratio z reversion    ->  6
NULLS: config placebo (30x30d-block weight shuffles) on top-3 + search-level 5 draws.
Then: levered frontier of the ROI champion + blend of top-3 into book R2 base.
"""
import os
import sys
import json

sys.path.insert(0, os.path.abspath("scripts"))

import numpy as np
import pandas as pd

import strategy_hunt as sh
import regime_hunt as rh
import regime_expansion as rx
import five_year_test as ft
from nuclear_edges import metrics_from_pnl, pnl_from_weights, cs_weights

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOARD = os.path.join(BASE_DIR, "reports", "strategy_leaderboard.json")
LEDGER = os.path.join(BASE_DIR, "reports", "roi_progress_ledger.json")
FEE = 0.0010


def main():
    px = ft.load_all_5y()
    rh.MENU = rh.menu_builders()
    ws_base, _ = rx.build_full(px)
    idx, cols = px.index, px.columns
    ret = px.pct_change()
    btc = px["BTC"]

    nodes = {}

    def add(name, w):
        nodes[name] = (w.fillna(0.0), px)

    def two(name, score):
        for K in (3, 5):
            add(f"{name}_K{K}", cs_weights(score, K, px))

    # ---------------- FACTOR ZOO
    skew = ret.rolling(30).skew()
    two("skew_fade", -skew)
    two("skew_chase", skew)

    cov = ret.rolling(60).cov(ret["BTC"])
    var = ret["BTC"].rolling(60).var()
    beta = cov.div(var, axis=0)
    two("beta_low", -beta)
    two("beta_high", beta)

    roll_max = (1 + ret).rolling(60).apply(np.prod, raw=True) - 1
    dd60 = ((1 + ret).rolling(60).apply(np.prod, raw=True) /
            (1 + ret).rolling(60).apply(np.prod, raw=True).expanding().max() - 1)
    calmar = roll_max / dd60.abs().replace(0, np.nan)
    two("calmar_high", calmar)
    two("calmar_low", -calmar)

    win20 = (ret > 0).rolling(20).mean()
    two("winrate_high", win20)
    two("winrate_low", -win20)

    # volume-share rotation: use volume panel set by load_all_5y on sh5
    import strategy_hunt5 as sh5
    volp = sh5._V
    share = volp / volp.rolling(30).sum()
    dshare = share - share.shift(30)
    two("volshare_up", dshare)
    two("volshare_dn", -dshare)

    resid = ret.sub(beta.mul(ret["BTC"], axis=0))
    resmom = (1 + resid).rolling(60).apply(np.prod, raw=True) - 1
    two("resmom_high", resmom)
    two("resmom_low", -resmom)

    maxret = ret.rolling(30).max()
    two("maxret_fade", -maxret)
    two("maxret_chase", maxret)

    illiq = (ret.abs() / volp.replace(0, np.nan)).rolling(30).mean()
    two("illiq_high", illiq)
    two("illiq_low", -illiq)

    s20 = np.sign(px / px.shift(20) - 1)
    s60 = np.sign(px / px.shift(60) - 1)
    s120 = np.sign(px / px.shift(120) - 1)
    consensus = s20 + s60 + s120
    two("consensus_mom", consensus)
    two("consensus_neg", -consensus)

    mom121 = px / px.shift(252) * px.shift(21) / px - 1
    two("mom121", mom121)
    two("mom121_neg", -mom121)

    momper = (px / px.shift(60) - 1) / ret.rolling(60).std().replace(0, np.nan)
    two("mompervol", momper)
    two("mompervol_neg", -momper)

    # ---------------- TIMING (BTC / EQ)
    eq_w = pd.DataFrame(0.0, index=idx, columns=cols)
    eq_w["BTC"] = 0.5
    eq_w["ETH"] = 0.5
    day = idx.day
    tom = ((day >= 1) & (day <= 3)).astype(float)
    for an, base in (("BTC", pd.DataFrame(0.0, index=idx, columns=cols)), ("EQ", eq_w.copy())):
        w = base.copy()
        if an == "BTC":
            w["BTC"] = tom
        else:
            w = eq_w.mul(tom, axis=0)
        add(f"tom_{an}", w)

    r30 = px / px.shift(30) - 1
    for an in ("BTC", "EQ"):
        trig = (r30 < -0.20).astype(float).rolling(60).max()
        w = (eq_w if an == "EQ" else pd.DataFrame(0.0, index=idx, columns=cols)).copy()
        if an == "BTC":
            w["BTC"] = trig["BTC"]
        else:
            w = eq_w.mul(trig["BTC"], axis=0)
        add(f"postcrash20_{an}", w)

    hh55 = px.rolling(55).max().shift(1)
    retest = ((px <= hh55 * 1.02) & (px >= hh55 * 0.97) &
              (px.rolling(20).max() >= hh55)).astype(float)
    for an in ("BTC", "EQ"):
        w = pd.DataFrame(0.0, index=idx, columns=cols)
        if an == "BTC":
            w["BTC"] = retest["BTC"]
        else:
            w["BTC"] = retest["BTC"] / 2
            w["ETH"] = retest["ETH"] / 2
        add(f"retest55_{an}", w)

    inside = ((px.shift(1).rolling(2).max() - px.shift(1).rolling(2).min()) <
              (px.shift(3).rolling(5).max() - px.shift(3).rolling(5).min()))
    brk = np.sign(px / px.shift(20) - 1)
    ib_sig = (inside & (ret.abs() > ret.rolling(20).std())).astype(float) * brk
    for an in ("BTC", "EQ"):
        w = pd.DataFrame(0.0, index=idx, columns=cols)
        if an == "BTC":
            w["BTC"] = ib_sig["BTC"]
        else:
            w["BTC"] = ib_sig["BTC"] / 2
            w["ETH"] = ib_sig["ETH"] / 2
        add(f"insidebar_{an}", w)

    vw_month = px.groupby([idx.year, idx.month]).transform(lambda s: s.expanding().mean())  # causal MTD
    dev = px / vw_month - 1
    vwap_sig = pd.DataFrame(np.where(dev < -0.02, 1.0, np.where(dev > 0.02, -1.0, 0.0)),
                            index=idx, columns=cols)
    for an in ("BTC", "EQ"):
        w = pd.DataFrame(0.0, index=idx, columns=cols)
        if an == "BTC":
            w["BTC"] = vwap_sig["BTC"]
        else:
            w["BTC"] = vwap_sig["BTC"] / 2
            w["ETH"] = vwap_sig["ETH"] / 2
        add(f"vwapdev_{an}", w)

    rs = (px / px.shift(60)).rank(axis=1)
    rot_arr = np.where(rs["BTC"].values >= rs["ETH"].values, 1.0, 0.0)
    rot = pd.DataFrame(np.repeat(rot_arr[:, None], len(cols), axis=1), index=idx, columns=cols)
    rot["ETH"] = 1 - rot["BTC"]
    add("btc_eth_rot", rot)

    calm = (ret.rolling(30).std() < ret.rolling(100).std()).astype(float)
    for an in ("BTC", "EQ"):
        w = pd.DataFrame(0.0, index=idx, columns=cols)
        if an == "BTC":
            w["BTC"] = calm["BTC"]
        else:
            w["BTC"] = calm["BTC"] / 2
            w["ETH"] = calm["ETH"] / 2
        add(f"calmreg_{an}", w)

    rng20 = (px.rolling(20).max() / px.rolling(20).min() - 1)
    expn = (rng20 > rng20.shift(1) * 1.3).astype(float)
    for an in ("BTC", "EQ"):
        w = pd.DataFrame(0.0, index=idx, columns=cols)
        sig = expn * np.sign(px / px.shift(60) - 1)
        if an == "BTC":
            w["BTC"] = sig["BTC"]
        else:
            w["BTC"] = sig["BTC"] / 2
            w["ETH"] = sig["ETH"] / 2
        add(f"rangeexp_{an}", w)

    sqz = (ret.rolling(10).std() / ret.rolling(50).std() < 0.7).astype(float)
    for an in ("BTC", "EQ"):
        w = pd.DataFrame(0.0, index=idx, columns=cols)
        sig = sqz * np.sign(px / px.shift(30) - 1)
        if an == "BTC":
            w["BTC"] = sig["BTC"]
        else:
            w["BTC"] = sig["BTC"] / 2
            w["ETH"] = sig["ETH"] / 2
        add(f"sqzbrk_{an}", w)

    # ---------------- PAIRS / STAT-ARB
    for a, b in (("ETH", "BTC"), ("LTC", "BTC"), ("XRP", "BTC")):
        lr = np.log(px[a] / px[b])
        z = (lr - lr.rolling(60).mean()) / lr.rolling(60).std().replace(0, np.nan)
        for thr in (1.5, 2.0):
            sig_arr = np.where(z.values > thr, -1.0, np.where(z.values < -thr, 1.0, 0.0))
            sig = pd.DataFrame(np.repeat(sig_arr[:, None], len(cols), axis=1),
                               index=idx, columns=cols)
            w = pd.DataFrame(0.0, index=idx, columns=cols)
            w[a] = sig[a]
            w[b] = -sig[a]
            add(f"ratior_{a}{b}_z{int(thr*10)}", w)

    # ================================================== EVAL
    print("=" * 118)
    print(f"EXP-045: {len(nodes)} nodes / 20 new types — ranked by ROI (DD<=40, minYr>=-1.5)")
    print("=" * 118)
    rows = {}
    for name, (w, p) in nodes.items():
        m = metrics_from_pnl(pnl_from_weights(w, p, FEE))
        if m is None:
            continue
        rows[name] = m
    ok = [(k, v) for k, v in rows.items()
          if v["dd"] <= 40 and v["min_year"] is not None and v["min_year"] >= -1.5]
    ok.sort(key=lambda kv: kv[1]["monthly"], reverse=True)
    print("\nTOP-15 by ROI %/mo:")
    for k, v in ok[:15]:
        ys = " ".join(f"{y[2:]}:{x:+5.1f}" for y, x in v["yearly"].items())
        print(f"  {k:<24} {v['monthly']:+6.2f}%/mo SR {v['sharpe']:+5.2f} DD {v['dd']:5.1f} "
              f"minYr {v['min_year']:+5.2f} | {ys}")
    if not ok:
        print("  (none passed gates)")
    best = ok[0] if ok else max(rows.items(), key=lambda kv: kv[1]["monthly"])

    # ---------------- placebos on top-3
    print("\nNULLS (30 block-shuffle draws each on top-3):")
    rng = np.random.default_rng(9001)
    for name, _ in ok[:3]:
        w, p = nodes[name]
        nb = int(np.ceil(len(w) / 30))
        draws = []
        for _ in range(30):
            perm = rng.permutation(nb)
            w2 = pd.concat([w.iloc[b * 30:(b + 1) * 30] for b in perm], axis=0)
            w2.index = w.index[:len(w2)]
            w2 = w2.reindex(w.index).fillna(0.0)
            draws.append(metrics_from_pnl(pnl_from_weights(w2, p, FEE))["monthly"])
        dr = np.array(draws)
        p90 = float(np.quantile(dr, 0.9))
        print(f"  {name:<24} real {rows[name]['monthly']:+6.2f}%/mo vs null p90 {p90:+6.2f} "
              f"-> {'PASS' if rows[name]['monthly'] >= p90 else 'FAIL'}")
    # search-level null
    sn = []
    for d_ in range(5):
        best_m = -99
        for name, (w, p) in nodes.items():
            nb = int(np.ceil(len(w) / 30))
            perm = rng.permutation(nb)
            w2 = pd.concat([w.iloc[b * 30:(b + 1) * 30] for b in perm], axis=0)
            w2.index = w.index[:len(w2)]
            w2 = w2.reindex(w.index).fillna(0.0)
            m = metrics_from_pnl(pnl_from_weights(w2, p, FEE))
            if m:
                best_m = max(best_m, m["monthly"])
        sn.append(round(best_m, 2))
        print(f"  search-null draw {d_}: best %/mo over {len(nodes)} = {best_m:+.2f}")
    g_search = best[1]["monthly"] >= max(sn)

    # ---------------- levered frontier of champion + blend into book R2
    print("\n" + "=" * 118)
    print(f"CHAMPION {best[0]} levered frontier + blend into book-R2 base:")
    w_c, p_c = nodes[best[0]]
    for lev in (1.0, 1.5, 2.0, 2.5):
        m = metrics_from_pnl(pnl_from_weights(w_c * lev, p_c, FEE))
        print(f"  champion x{lev:<4} {m['monthly']:+6.2f}%/mo SR {m['sharpe']:+5.2f} "
              f"DD {m['dd']:5.1f} minYr {m['min_year']:+5.2f}")
    gate = (px["BTC"] > px["BTC"].rolling(100).mean()).astype(float)
    from nuclear_edges import cs_weights as _csw
    w_mom = _csw((px / px.shift(14) - 1), 5, px, gate=gate)
    base_w = 0.75 * (0.5 * ws_base["ABS_GROT"] + 0.5 * ws_base["FVG_SHORT"]).reindex(idx).fillna(0.0) \
        + 0.25 * w_mom
    book = pnl_from_weights(base_w, px)
    mb = metrics_from_pnl(book)
    blend_rows = {}
    print(f"  (base book R2 core: SR {mb['sharpe']:+.2f} {mb['monthly']:+.2f}%/mo DD {mb['dd']})")
    for name, _ in ok[:3]:
        w_n, p_n = nodes[name]
        pn = pnl_from_weights(w_n, p_n, FEE)
        for share in (0.10, 0.25):
            m = metrics_from_pnl((1 - share) * book + share * pn)
            blend_rows[f"{name}_x{int(share*100)}"] = m
            print(f"  +{name:<22} {int(share*100):>2}% -> SR {m['sharpe']:+5.2f} "
                  f"{m['monthly']:+5.2f}%/mo DD {m['dd']:5.1f} minYr {m['min_year']:+5.2f}")

    verdict = {
        "champion": best[0], "champion_metrics": best[1],
        "search_null_best": [float(x) for x in sn], "search_pass": bool(g_search),
    }
    board = json.load(open(BOARD))
    board["exp045_roi_types"] = {
        "date": "2026-10-30",
        "question": "best-of-best ROI across 20 NEW strategy types (67 nodes, 5y, costs)",
        "all_nodes": rows,
        "top15": {k: rows[k] for k, v in ok[:15]},
        "blends": blend_rows,
        "verdict": verdict,
    }
    json.dump(board, open(BOARD, "w"), indent=2)
    print("\nsaved exp045_roi_types")


if __name__ == "__main__":
    main()
