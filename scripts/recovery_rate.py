"""EXP-036 (2026-10-30): recovery-rate analysis for the deployment menu.

Question: when each policy drops, how reliably and how fast does it climb back?
For every policy: drawdown episodes (peak -> trough -> recovery), recovery rate
(fraction of episodes and of lost depth that return to new highs), months-to-recover
stats, time-underwater share, recovery factor, deepest-3 episode detail.

Two curves per policy:
  A. deployable curve: mappings learned on full period (same curve as the EXP-035
     risk frontier the user saw);
  B. LOFO-spliced OOS curve: each block's mapping learned WITHOUT that block
     (robustness bound; block-1 mapping trains on later blocks, so this is a
     cross-validated bound, not a live walk-forward).

BTC buy&hold is included as the reference recovery profile. Saves
exp036_recovery to reports/strategy_leaderboard.json (SKIP_LEDGER=1 to skip
the ledger).
"""
import os
import sys
import json

sys.path.insert(0, os.path.abspath("scripts"))

import numpy as np
import pandas as pd

import strategy_hunt as sh
import regime_hunt as rh
import regime_audit as ra
import regime_expansion as rx
import nuclear_regime as nr

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOARD = os.path.join(BASE, "reports", "strategy_leaderboard.json")
LEDGER = os.path.join(BASE, "reports", "roi_progress_ledger.json")
MONTHS = 29.9
DPM = 30.44  # days per month (equity is daily)


def _m(days):
    """days -> months, 1 decimal."""
    return round(days / DPM, 1)


# ----------------------------------------------------------------- episodes
def dd_episodes(eq: pd.Series):
    """Monthly drawdown episodes of an equity curve."""
    runmax = eq.cummax()
    dd = eq / runmax - 1.0
    eps = []
    i, n = 0, len(eq)
    while i < n:
        if dd.iloc[i] < 0:
            start = i
            # peak is the last month at the running max before the dip
            peak = i - 1 if i > 0 else 0
            trough = i
            j = i
            while j < n and dd.iloc[j] < 0:
                if dd.iloc[j] < dd.iloc[trough]:
                    trough = j
                j += 1
            recovered = j < n
            eps.append({
                "peak": str(eq.index[peak])[:10],
                "start": str(eq.index[start])[:10],
                "trough": str(eq.index[trough])[:10],
                "recovery": str(eq.index[j])[:10] if recovered else None,
                "depth_pct": round(float(dd.iloc[trough] * 100), 1),
                "months_to_trough": _m(trough - peak),
                "months_trough_to_recovery": _m(j - trough) if recovered else None,
                "months_underwater": _m((j if recovered else n) - start),
                "recovered": bool(recovered),
            })
            i = j + 1
        else:
            i += 1
    return eps, dd


def recovery_profile(eq: pd.Series):
    eps, dd = dd_episodes(eq)
    n = len(eq)
    rec = [e for e in eps if e["recovered"]]
    depths_all = sum(-e["depth_pct"] for e in eps) or 1.0
    depths_rec = sum(-e["depth_pct"] for e in rec)
    months_uw = sum(e["months_underwater"] for e in eps)
    recov_months = [e["months_trough_to_recovery"] for e in rec]
    buckets = {"<5%": (0, 5), "5-10%": (5, 10), "10-20%": (10, 20), ">=20%": (20, 1e9)}
    by_bucket = {}
    for bname, (lo, hi) in buckets.items():
        sel = [e for e in eps if lo <= -e["depth_pct"] < hi]
        sel_rec = [e for e in sel if e["recovered"]]
        by_bucket[bname] = {
            "n": len(sel),
            "recovered": len(sel_rec),
            "median_months_to_recover": (round(float(np.median([e["months_trough_to_recovery"] for e in sel_rec])), 1)
                                         if sel_rec else None),
        }
    final_mult = float(eq.iloc[-1] / eq.iloc[0])
    maxdd = float(-dd.min())
    top = sorted(eps, key=lambda e: e["depth_pct"])[:3]
    return {
        "final_mult": round(final_mult, 2),
        "max_dd_pct": round(maxdd * 100, 1),
        "n_episodes": len(eps),
        "n_recovered": len(rec),
        "recovery_rate_pct": round(100.0 * len(rec) / len(eps), 1) if eps else None,
        "depth_weighted_recovery_pct": round(100.0 * depths_rec / depths_all, 1) if eps else None,
        "median_months_trough_to_recovery": (round(float(np.median(recov_months)), 1) if recov_months else None),
        "max_months_trough_to_recovery": (round(float(max(recov_months)), 1) if recov_months else None),
        "time_underwater_pct": round(100.0 * months_uw / max((n - 1) / DPM, 1e-9), 1) if n > 1 else None,
        "longest_underwater_months": max((e["months_underwater"] for e in eps), default=0),
        "recovery_factor": round((final_mult - 1.0) / maxdd, 2) if maxdd > 0 else None,
        "by_depth_bucket": by_bucket,
        "deepest_episodes": top,
    }


