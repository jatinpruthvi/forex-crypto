"""EXP-039 (2026-10-30): top-5 strategies on the LAST 5 YEARS (2021-01 -> 2026-07).

New data source (GitHub): olaxbt/ai-market-maker `data/ohlcv/{C}_USDT_1d.csv`
(Binance-style daily OHLCV, 2021-01-01 -> 2026-07-31). Cross-validated against the
original StephanAkkerman panel on the 2021-01..2023-04 overlap (9 shared coins):
median level diff ~0.05% (bar-boundary stamping), daily-return corr 0.9996-0.99997.

UNIVERSE: 15 coins with full-window history (partial listings APT/ARB/OP/SUI excluded):
  BTC ETH BNB XRP ADA DOGE LTC LINK ATOM SOL DOT UNI AVAX FIL NEAR
  (9 of the original 21; universe differs from the design panel - documented).

PROTOCOL (pre-registered):
  split = 2023-04-15 (the old panel's end = the design horizon)
  M1 frozen  : mapping learned on <=2023-04-15 ONLY, then frozen -> the OOS segment
               (2023-04-15 -> 2026-07-31, 3.3 yrs NEVER seen in any prior experiment)
               is a TRUE out-of-sample test of the deployable spec.
  M2 brain63 : expanding re-learn every 63 days (the EXP-038 recommended live loop)
  M3 full    : mapping learned on the whole 5.5y (in-sample ceiling reference)
  Report: overlap segment (2021-01..2023-04) + OOS segment + per-year monthlies
  (2021, 2022, 2023pre, 2023post, 2024, 2025, 2026YTD), DD/Calmar/worst month on OOS,
  deepest-episode recovery for the three paper sleeves.

STRATEGIES: the spec's top-5 (Blend3_75, ENS_CxH4, Champion_P3, ENS_CxP3, CORR30_s0)
plus the two sized sleeves (ENS_CxH4@55, Meta-ENS@55).
"""
import os
import sys
import json

sys.path.insert(0, os.path.abspath("scripts"))

import numpy as np
import pandas as pd

import strategy_hunt as sh
import strategy_hunt5 as sh5
import regime_hunt as rh
import regime_audit2 as ra2
import regime_expansion as rx
import nuclear_regime as nr
import recovery_rate as rr

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOARD = os.path.join(BASE, "reports", "strategy_leaderboard.json")
LEDGER = os.path.join(BASE, "reports", "roi_progress_ledger.json")
PANEL = os.path.join(BASE, "data", "timeframes", "1d_panel_5y")
COINS5 = ["BTC", "ETH", "BNB", "XRP", "ADA", "DOGE", "LTC", "LINK", "ATOM",
          "SOL", "DOT", "UNI", "AVAX", "FIL", "NEAR"]
SPLIT = pd.Timestamp("2023-04-15")


def load_all_5y():
    frames = {}
    for c in COINS5:
        df = pd.read_csv(os.path.join(PANEL, f"{c}USDT_1d.csv"))
        df["date"] = pd.to_datetime(df["date"])
        frames[c] = df.set_index("date")
    idx = None
    for df in frames.values():
        idx = df.index if idx is None else idx.intersection(df.index)
    def panel(col):
        return pd.DataFrame({c: frames[c].reindex(idx)[col] for c in COINS5}).sort_index()
    sh5._O, sh5._H, sh5._L, sh5._C, sh5._V = (panel("open"), panel("high"), panel("low"),
                                              panel("close"), panel("volume"))
    px = sh5._C.dropna(how="any")
    sh5._O, sh5._H, sh5._L, sh5._V = (sh5._O.reindex(px.index), sh5._H.reindex(px.index),
                                      sh5._L.reindex(px.index), sh5._V.reindex(px.index))
    return px


def strategies(p3c, c30, h4c):
    """(name, builder(ws, streams, train, px) -> weights, scale)."""
    def ens(cfg, scale=1.0):
        def b(ws, streams, train, px):
            lg = rx.learn_parts(cfg, streams, train)
            return rx.apply_parts(cfg, ws, lg, px.index, px.columns) * scale
        return b
    def meta_ens(scale=1.0):
        def b(ws, streams, train, px):
            lC = rx.learn_parts(rx.Cfg("c", "single", cells=c30, sm=0), streams, train)
            lH = rx.learn_parts(rx.Cfg("h", "single", cells=h4c, sm=10), streams, train)
            lP = rx.learn_parts(rx.Cfg("p", "single", cells=p3c, sm=10), streams, train)
            idx, cols = px.index, px.columns
            wC = rx.apply_parts(rx.Cfg("c", "single", cells=c30, sm=0), ws, lC, idx, cols)
            wH = rx.apply_parts(rx.Cfg("h", "single", cells=h4c, sm=10), ws, lH, idx, cols)
            wP = rx.apply_parts(rx.Cfg("p", "single", cells=p3c, sm=10), ws, lP, idx, cols)
            cl = ra2.persist(ra2.labels_from_cells(c30, idx), 5)
            half = pd.DataFrame(0.0, index=idx, columns=cols)
            half[cl == "A"] = wH[cl == "A"]
            half[cl == "B"] = wP[cl == "B"]
            return (0.5 * wC + 0.5 * half) * scale
        return b
    return {
        "Blend3_75": ens(rx.Cfg("b3", "ens", parts=[(p3c, 10), (c30, 0), (h4c, 10)]), 0.75),
        "ENS_CxH4": ens(rx.Cfg("ch", "ens", parts=[(c30, 0), (h4c, 10)])),
        "Champion_P3": ens(rx.Cfg("p3", "single", cells=p3c, sm=10)),
        "ENS_CxP3": ens(rx.Cfg("cp", "ens", parts=[(c30, 0), (p3c, 10)])),
        "CORR30_s0": ens(rx.Cfg("c30", "single", cells=c30, sm=0)),
        "ENS_CxH4_55": ens(rx.Cfg("ch55", "ens", parts=[(c30, 0), (h4c, 10)]), 0.55),
        "Meta_ENS_55": meta_ens(0.55),
    }


