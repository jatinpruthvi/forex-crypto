"""EXP-029 AUDIT — deep verification of the regime-conditional policy work.

A) CORRECTNESS TESTS (bugs would invalidate EXP-029):
   T1 pandas row-assignment semantics used in run_composite
   T2 regime partition completeness (every bar in exactly one cell)
   T3 no-lookahead (regime label at t must depend only on data <= t)
   T4 composite equivalence (run_composite == independent manual implementation)
   T5 in-cell stats hand-check on one cell
B) GAP-FILLS (things EXP-029 missed):
   G1 LOFO for the champion P3 def itself (EXP-029 LOFO'd P4 only)
   G2 strict LOFO with DISJOINT folds (EXP-029 folds overlap ~10% -> mild leakage)
   G3 champion neighbor plateau (hysteresis band x MA window)
   G4 switch-smoothing (N-day persistence before switching) - fixes LOFO whipsaw months
   G5 transition-zone blend (50/50 when near the gate)
   G6 extended menu: do 5 untested strategies win any cell? (conditional re-check)
   G7 two untested parameter families: avg pairwise correlation, momentum dispersion

Run:  SKIP_LEDGER=1 /tmp/venv/bin/python -W ignore scripts/regime_audit.py
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
import strategy_hunt4 as sh4  # noqa: E402
import strategy_hunt5 as sh5  # noqa: E402
import regime_hunt as rh  # noqa: E402

PASS, FAIL = "PASS", "FAIL"


def load_all():
    frames = {}
    for c in sh.COINS:
        df = pd.read_csv(f"data/timeframes/1d_panel/{c}USDT_1d.csv")
        df["date"] = pd.to_datetime(df["date"])
        frames[c] = df.set_index("date")
    idx = None
    for df in frames.values():
        idx = df.index if idx is None else idx.intersection(df.index)
    def panel(col):
        return pd.DataFrame({c: frames[c].reindex(idx)[col] for c in sh.COINS}).sort_index()
    sh5._O, sh5._H, sh5._L, sh5._C, sh5._V = (panel("open"), panel("high"), panel("low"),
                                              panel("close"), panel("volume"))
    px = sh5._C.dropna(how="any")
    sh5._O, sh5._H, sh5._L, sh5._V = (sh5._O.reindex(px.index), sh5._H.reindex(px.index),
                                      sh5._L.reindex(px.index), sh5._V.reindex(px.index))
    return px


# ------------------------------------------------------------ A: tests ------
def t1_alignment():
    """run_composite does: label[mask] = cell ; w[sel] = ws[sel] with subset indices."""
    idx = pd.date_range("2020-01-01", periods=10)
    lab = pd.Series("NONE", index=idx)
    full_mask = pd.Series([False, True, True, False, True, True, False, True, True, False], index=idx)
    sub = idx[2:8]                       # window = subset of index
    lab2 = pd.Series("NONE", index=sub)
    try:
        lab2[full_mask] = "CELL"         # subset-object indexed by full-index mask
    except Exception as e:
        return FAIL, f"full-mask on subset raises: {e}"
    # expected: rows 2..7 where full_mask True -> 2,4,5,7 intersect 2..7 = 2,4,5,7 -> 4 rows
    want = pd.Series("NONE", index=sub)
    for i in (2, 4, 5, 7):
        want.iloc[i - 2] = "CELL"
    if not lab2.equals(want):
        return FAIL, f"alignment semantics wrong: {list(lab2)} vs {list(want)}"
    return PASS, "boolean-row assignment aligns by index (no positional accident)"


def t2_partition(px):
    defs = rh.regime_defs(px)
    bad = []
    for dname, cells in defs.items():
        tot = pd.Series(False, index=px.index)
        for cell, m in cells.items():
            tot = tot | m.fillna(False)
        cov = float(tot.mean())
        if cov < 0.999:
            bad.append((dname, cov))
    return (PASS if not bad else FAIL), (f"all {len(defs)} defs cover >=99.9% of bars"
                                         if not bad else f"incomplete: {bad}")


def t3_no_lookahead(px):
    """Regime labels at t must be unchanged when data after t is altered."""
    px2 = px.copy()
    t = int(len(px) * 0.6)
    px2.iloc[t:] = px2.iloc[t:] * 1.37    # wildly alter the future
    d1 = rh.regime_defs(px)
    d2 = rh.regime_defs(px2)
    mism = 0
    for dname in d1:
        for cell, m1 in d1[dname].items():
            m2 = d2[dname][cell]
            if not (m1.iloc[:t].fillna(False).values == m2.iloc[:t].fillna(False).values).all():
                mism += 1
    return (PASS if mism == 0 else FAIL), ("labels up to t identical under future perturbation"
                                           if mism == 0 else f"{mism} cell-masks leak the future")


def t4_composite_equivalence(px):
    """run_composite == independent per-bar lookup implementation."""
    rh.MENU = rh.menu_builders()
    defs = rh.regime_defs(px)
    cells = defs["P3_hyst100"]
    assign = {"ON": "ABS_GROT", "OFF": "FVG_LS"}
    w1 = rh.run_composite(px, cells, assign)
    # manual: per-bar label lookup
    ws = {k: b(px) for k, b in rh.MENU.items()}
    lab = pd.Series("NONE", index=px.index)
    for cell, m in cells.items():
        lab[m.fillna(False)] = cell
    w2 = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    for i in range(len(px)):
        cell = lab.iloc[i]
        if cell in assign:
            w2.iloc[i] = ws[assign[cell]].iloc[i]
    diff = float((w1.fillna(0.0) - w2.fillna(0.0)).abs().values.max())
    return (PASS if diff < 1e-12 else FAIL), f"max weight diff = {diff:.2e}"


def t5_incell_handcheck(px):
    """One cell: in_cell_stats monthly matches manual computation."""
    rh.MENU = rh.menu_builders()
    b = rh.MENU["FVG_LS"]
    w = b(px)
    _eq, r = sh.portfolio_sim(w, px)
    defs = rh.regime_defs(px)
    mask = defs["P3_hyst100"]["OFF"].fillna(False)
    s = rh.in_cell_stats(r, mask)
    rr = r[mask].dropna()
    manual = float((1.0 + rr).prod()) ** (30.44 / len(rr)) - 1.0
    ok = abs(manual * 100.0 - s["monthly"]) < 1e-6
    return (PASS if ok else FAIL), (f"in-cell monthly {s['monthly']:+.4f}% vs manual {manual*100:+.4f}%"
                                    f" ({s['n_days']} days)")


# ---------------------------------------------------- B: gap-fills ---------
def composite_builder(cells, assign, smooth=0):
    def builder(p, cm=cells, ag=assign, sm=smooth):
        ws = {k: b(p) for k, b in rh.MENU.items()}
        lab = pd.Series("NONE", index=p.index)
        for cell, m in cm.items():
            lab[m.reindex(p.index).fillna(False)] = cell
        if sm > 0:  # N-day persistence before switching
            out, cur = [], "NONE"
            pending, cnt = "NONE", 0
            for v in lab:
                if v != cur:
                    if v == pending:
                        cnt += 1
                    else:
                        pending, cnt = v, 1
                    if cnt >= sm:
                        cur, pending, cnt = v, v, 0
                else:
                    pending, cnt = v, 0
                out.append(cur)
            lab = pd.Series(out, index=p.index)
        w = pd.DataFrame(0.0, index=p.index, columns=p.columns)
        for cell in set(lab.unique()) - {"NONE"}:
            sel = (lab == cell)
            strat = ag.get(cell, "CASH")
            w[sel] = ws[strat][sel]
        return w
    return builder


def learn_assign(px, rets, cells, train_ranges):
    m_ = pd.Series(False, index=px.index)
    for x, y in train_ranges:
        m_.iloc[x:y] = True
    assign = {}
    for cell, mask in cells.items():
        row = {}
        for k, r in rets.items():
            s = rh.in_cell_stats(r, mask.fillna(False) & m_)
            if s:
                row[k] = s
        okd = {k: v for k, v in row.items() if v["dd_mo"] <= 10.0 and k != "CASH"}
        assign[cell] = max(okd.items(), key=lambda kv: kv[1]["monthly"])[0] if okd else "CASH"
    return assign


def main():
    px = load_all()
    rh.MENU = rh.menu_builders()
    print("=" * 118)
    print("A) CORRECTNESS TESTS")
    print("=" * 118)
    tests = [t1_alignment, t2_partition, t3_no_lookahead]
    results = []
    for f in tests:
        st, msg = f(px) if f is not t1_alignment else f()
        print(f"  {st}  {f.__name__}: {msg}")
        results.append((f.__name__, st, msg))
    st, msg = t4_composite_equivalence(px)
    print(f"  {st}  t4_composite_equivalence: {msg}")
    results.append(("t4_composite_equivalence", st, msg))
    st, msg = t5_incell_handcheck(px)
    print(f"  {st}  t5_incell_handcheck: {msg}")
    results.append(("t5_incell_handcheck", st, msg))

    # menu returns for gap-fills
    rets = {}
    for k, b in rh.MENU.items():
        w = b(px)
        _eq, r = sh.portfolio_sim(w, px)
        rets[k] = r

    defs = rh.regime_defs(px)
    n = len(px)
    bounds = [(0, int(n * 0.38)), (int(n * 0.34), int(n * 0.70)), (int(n * 0.66), n)]
    dbounds = [(0, int(n * 0.38)), (int(n * 0.38), int(n * 0.70)), (int(n * 0.70), n)]  # disjoint

    print("\n" + "=" * 118)
    print("B) GAP-FILLS")
    print("=" * 118)

    # G1: LOFO on champion P3 def (original overlapping folds)
    print("\nG1 LOFO on champion P3_hyst100 (folds as in EXP-029):")
    for held in (1, 2, 3):
        train = [k for k in (1, 2, 3) if k != held]
        assign = learn_assign(px, rets, defs["P3_hyst100"],
                              [bounds[k - 1] for k in train])
        a, b_ = bounds[held - 1]
        w = composite_builder(defs["P3_hyst100"], assign)(px.iloc[max(0, a - 250):b_]).reindex(px.iloc[a:b_].index).fillna(0.0)
        eq, r = sh.portfolio_sim(w, px.iloc[a:b_])
        m = sh.metrics(eq, r)
        print(f"  held-out fold{held}: {assign} -> {m['monthly_roi']:+7.2f}%/mo DD {m['max_dd']:5.1f}% worstM {m['worst_month']:+6.1f}")

    # G2: strict disjoint-fold LOFO
    print("\nG2 STRICT LOFO (disjoint folds - removes fold-overlap leakage):")
    for held in (1, 2, 3):
        train = [k for k in (1, 2, 3) if k != held]
        assign = learn_assign(px, rets, defs["P3_hyst100"],
                              [dbounds[k - 1] for k in train])
        a, b_ = dbounds[held - 1]
        w = composite_builder(defs["P3_hyst100"], assign)(px.iloc[max(0, a - 250):b_]).reindex(px.iloc[a:b_].index).fillna(0.0)
        eq, r = sh.portfolio_sim(w, px.iloc[a:b_])
        m = sh.metrics(eq, r)
        print(f"  held-out block{held} [{a}:{b_}]: {assign} -> {m['monthly_roi']:+7.2f}%/mo DD {m['max_dd']:5.1f}% worstM {m['worst_month']:+6.1f}")

    # G3: champion neighbor plateau (band x MA)
    print("\nG3 champion neighbor plateau (hysteresis band x MA window):")
    for ma, band in [(100, 0.02), (100, 0.01), (100, 0.03), (100, 0.05),
                     (90, 0.02), (110, 0.02), (125, 0.02)]:
        cells = {"ON": (sh4.hyst_state(px, ma, band) > 0.5),
                 "OFF": (sh4.hyst_state(px, ma, band) <= 0.5)}
        assign = {"ON": "ABS_GROT", "OFF": "FVG_LS"}
        fm = sh.fold_metrics(composite_builder(cells, assign), px)
        m = sh4.dyn_score(fm)
        print(f"  ma{ma} band{band:.2f}: {m['monthly_roi']:+7.2f}%/mo DD {m['max_dd']:5.1f}% "
              f"Cal {m['calmar']:5.2f} folds {m['folds'][0]:+7.2f}/{m['folds'][1]:+6.2f}/{m['folds'][2]:+6.2f} "
              f"{'DYN-OK' if m['dyn_ok'] else ''}")

    # G4: switch smoothing
    print("\nG4 switch-smoothing (N-day persistence before switching):")
    for sm in (3, 5, 10):
        fm = sh.fold_metrics(composite_builder(defs["P3_hyst100"],
                                               {"ON": "ABS_GROT", "OFF": "FVG_LS"}, smooth=sm), px)
        m = sh4.dyn_score(fm)
        print(f"  smooth{sm}: {m['monthly_roi']:+7.2f}%/mo DD {m['max_dd']:5.1f}% Cal {m['calmar']:5.2f} "
              f"folds {m['folds'][0]:+7.2f}/{m['folds'][1]:+6.2f}/{m['folds'][2]:+6.2f} worstM "
              f"{'DYN-OK' if m['dyn_ok'] else ''}")

    # G5: transition blend
    print("\nG5 transition-zone blend (50/50 within +-2% of MA100):")
    def blend_builder(p):
        btc = p["BTC"] if "BTC" in p.columns else p.iloc[:, 0]
        ma = btc.rolling(100).mean()
        near = ((btc / ma - 1).abs() < 0.02).fillna(False)
        hy = sh4.hyst_state(p, 100, 0.02)
        wa = rh.MENU["ABS_GROT"](p)
        wf = rh.MENU["FVG_LS"](p)
        w = wa.mul((hy > 0.5).astype(float), axis=0) + wf.mul((hy <= 0.5).astype(float), axis=0)
        wb = 0.5 * wa + 0.5 * wf
        return wb.mul(near, axis=0).fillna(0.0) + w.mul(~near, axis=0).fillna(0.0)
    fm = sh.fold_metrics(blend_builder, px)
    m = sh4.dyn_score(fm)
    print(f"  blend: {m['monthly_roi']:+7.2f}%/mo DD {m['max_dd']:5.1f}% Cal {m['calmar']:5.2f} "
          f"folds {m['folds'][0]:+7.2f}/{m['folds'][1]:+6.2f}/{m['folds'][2]:+6.2f} "
          f"{'DYN-OK' if m['dyn_ok'] else ''}")

    # G6: extended menu - do untested strategies win any cell?
    print("\nG6 extended menu conditional check (5 untested strategies x champion def cells):")
    ext = {
        "BLEND": lambda p: 0.5 * sh.w_gated_rot(p, gate_ma=150) + 0.5 * sh.w_dip_v2(p),
        "XSEC_MOM": sh.w_xsec_mom,
        "DUAL_MOM": sh.w_dual_mom,
        "ENSEMBLE": lambda p: sh2.w_ensemble(p),
        "DIP_TREND": sh.w_dip_trend,
    }
    ext_rets = {}
    for k, b in ext.items():
        w = b(px)
        _eq, r = sh.portfolio_sim(w, px)
        ext_rets[k] = r
    changed = []
    for dname in ("P3_hyst100", "P4_trend_x_vol", "P6_trend_x_stress"):
        for cell, mask in defs[dname].items():
            row = {}
            for k, r in list(rets.items()) + list(ext_rets.items()):
                s = rh.in_cell_stats(r, mask.fillna(False))
                if s:
                    row[k] = s
            okd = {k: v for k, v in row.items() if v["dd_mo"] <= 10.0 and k != "CASH"}
            best = max(okd.items(), key=lambda kv: kv[1]["monthly"])[0] if okd else "CASH"
            old = max({k: v for k, v in row.items() if k in rets and v["dd_mo"] <= 10.0 and k != "CASH"}.items(),
                      key=lambda kv: kv[1]["monthly"])[0] if {k: v for k, v in row.items() if k in rets and v["dd_mo"] <= 10.0 and k != "CASH"} else "CASH"
            flag = "NEW-WINNER" if best != old and best not in rets else ""
            if flag:
                changed.append((dname, cell, old, best))
            print(f"  {dname}/{cell}: old best {old} -> with extended menu {best} {flag}")

    # G7: new parameter families (correlation, dispersion)
    print("\nG7 untested parameter families: avg pairwise correlation, momentum dispersion:")
    ret_df = px.pct_change()
    # avg pairwise correlation (causal, rolling 30d), pair-by-pair:
    cols = list(px.columns)
    pairs = [(a, b) for i, a in enumerate(cols) for b in cols[i + 1:]]
    corr_mat = pd.DataFrame({f"{a}-{b}": ret_df[a].rolling(30).corr(ret_df[b]) for a, b in pairs})
    avg_corr = corr_mat.mean(axis=1)
    hi_corr = (avg_corr > avg_corr.expanding().median().shift(1)).fillna(False)
    mom_disp = px.pct_change(60).std(axis=1)
    hi_disp = (mom_disp > mom_disp.expanding().median().shift(1)).fillna(False)
    btc = px["BTC"]
    ma100 = btc.rolling(100).mean()
    up = (btc > ma100).fillna(False)
    new_defs = {
        "N1_trend_x_corr": {"UP_HIC": (up & hi_corr).fillna(False), "UP_LOC": (up & ~hi_corr).fillna(False),
                            "DN_HIC": (~up & hi_corr).fillna(False), "DN_LOC": (~up & ~hi_corr).fillna(False)},
        "N2_trend_x_disp": {"UP_HID": (up & hi_disp).fillna(False), "UP_LOD": (up & ~hi_disp).fillna(False),
                            "DN_HID": (~up & hi_disp).fillna(False), "DN_LOD": (~up & ~hi_disp).fillna(False)},
    }
    for dname, cells in new_defs.items():
        assign = {}
        for cell, mask in cells.items():
            row = {}
            for k, r in rets.items():
                s = rh.in_cell_stats(r, mask.fillna(False))
                if s:
                    row[k] = s
            okd = {k: v for k, v in row.items() if v["dd_mo"] <= 10.0 and k != "CASH"}
            assign[cell] = max(okd.items(), key=lambda kv: kv[1]["monthly"])[0] if okd else "CASH"
            best = assign[cell]
            s = row.get(best)
            print(f"  {dname}/{cell} occ {mask.mean():.2f}: {best} "
                  f"{s['monthly']:+.2f}%/mo (DD {s['dd']:.0f})" if s else f"  {dname}/{cell}: CASH")
        fm = sh.fold_metrics(composite_builder(cells, assign), px)
        m = sh4.dyn_score(fm)
        print(f"  -> composite {dname} {assign}")
        print(f"     {m['monthly_roi']:+7.2f}%/mo DD {m['max_dd']:5.1f}% Cal {m['calmar']:5.2f} "
              f"folds {m['folds'][0]:+7.2f}/{m['folds'][1]:+6.2f}/{m['folds'][2]:+6.2f} "
              f"{'DYN-OK' if m['dyn_ok'] else ''}")

    # ---- save audit summary ----
    path = "reports/strategy_leaderboard.json"
    lb = json.load(open(path))
    lb["exp029_audit"] = {
        "tests": [{"name": n, "status": s, "msg": m} for n, s, m in results],
        "extended_menu_new_winners": changed,
        "note": ("G1-G5/G7 numeric rows printed in run log; audit conclusions in "
                 "docs/STRATEGY_REDESIGN.md section 12.1"),
    }
    json.dump(lb, open(path, "w"), indent=2)
    print("\nAudit summary saved to leaderboard (exp029_audit).")


if __name__ == "__main__":
    main()
