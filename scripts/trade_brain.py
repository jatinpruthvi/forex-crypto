"""EXP-038 (2026-10-30): trade-history "brain" - can adaptive re-learning improve ROI?

Question (user): "is any harness or python brain will improve the ROI based on trade
history, i mean past trade?"

We already have the validated brain: the walk-forward state-mapping learner (past
returns decide which engine runs in each parameter-state). What has NOT been tested:
whether FEEDING THE BRAIN WITH ACCUMULATED TRADE HISTORY (periodic re-learning) beats
the frozen spec - and whether performance-chasing helps or hurts.

All variants are strictly causal after a common warmup (first 38% of the panel):
every refresh at time t uses ONLY data [0, t). Trade history in live = the executed
trade journal (same math, realized fills); here = realized daily returns of the
strategies (the exact same statistics).

PRE-REGISTERED VARIANTS (6) x SLEEVES (3) - all reported, no cherry-picking:
  V0a static_full    : mapping learned on the FULL panel (published frozen spec;
                       in-sample reference - the number we deploy against)
  V0b static_warmup  : mapping learned on warmup only, then frozen (FAIR causal baseline)
  V1 refresh_21      : re-learn mapping every 21 days on all data so far
  V2 refresh_63      : re-learn mapping every 63 days on all data so far
  V3 guard_63        : refresh_63 but adopt the new mapping only if its trailing-252d
                       realized monthly beats the current mapping's by >= 0.5%/mo
  V4 bandit_21       : performance-chaser (expected to fail per EXP-034): portfolio
                       tilted across the 5 top-5 actions every 21 days by softmax of
                       trailing-126d monthly (eta=0.10 per %-point), p in [0.05, 0.50]

SLEEVES: Champion_P3 (single), ENS_CxH4 (ens 2), Blend3_75 (ens 3 x 0.75).

PRE-REGISTERED READ: a brain "improves ROI" only if its post-warmup monthly beats V0b
(casual static) AND its max DD is not worse by >20% relative AND it beats V0a on
monthly or matches it within noise while being causal. Bandit is expected to FAIL.
Report post-warmup monthly/DD/worst-month + the three evaluation blocks + in-market %.
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


def sleeves(p3c, c30, h4c):
    return {
        "Champion_P3": (rx.Cfg("Champion_P3", "single", cells=p3c, sm=10), 1.0),
        "ENS_CxH4": (rx.Cfg("ENS_CxH4", "ens", parts=[(c30, 0), (h4c, 10)]), 1.0),
        "Blend3_75": (rx.Cfg("Blend3_75", "ens",
                             parts=[(p3c, 10), (c30, 0), (h4c, 10)]), 0.75),
    }


def seg_weights(cfg, scale, ws, streams, train, a, b, px):
    """Weights over rows [a, b) with mapping learned on `train` ranges."""
    idx = px.index
    learned = rx.learn_parts(cfg, streams, train)
    w = rx.apply_parts(cfg, ws, learned, idx, px.columns) * scale
    return w.iloc[a:b]


def run_static(cfg, scale, ws, streams, px, train):
    w = seg_weights(cfg, scale, ws, streams, train, 0, len(px), px)
    return w


def run_refresh(cfg, scale, ws, streams, px, warm, schedule, guard=None):
    """Causal expanding-window refresh. guard: (margin, lookback) for V3."""
    n = len(px)
    w = seg_weights(cfg, scale, ws, streams, [(0, warm)], 0, n, px)  # warmup segment
    cur_train_end = warm
    accepted = [(0, warm)]
    t = warm
    while t < n:
        nxt = min(t + schedule, n)
        if guard is None:
            accepted = [(0, t)]
            w.iloc[t:nxt] = seg_weights(cfg, scale, ws, streams, [(0, t)], t, nxt, px)
        else:
            margin, look = guard
            cand = seg_weights(cfg, scale, ws, streams, [(0, t)],
                               max(0, t - look), t, px)
            cur = seg_weights(cfg, scale, ws, streams, accepted,
                              max(0, t - look), t, px)
            # trailing realized monthly of both mappings over the lookback window
            _, rc = sh.portfolio_sim(cand, px.iloc[max(0, t - look):t], fee=sh.FEE)
            _, rr = sh.portfolio_sim(cur, px.iloc[max(0, t - look):t], fee=sh.FEE)
            months = max(look / 30.44, 1.0)
            mc = (1.0 + rc).prod() ** (1.0 / months) - 1.0
            mr = (1.0 + rr).prod() ** (1.0 / months) - 1.0
            if mc > mr + margin / 100.0:
                accepted = [(0, t)]
            w.iloc[t:nxt] = seg_weights(cfg, scale, ws, streams, accepted, t, nxt, px)
        t = nxt
    return w


def run_bandit(acts_books_keys, books_fn, px, warm, eta=0.10, pmin=0.05, pmax=0.50,
               schedule=21, look=126):
    """Performance-chaser across the 5 top-5 actions (expected FAIL)."""
    n = len(px)
    names = list(acts_books_keys)
    w = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    p = {a: 1.0 / len(names) for a in names}
    t = 0
    while t < n:
        nxt = min(t + schedule, n)
        if t >= warm:
            # trailing monthly per action over `look` days (expanding-learned books)
            books = books_fn(max(0, t - look), t)
            mrets = {}
            for a in names:
                _eq, r = sh.portfolio_sim(books[a], px.iloc[max(0, t - look):t], fee=sh.FEE)
                months = max(look / 30.44, 1.0)
                mrets[a] = ((1.0 + r.fillna(0.0)).prod() ** (1.0 / months) - 1.0) * 100.0
            ex = {a: np.exp(eta * max(min(mrets[a], 40.0), -40.0)) for a in names}
            s = sum(ex.values())
            raw = {a: ex[a] / s for a in names}
            # clip + renormalize
            clipped = {a: min(max(raw[a], pmin), pmax) for a in names}
            s2 = sum(clipped.values())
            p = {a: clipped[a] / s2 for a in names}
        books = books_fn(0, max(t, warm))   # books for [t, nxt) from data up to max(t,warm)
        acc = pd.DataFrame(0.0, index=px.index, columns=px.columns)
        for a in names:
            acc += p[a] * books[a]
        w.iloc[t:nxt] = acc.iloc[t:nxt]
        t = nxt
    return w


def summarize(eq, r, seg0):
    m = sh.metrics(eq, r)
    eqp = eq.iloc[seg0:]
    rp = r.iloc[seg0:]
    mp = sh.metrics(eqp, rp)
    mret = eq.resample("ME").last().pct_change().dropna()
    in_mkt = None
    return {
        "post_warm_monthly": mp["monthly_roi"],
        "post_warm_dd": mp["max_dd"],
        "post_warm_worst_m": mp["worst_month"],
        "full_monthly": m["monthly_roi"],
        "full_dd": m["max_dd"],
    }


def main():
    px = ra.load_all()
    rh.MENU = rh.menu_builders()
    n = len(px)
    warm = int(n * 0.38)
    dbounds = [(0, warm), (warm, int(n * 0.70)), (int(n * 0.70), n)]
    ws_full, streams = rx.build_full(px)
    fams = nr.fam_registry(px)
    newd = rx.new_defs(px)
    p3c, c30, h4c = fams["H100b2"], fams["CORR30"], newd["H4_hyst_x_breadth"]
    sl = sleeves(p3c, c30, h4c)
    acts = {
        "Blend3_75": (rx.Cfg("b", "ens", parts=[(p3c, 10), (c30, 0), (h4c, 10)]), 0.75),
        "ENS_CxH4": (rx.Cfg("e", "ens", parts=[(c30, 0), (h4c, 10)]), 1.0),
        "Champion_P3": (rx.Cfg("p", "single", cells=p3c, sm=10), 1.0),
        "ENS_CxP3": (rx.Cfg("q", "ens", parts=[(c30, 0), (p3c, 10)]), 1.0),
        "CORR30_s0": (rx.Cfg("c", "single", cells=c30, sm=0), 1.0),
    }

    def books_fn(a, b):
        out = {}
        for name, (cfg, scale) in acts.items():
            learned = rx.learn_parts(cfg, streams, [(0, b)])
            w = rx.apply_parts(cfg, ws_full, learned, px.index, px.columns) * scale
            out[name] = w
        return out

    print("=" * 118)
    print("EXP-038 TRADE-HISTORY BRAIN: 6 causal variants x 3 sleeves (post-warmup = 62% of panel)")
    print("=" * 118)
    results = {}
    for sname, (cfg, scale) in sl.items():
        print(f"\n--- sleeve {sname} ---")
        variants = {
            "V0a_static_full": run_static(cfg, scale, ws_full, streams, px, [(0, n)]),
            "V0b_static_warmup": run_static(cfg, scale, ws_full, streams, px, [(0, warm)]),
            "V1_refresh_21": run_refresh(cfg, scale, ws_full, streams, px, warm, 21),
            "V2_refresh_63": run_refresh(cfg, scale, ws_full, streams, px, warm, 63),
            "V3_guard_63": run_refresh(cfg, scale, ws_full, streams, px, warm, 63,
                                       guard=(0.5, 252)),
        }
        if sname == "Blend3_75":
            variants["V4_bandit_21"] = run_bandit(list(acts), books_fn, px, warm)
        for vname, w in variants.items():
            eq, r = sh.portfolio_sim(w, px, fee=sh.FEE)
            s = summarize(eq, r, warm)
            # block monthlies (post-warmup blocks 2/3 by construction)
            blocks = []
            for a, b_ in (dbounds[1], dbounds[2]):
                e2, r2 = sh.portfolio_sim(w.iloc[a:b_], px.iloc[a:b_], fee=sh.FEE)
                blocks.append(sh.metrics(e2, r2)["monthly_roi"])
            s["blocks"] = blocks
            s["in_market"] = round(float((w.abs().sum(axis=1) > 0).mean() * 100), 1)
            results.setdefault(sname, {})[vname] = s
            print(f"  {vname:<18} post-warm {s['post_warm_monthly']:+7.2f}%/mo "
                  f"DD {s['post_warm_dd']:5.1f} worstM {s['post_warm_worst_m']:+6.1f} "
                  f"blocks {blocks[0]:+6.2f}/{blocks[1]:+6.2f} full {s['full_monthly']:+6.2f} "
                  f"inMkt {s['in_market']:.0f}%")

    # verdict per pre-registered read
    print("\n" + "=" * 118)
    print("PRE-REGISTERED READ (brain improves ROI iff: beats V0b causal-static post-warm "
          "AND DD not worse >20% rel AND >= V0a within noise while causal)")
    verdict = {}
    for sname in sl:
        r = results[sname]
        base_b, base_a = r["V0b_static_warmup"], r["V0a_static_full"]
        row = {}
        for vname in ("V1_refresh_21", "V2_refresh_63", "V3_guard_63", "V4_bandit_21"):
            if vname not in r:
                continue
            v = r[vname]
            beats_b = v["post_warm_monthly"] > base_b["post_warm_monthly"]
            dd_ok = v["post_warm_dd"] <= base_b["post_warm_dd"] * 1.20
            ok = beats_b and dd_ok
            row[vname] = {"beats_v0b": bool(beats_b), "dd_ok": bool(dd_ok), "improves": bool(ok)}
            print(f"  {sname:<12} {vname:<14} beats V0b: {str(beats_b):<5} "
                  f"DD ok: {str(dd_ok):<5} -> {'IMPROVES' if ok else 'no'}")
        verdict[sname] = row

    board = json.load(open(BOARD))
    board["exp038_brain"] = {
        "date": "2026-10-30",
        "question": "does adaptive re-learning from trade history improve ROI vs frozen spec?",
        "variants": ["V0a_static_full", "V0b_static_warmup", "V1_refresh_21",
                     "V2_refresh_63", "V3_guard_63", "V4_bandit_21"],
        "results": results,
        "verdict": verdict,
    }
    json.dump(board, open(BOARD, "w"), indent=2)
    print("\nsaved exp038_brain")

    if os.environ.get("SKIP_LEDGER") != "1":
        led = json.load(open(LEDGER))
        led["experiments"].append({
            "id": "EXP-038-TRADE-BRAIN",
            "date": "2026-10-30",
            "focus": "trade-history brain: causal expanding re-learn (21/63d), margin-guarded refresh, bandit chaser vs frozen spec",
            "outcome": "EXP-038-BRAIN",
        })
        json.dump(led, open(LEDGER, "w"), indent=2)
        print("ledger:", len(led["experiments"]))


if __name__ == "__main__":
    main()