def weights_for(mode, builder, ws, streams, px, split_i):
    n = len(px)
    if mode == "M3_full":
        return builder(ws, streams, [(0, n)], px)
    if mode == "M1_frozen":
        return builder(ws, streams, [(0, split_i)], px)
    # M2 brain63: expanding refresh every 63 rows after split
    w = builder(ws, streams, [(0, split_i)], px)
    t = split_i
    while t < n:
        nxt = min(t + 63, n)
        w.iloc[t:nxt] = builder(ws, streams, [(0, t)], px).iloc[t:nxt]
        t = nxt
    return w


def seg_metrics(w, px, a, b):
    ww = w.iloc[a:b]
    eq, r = sh.portfolio_sim(ww, px.iloc[a:b], fee=sh.FEE)
    m = sh.metrics(eq, r)
    return m, eq


def yearly(eq):
    monthly = eq.resample("ME").last().pct_change().dropna()
    out = {}
    for y, grp in monthly.groupby(monthly.index.year):
        out[str(y)] = round(float(((1 + grp).prod() ** (1.0 / max(len(grp), 1)) - 1) * 100), 2)
    return out


def main():
    px = load_all_5y()
    rh.MENU = rh.menu_builders()
    n = len(px)
    split_i = int((px.index < SPLIT).sum())
    ws_full, streams = rx.build_full(px)
    fams = nr.fam_registry(px)
    newd = rx.new_defs(px)
    p3c, c30, h4c = fams["H100b2"], fams["CORR30"], newd["H4_hyst_x_breadth"]
    strats = strategies(p3c, c30, h4c)

    print("=" * 118)
    print(f"EXP-039 TOP-5 ON LAST 5 YEARS: {px.index[0].date()} -> {px.index[-1].date()}, "
          f"{len(COINS5)} coins, split {SPLIT.date()} ({split_i} train / {n - split_i} OOS rows)")
    print("=" * 118)

    results = {}
    for sname, builder in strats.items():
        results[sname] = {}
        for mode in ("M1_frozen", "M2_brain63", "M3_full"):
            w = weights_for(mode, builder, ws_full, streams, px, split_i)
            m_tr, _ = seg_metrics(w, px, 0, split_i)
            m_oo, eq_oo = seg_metrics(w, px, split_i, n)
            eq_full, _ = sh.portfolio_sim(w, px, fee=sh.FEE)
            yr = yearly(eq_full)
            ep = rr.dd_episodes(eq_oo)[0]
            deep = sorted(ep, key=lambda e: e["depth_pct"])[:1]
            results[sname][mode] = {
                "overlap_mo": m_tr["monthly_roi"],
                "oos_mo": m_oo["monthly_roi"],
                "oos_dd": m_oo["max_dd"],
                "oos_calmar": m_oo["calmar"],
                "oos_worst_m": m_oo["worst_month"],
                "yearly": yr,
                "oos_deepest": deep[0] if deep else None,
            }
        r = results[sname]
        print(f"\n{sname}:")
        for mode in ("M1_frozen", "M2_brain63", "M3_full"):
            v = r[mode]
            yrs = " ".join(f"{y[2:]}:{m:+.1f}" for y, m in v["yearly"].items())
            print(f"  {mode:<10} overlap {v['overlap_mo']:+6.2f} | OOS {v['oos_mo']:+6.2f}%/mo "
                  f"DD {v['oos_dd']:5.1f} Cal {v['oos_calmar']:5.2f} worstM {v['oos_worst_m']:+6.1f} "
                  f"| yearly {yrs}")
            if v["oos_deepest"]:
                d = v["oos_deepest"]
                print(f"             deepest OOS episode: {d['depth_pct']:+.1f}% "
                      f"{d['trough']} -> {d['recovery'] or 'NEVER'} "
                      f"({d['months_trough_to_recovery']}m)")

    board = json.load(open(BOARD))
    board["exp039_5y"] = {
        "date": "2026-10-30",
        "question": "top-5 on last 5 years (2021-01 -> 2026-07), true OOS 2023-04 -> 2026-07",
        "source": "olaxbt/ai-market-maker data/ohlcv (Binance-style daily OHLCV)",
        "cross_validation": "9 shared coins vs original panel 2021-01..2023-04: "
                            "median level diff ~0.05%, ret corr 0.9996-0.99997",
        "coins": COINS5,
        "split": str(SPLIT.date()),
        "results": results,
    }
    json.dump(board, open(BOARD, "w"), indent=2)
    print("\nsaved exp039_5y")

    if os.environ.get("SKIP_LEDGER") != "1":
        led = json.load(open(LEDGER))
        led["experiments"].append({
            "id": "EXP-039-FIVE-YEAR",
            "date": "2026-10-30",
            "focus": "top-5 on last 5 years (2021-01->2026-07, 15-coin majors panel, "
                     "olaxbt source cross-validated): frozen-at-2023 true OOS 3.3y + brain63 live sim",
            "outcome": "EXP-039-5Y",
        })
        json.dump(led, open(LEDGER, "w"), indent=2)
        print("ledger:", len(led["experiments"]))


if __name__ == "__main__":
    main()
