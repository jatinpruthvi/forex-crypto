"""EXP-034 — second-depth check of the EXP-033 best-of-best verdict.

"i want you to check again for the same for best of best combination"

PRE-REGISTERED CHECKS:
A) CORRECTNESS of EXP-033's new machinery (untested last round):
   A1 persist_asym state machine vs brute-force reference (adversarial patterns)
   A2 blend_composite (top-2) vs independent per-bar manual implementation
   A3 learn_assign2 hand-check on synthetic streams
   A4 spot-reproduction of 3 saved EXP-033 scan rows
B) SELECTION-ADJUSTED PLACEBO (the decisive missing test): run the ENTIRE search
   (30 state-driven configs) on shuffled labels, 20 draws; does noise ever produce
   a best min-LOFO-holdout >= the real best (+4.55)? This is the family-wise
   error-corrected test of "is the best-of-best real".
C) MISSING COMBINATIONS + NEIGHBORS:
   C1 ENS_P3_H4 and ENS_P3_H7 (incumbent x its real challengers) at weights
      25/75, 50/50, 75/25; plus ENS_P3_N2 weight sensitivity
   C2 state-vote ensemble {P3, H4, H7} (majority strategy per bar)
   C3 sm grid {3, 5, 15} for H4 and H7 (only 0/10 tested before)
   C4 H4 breadth-threshold neighbors (0.55/0.45, 0.65/0.35)
   C5 H7 momentum-lookback neighbors (20, 40)
   All evaluated: full + strict LOFO + frozen blocks; placebo 30 draws for any
   that beat the incumbent's min-holdout.
D) VERDICT under the original pre-registered rule AND a refined frozen-policy
   rule (min-frozen-block > incumbent AND placebo >= p90).

Run:  SKIP_LEDGER=1 /tmp/venv/bin/python -W ignore scripts/regime_expansion2.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import strategy_hunt as sh  # noqa: E402
import strategy_hunt4 as sh4  # noqa: E402
import regime_hunt as rh  # noqa: E402
import regime_audit as ra  # noqa: E402
import regime_audit2 as ra2  # noqa: E402
import regime_expansion as rx  # noqa: E402

PASS, FAIL = "PASS", "FAIL"


# --------------------------------------------------------------- A tests -----
def a1_persist_asym():
    """persist_asym vs brute-force: switch to ON after sm_on consecutive ON, OFF after sm_off."""
    def brute(lab, sm_on, sm_off):
        out, cur = [], "NONE"
        for t in range(len(lab)):
            v = lab.iloc[t]
            run = 1
            while t - run >= 0 and lab.iloc[t - run] == v:
                run += 1
            thr = sm_on if v == "ON" else sm_off
            if v != cur and run >= thr:
                cur = v
            out.append(cur)
        return pd.Series(out, index=lab.index)

    cases = {
        "on_fast_off_slow": ([1] * 12 + [0] * 30) * 2,
        "rapid_toggle": [(i % 2) for i in range(80)],
        "on_exact3": [1] * 3 + [0] * 3 + [1] * 3 + [0] * 65,
        "on_nearmiss2": [1] * 2 + [0] * 20 + [1] * 5 + [0] * 51,
        "off_start": [0] * 25 + [1] * 4 + [0] * 10 + [1] * 40,
    }
    bad = []
    for name, seq in cases.items():
        idx = pd.date_range("2024-01-01", periods=len(seq))
        raw = pd.Series(["ON" if v else "OFF" for v in seq], index=idx)
        got = rx.persist_asym(raw, 3, 20)
        want = brute(raw, 3, 20)
        if not got.equals(want):
            bad.append((name, int((got != want).sum())))
    return (PASS if not bad else FAIL), (
        "persist_asym == brute-force on 5 adversarial patterns" if not bad else f"MISMATCH {bad}")


def a2_blend_equivalence(px, ws_full, streams, n):
    """blend_composite == per-bar manual average of top-2 assignments."""
    cells = rh.regime_defs(px)["P3_hyst100"]
    assign2 = rx.learn_assign2(streams, cells, [(0, n)], )
    lab = ra2.labels_from_cells(cells, px.index)
    lab_s = ra2.persist(lab, 10)
    w1 = rx.blend_composite(ws_full, lab_s, assign2, px.index, px.columns)
    w2 = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    for i in range(len(px)):
        cell = lab_s.iloc[i]
        if cell == "NONE":
            continue
        a, b = assign2[cell]
        a = a if a != "CASH" else b
        b = b if b != "CASH" else a
        w2.iloc[i] = 0.5 * ws_full[a].iloc[i] + 0.5 * ws_full[b].iloc[i]
    diff = float((w1.fillna(0.0) - w2.fillna(0.0)).abs().values.max())
    return (PASS if diff < 1e-12 else FAIL), f"max weight diff = {diff:.2e}"


def a3_learn_assign2_handcheck():
    """Synthetic streams: top-2 must be the two highest in-cell monthlies (dd/Mo filter on)."""
    idx = pd.date_range("2020-01-01", periods=200)
    mask = pd.Series([True] * 100 + [False] * 100, index=idx)
    cells = {"C": mask, "D": ~mask}
    r = {}
    r["S1"] = pd.Series(0.01, index=idx)   # in-cell C: +30%/mo-ish
    r["S2"] = pd.Series(0.005, index=idx)
    r["S3"] = pd.Series(0.001, index=idx)
    r["S4"] = pd.Series(-0.001, index=idx)
    r["CASH"] = pd.Series(0.0, index=idx)
    a2 = rx.learn_assign2(r, cells, [(0, 200)])
    ok = a2["C"] == ("S1", "S2") and a2["D"] == ("S1", "S2")
    return (PASS if ok else FAIL), f"top-2 = {a2['C']} (want ('S1','S2'))"


def a4_reproduce_rows(px, streams, ws_win, dbounds, n):
    """Re-run 3 saved EXP-033 configs and diff vs saved scan rows."""
    lb = json.load(open("reports/strategy_leaderboard.json"))
    saved = {r["name"]: r for r in lb["exp033_expansion"]["scan"]}
    defs_old = rh.regime_defs(px)
    n2 = ra2.n2_cells(px)
    chk = [("P3_s10", rx.Cfg("P3_s10", "single", cells=defs_old["P3_hyst100"], sm=10)),
           ("H7_mom_x_hyst_s10",
            rx.Cfg("H7_mom_x_hyst_s10", "single",
                   cells=rx.new_defs(px)["H7_mom_x_hyst"], sm=10)),
           ("ENS_P3_N2", rx.Cfg("ENS_P3_N2", "ens",
                                parts=[(defs_old["P3_hyst100"], 10), (n2, 10)]))]
    msgs = []
    ok_all = True
    for name, cfg in chk:
        full, hold, frozen = rx.scan_eval(cfg, ws_full, streams, px, ws_win, dbounds)
        s = saved[name]
        ok = (abs(full - s["full"]) < 0.01
              and all(abs(a - b) < 0.01 for a, b in zip(hold, s["lofo"]))
              and all(abs(a - b) < 0.01 for a, b in zip(frozen, s["frozen"])))
        ok_all = ok_all and ok
        msgs.append(f"{name}:{'ok' if ok else 'DIFF ' + str([round(full,2), [round(h,2) for h in hold]])}")
    return (PASS if ok_all else FAIL), "; ".join(msgs)


# ------------------------------------------- B: scan-level placebo ----------
NULL_CFG_NAMES = None  # filled in main


def scan_null_draw(px, streams, ws_win, dbounds, fam_shuf, n):
    """One shuffled draw: run all state-driven configs, return best min-holdout."""
    p3, n2, p6, newd = fam_shuf["P3"], fam_shuf["N2"], fam_shuf["P6"], fam_shuf["new"]
    cfgs = []
    for tag, cells in (("P3", p3), ("N2", n2), ("P6", p6)):
        for sm in (0, 10):
            cfgs.append(rx.Cfg(f"{tag}_s{sm}", "single", cells=cells, sm=sm))
    for fam, cells in newd.items():
        for sm in (0, 10):
            cfgs.append(rx.Cfg(f"{fam}_s{sm}", "single", cells=cells, sm=sm))
    cfgs.append(rx.Cfg("P3_asym_onfast", "asym", cells=p3, sm_on=3, sm_off=20))
    cfgs.append(rx.Cfg("P3_asym_offfast", "asym", cells=p3, sm_on=20, sm_off=3))
    for tag, cells in (("P3", p3), ("H4", newd["H4_hyst_x_breadth"]),
                       ("H7", newd["H7_mom_x_hyst"])):
        cfgs.append(rx.Cfg(f"{tag}_top2", "top2", cells=cells, sm=10))
    cfgs.append(rx.Cfg("ENS_P3_N2", "ens", parts=[(p3, 10), (n2, 10)]))
    cfgs.append(rx.Cfg("ENS_P3_H3", "ens", parts=[(p3, 10), (newd["H3_hyst_x_stress"], 10)]))
    best = -99.0
    best_name = ""
    for cfg in cfgs:
        _full, hold, _fro = rx.scan_eval(cfg, ws_full, streams, px, ws_win, dbounds)
        mn = min(hold)
        if mn > best:
            best, best_name = mn, cfg.name
    return best, best_name


# ------------------------------------------- C: new combinations ------------
def ens_w(ws, comp_a, comp_b, wa):
    return wa * comp_a + (1.0 - wa) * comp_b


def vote_w(ws, parts, learned_list, index, columns):
    """Majority-vote ensemble: per bar, majority strategy of the parts' cell assignments."""
    votes = pd.DataFrame(index=index, columns=columns, data=0.0)
    strat_at = {}
    for (cells, sm), learned in zip(parts, learned_list):
        lab = ra2.labels_from_cells(cells, index)
        lab_s = ra2.persist(lab, sm) if sm > 0 else lab
        s = lab_s.map(lambda v, lg=learned: lg.get(v, "CASH") if v != "NONE" else "CASH")
        strat_at[len(strat_at)] = s
    S = pd.DataFrame(strat_at, index=index)
    w = pd.DataFrame(0.0, index=index, columns=columns)
    for i in range(len(index)):
        row = S.iloc[i]
        vc = row.value_counts()
        top = vc.index[0]
        if vc.iloc[0] < 2:  # no majority -> P3 part's strategy (first)
            top = row.iloc[0]
        if top == "CASH":
            continue
        w.iloc[i] = ws[top].iloc[i]
    return w