# ----------------------------------------------------------------- builders
def make_comp(p3c, c30, h4c, lp, la, lb, wp, wc, wh):
    def comp(ws, idx, cols):
        out = 0.0
        if wp:
            out = out + wp * rx.apply_parts(rx.Cfg("p", "single", cells=p3c, sm=10), ws, lp, idx, cols)
        if wc:
            out = out + wc * rx.apply_parts(rx.Cfg("a", "single", cells=c30, sm=0), ws, la, idx, cols)
        if wh:
            out = out + wh * rx.apply_parts(rx.Cfg("b", "single", cells=h4c, sm=10), ws, lb, idx, cols)
        return out
    return comp


def main():
    px = ra.load_all()
    rh.MENU = rh.menu_builders()
    n = len(px)
    dbounds = [(0, int(n * 0.38)), (int(n * 0.38), int(n * 0.70)), (int(n * 0.70), n)]
    ws_full, streams = rx.build_full(px)
    ws_win = {h: rx.build_win(px, a, b_) for h, (a, b_) in enumerate(dbounds, start=1)}
    fams = nr.fam_registry(px)
    newd = rx.new_defs(px)
    p3c, c30, h4c = fams["H100b2"], fams["CORR30"], newd["H4_hyst_x_breadth"]

    # full-period-learned mappings (deployable curve)
    lp = rx.learn_parts(rx.Cfg("p", "single", cells=p3c, sm=10), streams, [(0, n)])
    la = rx.learn_parts(rx.Cfg("a", "single", cells=c30, sm=0), streams, [(0, n)])
    lb = rx.learn_parts(rx.Cfg("b", "single", cells=h4c, sm=10), streams, [(0, n)])

    policies = [
        ("Champion_P3", 1, 0, 0, 1.0),
        ("CORR30_s0", 0, 1, 0, 1.0),
        ("H4_s10", 0, 0, 1, 1.0),
        ("ENS_CxH4_100", 0, 0.5, 0.5, 1.0),
        ("ENS_CxH4_55", 0, 0.5, 0.5, 0.55),
        ("Blend3_100", 1 / 3, 1 / 3, 1 / 3, 1.0),
        ("Blend3_75", 1 / 3, 1 / 3, 1 / 3, 0.75),
        ("Blend3_70", 1 / 3, 1 / 3, 1 / 3, 0.70),
    ]

    print("=" * 118)
    print("EXP-036 RECOVERY-RATE ANALYSIS (deployable curve: full-period-learned mapping)")
    print("=" * 118)
    results = {}

    # ---- curve A: deployable
    eqs = {}
    for name, wp, wc, wh, scale in policies:
        comp = make_comp(p3c, c30, h4c, lp, la, lb, wp, wc, wh)
        w = comp(ws_full, px.index, px.columns) * scale
        eq, _r = sh.portfolio_sim(w, px, fee=sh.FEE)
        eqs[name] = eq
    # BTC buy&hold reference
    wb = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    wb["BTC"] = 1.0
    eq_btc, _ = sh.portfolio_sim(wb, px, fee=sh.FEE)
    eqs["BTC_hold"] = eq_btc

    hdr = (f"  {'policy':<16} {'x':>5} {'DD%':>5} {'ep':>3} {'rec%':>5} {'dWrec%':>6} "
           f"{'medM':>4} {'maxM':>4} {'UW%':>5} {'maxUW':>5} {'RF':>5} {'deepest episode':<28}")
    print(hdr)
    for name, eq in eqs.items():
        p = recovery_profile(eq)
        results[name] = {"curve": "deployable_full_learn", **p}
        d0 = p["deepest_episodes"][0] if p["deepest_episodes"] else None
        dtxt = (f"{d0['depth_pct']:+.1f}% {d0['trough']}"
                f"->{d0['recovery'] or 'NEVER'} ({d0['months_trough_to_recovery'] or '-'}m)") if d0 else "-"
        print(f"  {name:<16} {'-':>5} {p['max_dd_pct']:>5.1f} {p['n_episodes']:>3} "
              f"{p['recovery_rate_pct']:>5.1f} {p['depth_weighted_recovery_pct']:>6.1f} "
              f"{str(p['median_months_trough_to_recovery']):>4} "
              f"{str(p['max_months_trough_to_recovery']):>4} "
              f"{p['time_underwater_pct']:>5.1f} {p['longest_underwater_months']:>5} "
              f"{str(p['recovery_factor']):>5} {dtxt:<28}")

    print("\n  depth buckets (n recovered/total, median months to recover):")
    for name in [p[0] for p in policies] + ["BTC_hold"]:
        bb = results[name]["by_depth_bucket"]
        s = "  ".join(f"{b}: {v['recovered']}/{v['n']} ({v['median_months_to_recover']}m)"
                      for b, v in bb.items() if v["n"])
        print(f"    {name:<16} {s}")

    # ---- curve B: LOFO-spliced OOS (each block learned WITHOUT that block)
    print("\n" + "=" * 118)
    print("LOFO-SPLICED OOS CURVE (block mapping learned without that block)")
    print("=" * 118)
    for name, wp, wc, wh, scale in (("Champion_P3", 1, 0, 0, 1.0),
                                    ("ENS_CxH4_55", 0, 0.5, 0.5, 0.55),
                                    ("Blend3_75", 1 / 3, 1 / 3, 1 / 3, 0.75)):
        chain = []
        for held in (1, 2, 3):
            others = [dbounds[k - 1] for k in (1, 2, 3) if k != held]
            lph = rx.learn_parts(rx.Cfg("p", "single", cells=p3c, sm=10), streams, others)
            lah = rx.learn_parts(rx.Cfg("a", "single", cells=c30, sm=0), streams, others)
            lbh = rx.learn_parts(rx.Cfg("b", "single", cells=h4c, sm=10), streams, others)
            comp = make_comp(p3c, c30, h4c, lph, lah, lbh, wp, wc, wh)
            a, b_ = dbounds[held - 1]
            wi = max(0, a - 250)
            ww = comp(ws_win[held], px.iloc[wi:b_].index, px.columns) * scale
            e2, _r = sh.portfolio_sim(ww.reindex(px.iloc[a:b_].index).fillna(0.0),
                                      px.iloc[a:b_], fee=sh.FEE)
            chain.append(e2 / e2.iloc[0])          # normalize block equity to 1.0
        mult = 1.0
        parts = []
        for e2 in chain:
            parts.append(e2 * mult)
            mult *= float(e2.iloc[-1])
        eq_c = pd.concat(parts)
        p = recovery_profile(eq_c)
        results[name]["lofo_spliced"] = p
        print(f"  {name:<16} DD {p['max_dd_pct']:>5.1f} rec {p['recovery_rate_pct']:>5.1f}% "
              f"dWrec {p['depth_weighted_recovery_pct']:>5.1f}% medM {p['median_months_trough_to_recovery']} "
              f"maxM {p['max_months_trough_to_recovery']} UW {p['time_underwater_pct']:>5.1f}% "
              f"RF {p['recovery_factor']}")

    # ---- save
    board = json.load(open(BOARD))
    board["exp036_recovery"] = {
        "date": "2026-10-30",
        "question": "recovery rate of deployment menu (EXP-035 frontier)",
        "policies": results,
    }
    json.dump(board, open(BOARD, "w"), indent=2)
    print("\nsaved exp036_recovery")

    if os.environ.get("SKIP_LEDGER") != "1":
        led = json.load(open(LEDGER))
        led["experiments"].append({
            "id": "EXP-036-RECOVERY-RATE",
            "date": "2026-10-30",
            "focus": "recovery-rate analysis of deployment menu: drawdown episodes, recovery %, months-to-recover, time underwater, recovery factor on deployable + LOFO-spliced curves",
            "outcome": "EXP-036-RECOVERY",
        })
        json.dump(led, open(LEDGER, "w"), indent=2)
        print("ledger:", len(led["experiments"]))


if __name__ == "__main__":
    main()