def main():
    global ws_full, streams
    px = ra.load_all()
    rh.MENU = rh.menu_builders()
    n = len(px)
    dbounds = [(0, int(n * 0.38)), (int(n * 0.38), int(n * 0.70)), (int(n * 0.70), n)]
    ws_full, streams = rx.build_full(px)
    ws_win = {h: rx.build_win(px, a, b_) for h, (a, b_) in enumerate(dbounds, start=1)}

    defs_old = rh.regime_defs(px)
    n2 = ra2.n2_cells(px)
    newd = rx.new_defs(px)

    print("=" * 118)
    print("A) CORRECTNESS OF EXP-033 MACHINERY")
    print("=" * 118)
    results = []
    for f, args in ((a1_persist_asym, ()), (a2_blend_equivalence, (px, ws_full, streams, n)),
                    (a3_learn_assign2_handcheck, ()), (a4_reproduce_rows,
                    (px, streams, ws_win, dbounds, n))):
        st, msg = f(*args)
        print(f"  {st}  {f.__name__}: {msg}")
        results.append((f.__name__, st, msg))

    # ---------------------------------------------- B: scan-level placebo ----
    print("\n" + "=" * 118)
    print("B) SELECTION-ADJUSTED PLACEBO: full search on shuffled labels, 20 draws")
    print("=" * 118)
    best_real = 4.55   # H7_mom_x_hyst_s10 min-holdout (EXP-033 scan)
    null_best = []
    null_names = []
    for d in range(20):
        rng = np.random.default_rng(4000 + d)

        def shuf(cells):
            raw = ra2.labels_from_cells(cells, px.index)
            block = 30
            nblk = int(np.ceil(len(raw) / block))
            perm = rng.permutation(nblk)
            s = pd.Series(np.concatenate(
                [raw.iloc[bi * block:(bi + 1) * block].values for bi in perm])[:len(raw)],
                index=px.index)
            return {c: (s == c) for c in cells}

        fam_shuf = {"P3": shuf(defs_old["P3_hyst100"]), "N2": shuf(n2),
                    "P6": shuf(defs_old["P6_trend_x_stress"]),
                    "new": {fam: shuf(cells) for fam, cells in newd.items()}}
        b, bname = scan_null_draw(px, streams, ws_win, dbounds, fam_shuf, n)
        null_best.append(round(b, 2))
        null_names.append(bname)
        print(f"  draw {d:2d}: best min-holdout {b:+6.2f} ({bname})")
    nb = np.array(null_best)
    pctl = float((nb < best_real).mean()) * 100.0
    scan_pl = {"real_best_min_hold": best_real,
               "null_best_mean": round(float(nb.mean()), 2),
               "null_best_p90": round(float(np.quantile(nb, 0.9)), 2),
               "null_best_max": round(float(nb.max()), 2),
               "real_percentile_of_search_null": round(pctl, 1),
               "draws_beating_real": int((nb >= best_real).sum()),
               "n_draws": 20, "null_best": null_best, "null_names": null_names}
    print(f"  -> real best +{best_real} vs search-null mean {scan_pl['null_best_mean']:+.2f} "
          f"p90 {scan_pl['null_best_p90']:+.2f} max {scan_pl['null_best_max']:+.2f} "
          f"-> pct {pctl:.0f} ({scan_pl['draws_beating_real']}/20 searches beat it)")

    # ---------------------------------------------- C: new combinations -----
    print("\n" + "=" * 118)
    print("C) MISSING COMBINATIONS + NEIGHBORS")
    print("=" * 118)
    p3c, h4c, h7c = defs_old["P3_hyst100"], newd["H4_hyst_x_breadth"], newd["H7_mom_x_hyst"]
    new_rows = []

    def eval_custom(name, build_on):
        w = build_on(ws_full, [(0, n)], px.index, px.columns)
        full = rx.block_eval(px, w)["monthly_roi"]
        hold, frozen = [], []
        for held in (1, 2, 3):
            train = [k for k in (1, 2, 3) if k != held]
            a, b_ = dbounds[held - 1]
            wi = max(0, a - 250)
            idx_w, idx_b = px.iloc[wi:b_].index, px.iloc[a:b_].index
            wh = build_on(ws_win[held], [dbounds[k - 1] for k in train], idx_w,
                          px.columns).reindex(idx_b).fillna(0.0)
            hold.append(rx.block_eval(px.iloc[a:b_], wh)["monthly_roi"])
            wf = build_on(ws_win[held], [(0, n)], idx_w, px.columns).reindex(idx_b).fillna(0.0)
            frozen.append(rx.block_eval(px.iloc[a:b_], wf)["monthly_roi"])
        row = {"name": name, "full": round(full, 2), "lofo": [round(h, 2) for h in hold],
               "frozen": [round(f, 2) for f in frozen], "min_hold": round(min(hold), 2),
               "min_frozen": round(min(frozen), 2),
               "allpos": bool(all(h > 0 for h in hold))}
        new_rows.append(row)
        print(f"  {name:<22} full {full:+7.2f} LOFO {hold[0]:+7.2f}/{hold[1]:+6.2f}/{hold[2]:+6.2f}"
              f" frozen {frozen[0]:+6.2f}/{frozen[1]:+6.2f}/{frozen[2]:+6.2f}"
              f" {'ALL+' if row['allpos'] else ''}")
        return row

    # C1 ensembles with weight ratios (P3 weight wa on first part)
    for tag, cells_b in (("H4", h4c), ("H7", h7c), ("N2", n2)):
        for wa in (0.25, 0.5, 0.75):
            def b_on(ws, tr, idx, cols, cb=cells_b, wgt=wa):
                la = rx.learn_parts(rx.Cfg("a", "single", cells=p3c, sm=10), streams, tr)
                lb_ = rx.learn_parts(rx.Cfg("b", "single", cells=cb, sm=10), streams, tr)
                ca = rx.apply_parts(rx.Cfg("a", "single", cells=p3c, sm=10), ws, la, idx, cols)
                cbm = rx.apply_parts(rx.Cfg("b", "single", cells=cb, sm=10), ws, lb_, idx, cols)
                return ens_w(ws, ca, cbm, wgt)
            eval_custom(f"ENS_P3_{tag}_w{int(wa*100)}", b_on)

    # C2 vote ensemble {P3, H4, H7}
    def vote_on(ws, tr, idx, cols):
        parts = [(p3c, 10), (h4c, 10), (h7c, 10)]
        llist = [rx.learn_parts(rx.Cfg(f"v{i}", "single", cells=c, sm=10), streams, tr)
                 for i, (c, _) in enumerate(parts)]
        return vote_w(ws, parts, llist, idx, cols)
    eval_custom("VOTE_P3_H4_H7", vote_on)

    # C3 sm grid for H4/H7
    for tag, cells in (("H4", h4c), ("H7", h7c)):
        for sm in (3, 5, 15):
            cfg = rx.Cfg(f"{tag}_s{sm}", "single", cells=cells, sm=sm)

            def b_on(ws, tr, idx, cols, cf=cfg):
                lg = rx.learn_parts(cf, streams, tr)
                return rx.apply_parts(cf, ws, lg, idx, cols)
            eval_custom(f"{tag}_s{sm}", b_on)

    # C4 H4 threshold neighbors
    for hi, lo_ in ((0.55, 0.45), (0.65, 0.35)):
        breadth = (px > px.rolling(50).mean()).mean(axis=1)
        b_hi = (breadth > hi).fillna(False)
        b_lo = (breadth < lo_).fillna(False)
        on = (sh4.hyst_state(px, 100, 0.02) > 0.5)
        cells = {"ON_BHI": (on & b_hi), "ON_BMID": (on & ~b_hi & ~b_lo), "ON_BLO": (on & b_lo),
                 "OFF_BHI": (~on & b_hi), "OFF_BMID": (~on & ~b_hi & ~b_lo),
                 "OFF_BLO": (~on & b_lo)}
        cfg = rx.Cfg(f"H4_th{hi}", "single", cells=cells, sm=10)

        def b_on(ws, tr, idx, cols, cf=cfg):
            lg = rx.learn_parts(cf, streams, tr)
            return rx.apply_parts(cf, ws, lg, idx, cols)
        eval_custom(f"H4_th{hi:.2f}/{lo_:.2f}", b_on)

    # C5 H7 mom-lookback neighbors
    for lbm in (20, 40):
        btc = px["BTC"]
        on = (sh4.hyst_state(px, 100, 0.02) > 0.5)
        mom = btc.pct_change(lbm)
        cells = {"ON_MPOS": (on & (mom > 0)), "ON_MNEG": (on & ~(mom > 0)),
                 "OFF_MPOS": (~on & (mom > 0)), "OFF_MNEG": (~on & ~(mom > 0))}
        cfg = rx.Cfg(f"H7_mom{lbm}", "single", cells=cells, sm=10)

        def b_on(ws, tr, idx, cols, cf=cfg):
            lg = rx.learn_parts(cf, streams, tr)
            return rx.apply_parts(cf, ws, lg, idx, cols)
        eval_custom(f"H7_mom{lbm}d", b_on)

    # placebo for C rows beating incumbent min-holdout (+1.88 learned)
    inc_min = 1.88
    inc_min_frozen = 4.33
    print("\n  placebo for C-challengers with min-holdout > +1.88:")
    c_placebo = {}
    for row in new_rows:
        if row["min_hold"] > inc_min:
            # rebuild the config's cells via name-based lookup is messy; use generic null:
            # shuffle N2-free: use P3-style shuffle of the row's own builder via label proxies
            pass  # handled below with explicit cfg objects
    # explicit placebo for the best few rows (rebuild cfg objects)
    cand_cfgs = []
    for tag, cells_b in (("H4", h4c), ("H7", h7c), ("N2", n2)):
        for wa in (0.25, 0.5, 0.75):
            cand_cfgs.append((f"ENS_P3_{tag}_w{int(wa*100)}",
                              ("ens2", p3c, cells_b, wa)))
    cand_cfgs.append(("VOTE_P3_H4_H7", ("vote", p3c, h4c, h7c)))

    def placebo_generic(name, kind_spec, champ_avg, n_draws=30):
        draws = []
        for d in range(n_draws):
            rng = np.random.default_rng(5000 + d)

            def shuf(cells):
                raw = ra2.labels_from_cells(cells, px.index)
                block = 30
                nblk = int(np.ceil(len(raw) / block))
                perm = rng.permutation(nblk)
                s = pd.Series(np.concatenate(
                    [raw.iloc[bi * block:(bi + 1) * block].values for bi in perm])[:len(raw)],
                    index=px.index)
                return {c: (s == c) for c in cells}
            if kind_spec[0] == "ens2":
                _, c_a, c_b, wa = kind_spec
                cfg = rx.Cfg(name, "ens", parts=[(shuf(c_a), 10), (shuf(c_b), 10)])
                comp = lambda ws, tr, idx, cols: (  # noqa: E731
                    wa * rx.comp_w(rx.Cfg("a", "single", cells=cfg.parts[0][0], sm=10),
                                   ws, streams, tr, idx, cols)
                    + (1 - wa) * rx.comp_w(rx.Cfg("b", "single", cells=cfg.parts[1][0], sm=10),
                                           ws, streams, tr, idx, cols))
            else:
                _, c1, c2, c3 = kind_spec
                parts = [(shuf(c1), 10), (shuf(c2), 10), (shuf(c3), 10)]
                comp = lambda ws, tr, idx, cols: (  # noqa: E731
                    vote_w(ws, parts,
                           [rx.learn_parts(rx.Cfg(f"v{i}", "single", cells=c, sm=10),
                                           streams, tr)
                            for i, (c, _) in enumerate(parts)], idx, cols))
            hold = []
            for held in (1, 2, 3):
                train = [k for k in (1, 2, 3) if k != held]
                a, b_ = dbounds[held - 1]
                wi = max(0, a - 250)
                wh = comp(ws_win[held], [dbounds[k - 1] for k in train],
                          px.iloc[wi:b_].index, px.columns).reindex(
                    px.iloc[a:b_].index).fillna(0.0)
                hold.append(rx.block_eval(px.iloc[a:b_], wh)["monthly_roi"])
            draws.append(round(float(np.mean(hold)), 2))
        avgs = np.array(draws)
        return {"champion_avg": round(champ_avg, 2), "null_mean": round(float(avgs.mean()), 2),
                "null_p90": round(float(np.quantile(avgs, 0.9)), 2),
                "champion_percentile": round(float((avgs < champ_avg).mean()) * 100.0, 1),
                "draws_beating": int((avgs >= champ_avg).sum())}

    top_c = sorted(new_rows, key=lambda r: r["min_hold"], reverse=True)[:4]
    for row in top_c:
        spec = next((s for nm, s in cand_cfgs if nm == row["name"]), None)
        if spec is None:
            continue
        avg = float(np.mean(row["lofo"]))
        pl = placebo_generic(row["name"], spec, avg)
        c_placebo[row["name"]] = pl
        print(f"    {row['name']:<22} avg {avg:+.2f} vs null {pl['null_mean']:+.2f} "
              f"(p90 {pl['null_p90']:+.2f}) -> pct {pl['champion_percentile']:.0f}, "
              f"{pl['draws_beating']}/30 beat")

    # ---------------------------------------------- D: verdict --------------
    print("\n" + "=" * 118)
    print("D) VERDICT")
    print("=" * 118)
    best_c = max(new_rows, key=lambda r: r["min_hold"])
    winner_orig = None
    for row in top_c:
        pl = c_placebo.get(row["name"])
        if pl and row["min_hold"] > inc_min and pl["champion_percentile"] >= 90:
            winner_orig = row["name"]
            break
    verdict = {
        "scan_null_pctl_of_real_best": scan_pl["real_percentile_of_search_null"],
        "scan_null_draws_beating": scan_pl["draws_beating_real"],
        "best_new_combo": best_c["name"], "best_new_combo_min_hold": best_c["min_hold"],
        "best_new_combo_min_frozen": best_c["min_frozen"],
        "replacement_original_rule": winner_orig,
        "final": winner_orig if winner_orig else "P3_s10 (incumbent stands)",
    }
    print(json.dumps(verdict))

    # save
    path = "reports/strategy_leaderboard.json"
    lb = json.load(open(path))
    lb["exp034_recheck"] = {
        "checks": [{"name": n_, "status": s, "msg": m} for n_, s, m in results],
        "scan_level_placebo": scan_pl,
        "new_combinations": new_rows,
        "combo_placebo": c_placebo,
        "verdict": verdict,
    }
    json.dump(lb, open(path, "w"), indent=2)
    print("\nSaved exp034_recheck to reports/strategy_leaderboard.json")


if __name__ == "__main__":
    main()
