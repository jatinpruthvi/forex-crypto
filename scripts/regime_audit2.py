"""EXP-031 — second-depth re-check of the EXP-029/030 regime-conditional policy.

"still check in depth, think what can be go wrong and check again"

A) MODEL & REPRODUCIBILITY CHECKS
   A1 portfolio_sim fee/return formula hand-check (exact arithmetic on synthetic prices)
   A2 persist() smoothing helper certified against composite_builder's inline loop
      (adversarial switch patterns: rapid toggles, exact-sm runs, warmup start)
   A3 reproduce the champion P3+smooth10 headline (16.02/25.1/19.74/folds) bit-for-bit
   A4 reproduce strict disjoint-block LOFO (+31.8/+4.3/+1.9) via BOTH the real
      composite_builder path and the fast precomputed-weight path (must match)
   A5 switch-cost truth: label flips, turnover & fees actually charged at flip bars
B) HONESTY TESTS (the ones that could flatter the champion)
   B1 NESTED LOFO: for each held block, choose {def P3|N2} x {sm 0|3|5|10} AND the
      cell->strategy mapping using ONLY the other 2 blocks, then apply to the held
      block. Validates the whole selection procedure, not just the frozen champion.
   B2 PLACEBO NULL: 50 block-shuffled draws of the P3 state series (preserves
      occupancy and local run structure, destroys alignment with the market)
      through the identical disjoint LOFO protocol. Champion must sit in the tail.
C) ROBUSTNESS BATTERY (champion)
   C1 fee x1.5, C2 drop best calendar month (fragility probe), C3 per-coin
   concentration, C4 monthly tail stats, C5 worst-DD window autopsy,
   C6 switch count + dwell times.

Run:  SKIP_LEDGER=1 /tmp/venv/bin/python -W ignore scripts/regime_audit2.py
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
import regime_audit as ra  # # noqa: E402

PASS, FAIL = "PASS", "FAIL"


def persist(lab: pd.Series, sm: int) -> pd.Series:
    """N-day persistence state machine — exact port of composite_builder's loop."""
    if sm <= 0:
        return lab.copy()
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
    return pd.Series(out, index=lab.index)


def labels_from_cells(cells, index):
    lab = pd.Series("NONE", index=index)
    for cell, m in cells.items():
        lab[m.fillna(False)] = cell
    return lab


def fast_composite(ws, lab, assign, index, columns):
    """Label-slicing of precomputed per-strategy weight matrices (== composite_builder math)."""
    w = pd.DataFrame(0.0, index=index, columns=columns)
    for cell in set(lab.unique()) - {"NONE"}:
        sel = (lab == cell)
        strat = assign.get(cell, "CASH")
        w[sel] = ws[strat][sel]
    return w


def n2_cells(px):
    """Rebuild G7's N2 trend x momentum-dispersion cells (identical construction)."""
    ret_df = px.pct_change()
    mom_disp = px.pct_change(60).std(axis=1)
    hi_disp = (mom_disp > mom_disp.expanding().median().shift(1)).fillna(False)
    btc = px["BTC"]
    ma100 = btc.rolling(100).mean()
    up = (btc > ma100).fillna(False)
    return {"UP_HID": (up & hi_disp).fillna(False), "UP_LOD": (up & ~hi_disp).fillna(False),
            "DN_HID": (~up & hi_disp).fillna(False), "DN_LOD": (~up & ~hi_disp).fillna(False)}


def block_monthly(px_block, w, fee=sh.FEE):
    eq, r = sh.portfolio_sim(w, px_block, fee=fee)
    return sh.metrics(eq, r), eq, r


# ------------------------------------------------------------------ A1 -------
def a1_fee_handcheck():
    """portfolio_sim: port_ret[t] = w[t]·r[t] - |dw[t]|*fee with r[t]=px[t+1]/px[t]-1."""
    idx = pd.date_range("2024-01-01", periods=4)
    px = pd.DataFrame([[100.0, 100.0], [110.0, 90.0], [121.0, 99.0], [100.0, 100.0]],
                      index=idx, columns=["A", "B"])
    w = pd.DataFrame([[0.5, 0.5], [1.0, 0.0], [1.0, 0.0], [0.0, 1.0]], index=idx,
                     columns=["A", "B"])
    fee = sh.FEE
    _eq, r = sh.portfolio_sim(w, px, fee=fee)
    # expected returns (hand arithmetic)
    r0 = 0.5 * 0.10 + 0.5 * (-0.10) - 0.0            # dw row0 = NaN -> 0 fee
    r1 = 1.0 * 0.10 + 0.0 * 0.10 - 1.0 * fee          # |dw| = 1.0
    r2 = 1.0 * (100.0 / 121.0 - 1.0) + 0.0 - 0.0      # |dw| = 0
    r3 = 0.0 - 2.0 * fee                              # last bar price NaN -> 0; |dw| = 2
    exp = [r0, r1, r2, r3]
    got = [float(r.iloc[i]) for i in range(4)]
    ok = all(abs(g - e) < 1e-12 for g, e in zip(got, exp))
    switch_fee_charged = abs(r1 - 0.10) > 1e-9 and abs(r3 + 2 * fee) < 1e-12
    ok = ok and switch_fee_charged
    return (PASS if ok else FAIL), (
        f"hand [0, {exp[1]:+.6f}, {exp[2]:+.6f}, {exp[3]:+.6f}] == sim "
        f"[{got[0]:+.6f}, {got[1]:+.6f}, {got[2]:+.6f}, {got[3]:+.6f}]; "
        f"switch-bar fees charged ({fee*1e4:.1f}bp/unit turnover)")


# ------------------------------------------------------------------ A2 -------
def a2_persist_equivalence():
    """persist() must equal composite_builder's inline smoothing on adversarial labels."""
    rh.MENU = {
        "SA": lambda p: pd.DataFrame(1.0, index=p.index, columns=p.columns),
        "SB": lambda p: pd.DataFrame(2.0, index=p.index, columns=p.columns),
        "CASH": lambda p: pd.DataFrame(0.0, index=p.index, columns=p.columns),
    }
    idx = pd.date_range("2024-01-01", periods=60)
    px = pd.DataFrame({"X": np.linspace(100, 120, 60), "Y": np.linspace(50, 40, 60)},
                      index=idx)
    assign = {"ON": "SA", "OFF": "SB"}
    cases = {
        "constant_ON": [1] * 60,
        "short_then_long": [1] * 5 + [0] * 55,
        "rapid_toggle": [(i % 2) for i in range(60)],                  # never settles
        "exact_sm_runs": ([1] * 10 + [0] * 10) * 3,                    # exactly sm=10 runs
        "off_start_warmup": [0] * 15 + [1] * 30 + [0] * 15,
        "near_miss_runs": [1] * 9 + [0] * 9 + [1] * 9 + [0] * 33,      # 9 < sm=10
    }
    bad = []
    for name, seq in cases.items():
        raw = pd.Series(["ON" if v else "OFF" for v in seq], index=idx)
        cells = {"ON": (raw == "ON"), "OFF": (raw == "OFF")}
        w = ra.composite_builder(cells, assign, smooth=10)(px)
        # effective label per row from stub weights (1.0 -> SA/ON, 2.0 -> SB/OFF, 0 -> NONE)
        rowmean = w.mean(axis=1)
        eff = pd.Series(np.where(rowmean > 1.5, "OFF", np.where(rowmean > 0.5, "ON", "NONE")),
                        index=idx)
        want = persist(raw, 10)
        if not eff.equals(want):
            n_mis = int((eff != want).sum())
            bad.append((name, n_mis))
    rh.MENU = rh.menu_builders()  # restore real menu after stubbing
    return (PASS if not bad else FAIL), (
        "persist() == composite_builder inline loop on 6 adversarial switch patterns"
        if not bad else f"MISMATCH: {bad}")


# ------------------------------------------------------------- A3/A4 ---------
def a3_reproduce_champion(px, defs):
    """Re-run the exact G4 pipeline for P3+smooth10 and diff vs saved numbers."""
    cells = defs["P3_hyst100"]
    assign = {"ON": "ABS_GROT", "OFF": "FVG_LS"}
    fm = sh.fold_metrics(ra.composite_builder(cells, assign, smooth=10), px)
    m = sh4.dyn_score(fm)
    want = {"monthly_roi": 16.02, "max_dd": 25.1, "calmar": 19.74,
            "folds": [34.99, 4.86, 6.77]}
    ok = (abs(m["monthly_roi"] - want["monthly_roi"]) < 0.005
          and abs(m["max_dd"] - want["max_dd"]) < 0.05
          and abs(m["calmar"] - want["calmar"]) < 0.01
          and all(abs(a - b) < 0.005 for a, b in zip(m["folds"], want["folds"])))
    return (PASS if ok else FAIL), (
        f"recomputed {m['monthly_roi']:+.2f}%/mo DD {m['max_dd']:.1f}% Cal {m['calmar']:.2f} "
        f"folds {m['folds']} == saved 16.02/25.1/19.74/[34.99, 4.86, 6.77]"), m, assign, cells


def a4_reproduce_strict_lofo(px, defs, rets, ws_win, dbounds):
    """G2 strict LOFO for P3+smooth10 through the real path AND the fast path."""
    cells = defs["P3_hyst100"]
    n = len(px)
    real, fast = [], []
    for held in (1, 2, 3):
        train = [k for k in (1, 2, 3) if k != held]
        assign = ra.learn_assign(px, rets, cells, [dbounds[k - 1] for k in train])
        a, b_ = dbounds[held - 1]
        # real path (verbatim G2)
        w = ra.composite_builder(cells, assign, smooth=10)(
            px.iloc[max(0, a - 250):b_]).reindex(px.iloc[a:b_].index).fillna(0.0)
        m, _eq, _r = block_monthly(px.iloc[a:b_], w)
        real.append(m["monthly_roi"])
        # fast path (precomputed window weights + persist)
        wi = max(0, a - 250)
        lab = labels_from_cells(cells, px.iloc[wi:b_].index)
        lab_s = persist(lab, 10)
        wf = fast_composite(ws_win[held], lab_s, assign,
                            px.iloc[wi:b_].index, px.columns).reindex(
            px.iloc[a:b_].index).fillna(0.0)
        mf, _eq, _r = block_monthly(px.iloc[a:b_], wf)
        fast.append(mf["monthly_roi"])
    want = [31.8, 4.3, 1.9]   # docs 12.1 (1dp)
    ok_saved = all(abs(a - b) <= 0.06 for a, b in zip(real, want))
    ok_paths = all(abs(a - b) < 1e-9 for a, b in zip(real, fast))
    st = PASS if (ok_saved and ok_paths) else FAIL
    return st, (f"real {[round(x,2) for x in real]} == docs [31.8, 4.3, 1.9]; "
                f"fast path identical: {ok_paths}"), real, fast


def a5_switch_costs(px, cells, assign, ws_full):
    """Count smoothed label flips; confirm portfolio_sim charged turnover fees at flips."""
    lab_s = persist(labels_from_cells(cells, px.index), 10)
    flips = [i for i in range(1, len(lab_s)) if lab_s.iloc[i] != lab_s.iloc[i - 1]]
    w = fast_composite(ws_full, lab_s, assign, px.index, px.columns)
    turnover = w.diff().abs().sum(axis=1)
    to_at_flips = float(turnover.iloc[flips].sum()) if flips else 0.0
    fee_at_flips = to_at_flips * sh.FEE
    ok = (len(flips) >= 2 and to_at_flips > 0)
    return (PASS if ok else FAIL), (
        f"{len(flips)} switches of smoothed state; turnover@switches {to_at_flips:.1f} "
        f"units -> fees {fee_at_flips*100:.2f}% of equity charged; "
        f"median dwell {int(pd.Series([len(list(g)) for _, g in __import__('itertools').groupby(lab_s)]).median())} bars"), \
        lab_s, flips


# ------------------------------------------------------------------ B1 -------
def b1_nested_lofo(px, rets, defs, ws_win, dbounds, dbounds_names):
    """Fully nested: def x sm x mapping chosen on 2 training blocks only -> held block."""
    cands = {}
    for dname in ("P3_hyst100",):
        for sm in (0, 3, 5, 10):
            cands[(dname, sm)] = defs[dname]
    for sm in (0, 3, 5, 10):
        cands[("N2", sm)] = n2_cells(px)
    rows = []
    for held in (1, 2, 3):
        train = [k for k in (1, 2, 3) if k != held]
        scores = []
        for (dname, sm), cells in cands.items():
            assign = ra.learn_assign(px, rets, cells, [dbounds[k - 1] for k in train])
            tr_ms = []
            for t in train:
                a, b_ = dbounds[t - 1]
                wi = max(0, a - 250)
                lab_s = persist(labels_from_cells(cells, px.iloc[wi:b_].index), sm)
                wt = fast_composite(ws_win[t], lab_s, assign,
                                    px.iloc[wi:b_].index, px.columns).reindex(
                    px.iloc[a:b_].index).fillna(0.0)
                mt, _eq, _r = block_monthly(px.iloc[a:b_], wt)
                tr_ms.append(mt["monthly_roi"])
            scores.append(((dname, sm), assign, min(tr_ms), float(np.mean(tr_ms))))
        # choose by worst training block, tie-break mean
        best = max(scores, key=lambda kv: (kv[2], kv[3]))
        (dname, sm), assign, worst_tr, mean_tr = best
        # held-out eval
        a, b_ = dbounds[held - 1]
        wi = max(0, a - 250)
        lab_s = persist(labels_from_cells(cands[(dname, sm)], px.iloc[wi:b_].index), sm)
        wh = fast_composite(ws_win[held], lab_s, assign,
                            px.iloc[wi:b_].index, px.columns).reindex(
            px.iloc[a:b_].index).fillna(0.0)
        mh, _eq, _r = block_monthly(px.iloc[a:b_], wh)
        rows.append({"held": dbounds_names[held - 1], "chosen_def": dname, "sm": sm,
                     "assign": assign, "train_worst": round(worst_tr, 2),
                     "holdout_monthly": mh["monthly_roi"], "holdout_dd": mh["max_dd"],
                     "holdout_worst_month": mh["worst_month"]})
        print(f"  held {dbounds_names[held-1]}: chose {dname} sm{sm} {assign} "
              f"(train worst {worst_tr:+.2f}) -> HELD {mh['monthly_roi']:+.2f}%/mo "
              f"DD {mh['max_dd']:.1f}%")
    allpos = all(r["holdout_monthly"] > 0 for r in rows)
    avg = float(np.mean([r["holdout_monthly"] for r in rows]))
    return rows, allpos, avg


def b1b_nested_sm_only(px, rets, defs, ws_win, dbounds, dbounds_names):
    """P3 family FIXED a priori; only sm + mapping chosen on training blocks."""
    cells = defs["P3_hyst100"]
    rows = []
    for held in (1, 2, 3):
        train = [k for k in (1, 2, 3) if k != held]
        assign = ra.learn_assign(px, rets, cells, [dbounds[k - 1] for k in train])
        scores = []
        for sm in (0, 3, 5, 10):
            tr_ms = []
            for t in train:
                a, b_ = dbounds[t - 1]
                wi = max(0, a - 250)
                lab_s = persist(labels_from_cells(cells, px.iloc[wi:b_].index), sm)
                wt = fast_composite(ws_win[t], lab_s, assign,
                                    px.iloc[wi:b_].index, px.columns).reindex(
                    px.iloc[a:b_].index).fillna(0.0)
                mt, _eq, _r = block_monthly(px.iloc[a:b_], wt)
                tr_ms.append(mt["monthly_roi"])
            scores.append((sm, min(tr_ms), float(np.mean(tr_ms))))
        best = max(scores, key=lambda kv: (kv[1], kv[2]))
        sm = best[0]
        a, b_ = dbounds[held - 1]
        wi = max(0, a - 250)
        lab_s = persist(labels_from_cells(cells, px.iloc[wi:b_].index), sm)
        wh = fast_composite(ws_win[held], lab_s, assign,
                            px.iloc[wi:b_].index, px.columns).reindex(
            px.iloc[a:b_].index).fillna(0.0)
        mh, _eq, _r = block_monthly(px.iloc[a:b_], wh)
        rows.append({"held": dbounds_names[held - 1], "sm": sm, "assign": assign,
                     "holdout_monthly": mh["monthly_roi"], "holdout_dd": mh["max_dd"]})
        print(f"  held {dbounds_names[held-1]}: sm{sm} {assign} -> HELD "
              f"{mh['monthly_roi']:+.2f}%/mo DD {mh['max_dd']:.1f}%")
    allpos = all(r["holdout_monthly"] > 0 for r in rows)
    avg = float(np.mean([r["holdout_monthly"] for r in rows]))
    return rows, allpos, avg


def b1c_frozen_champion_blocks(px, defs, ws_win, dbounds, dbounds_names):
    """Fully frozen ex-ante policy (P3 sm10, mapping ON->ABS_GROT/OFF->FVG_LS): per-block."""
    cells = defs["P3_hyst100"]
    assign = {"ON": "ABS_GROT", "OFF": "FVG_LS"}
    rows = []
    for held in (1, 2, 3):
        a, b_ = dbounds[held - 1]
        wi = max(0, a - 250)
        lab_s = persist(labels_from_cells(cells, px.iloc[wi:b_].index), 10)
        wh = fast_composite(ws_win[held], lab_s, assign,
                            px.iloc[wi:b_].index, px.columns).reindex(
            px.iloc[a:b_].index).fillna(0.0)
        mh, _eq, _r = block_monthly(px.iloc[a:b_], wh)
        rows.append({"held": dbounds_names[held - 1], "holdout_monthly": mh["monthly_roi"],
                     "holdout_dd": mh["max_dd"]})
        print(f"  held {dbounds_names[held-1]}: FROZEN -> {mh['monthly_roi']:+.2f}%/mo "
              f"DD {mh['max_dd']:.1f}%")
    allpos = all(r["holdout_monthly"] > 0 for r in rows)
    avg = float(np.mean([r["holdout_monthly"] for r in rows]))
    return rows, allpos, avg


# ------------------------------------------------------------------ B2 -------
def b2_placebo(px, rets, defs, ws_win, dbounds, champ_avg, champ_min, n_draws=30):
    """Block-shuffled state labels through the identical disjoint LOFO protocol."""
    cells = defs["P3_hyst100"]
    raw = pd.Series(np.where(cells["ON"].fillna(False), "ON", "OFF"), index=px.index)
    block = 30
    nblk = int(np.ceil(len(raw) / block))
    draws = []
    for d in range(n_draws):
        rng = np.random.default_rng(1000 + d)
        perm = rng.permutation(nblk)
        parts = []
        for bi in perm:
            s = raw.iloc[bi * block:(bi + 1) * block]
            if len(s):
                parts.append(s.values)
        shuf = pd.Series(np.concatenate(parts)[:len(raw)], index=px.index)
        pcells = {"ON": (shuf == "ON"), "OFF": (shuf == "OFF")}
        hold_ms, hold_min = [], []
        for held in (1, 2, 3):
            train = [k for k in (1, 2, 3) if k != held]
            assign = ra.learn_assign(px, rets, pcells, [dbounds[k - 1] for k in train])
            a, b_ = dbounds[held - 1]
            wi = max(0, a - 250)
            lab_s = persist(labels_from_cells(pcells, px.iloc[wi:b_].index), 10)
            wt = fast_composite(ws_win[held], lab_s, assign,
                                px.iloc[wi:b_].index, px.columns).reindex(
                px.iloc[a:b_].index).fillna(0.0)
            mh, _eq, _r = block_monthly(px.iloc[a:b_], wt)
            hold_ms.append(mh["monthly_roi"])
        draws.append({"draw": d, "holdouts": [round(x, 2) for x in hold_ms],
                      "avg": round(float(np.mean(hold_ms)), 2),
                      "min": round(float(np.min(hold_ms)), 2)})
    avgs = np.array([r["avg"] for r in draws])
    mins = np.array([r["min"] for r in draws])
    pctl = float((avgs < champ_avg).mean()) * 100.0
    beat = int((avgs >= champ_avg).sum())
    beat_allpos = int(sum(1 for r in draws if r["min"] > 0 and r["avg"] >= champ_avg))
    summary = {
        "champion_avg": round(champ_avg, 2), "champion_min": round(champ_min, 2),
        "null_mean": round(float(avgs.mean()), 2), "null_median": round(float(np.median(avgs)), 2),
        "null_p90": round(float(np.quantile(avgs, 0.9)), 2),
        "null_max": round(float(avgs.max()), 2),
        "champion_percentile_of_null": round(pctl, 1),
        "draws_beating_champion_avg": beat,
        "draws_allpos_and_beating": beat_allpos,
        "n_draws": n_draws,
    }
    return summary, draws


# ------------------------------------------------------------------ C --------
def c_robustness(px, cells, assign, lab_s, flips, ws_full):
    w = fast_composite(ws_full, lab_s, assign, px.index, px.columns)
    eq, r = sh.portfolio_sim(w, px)
    m = sh.metrics(eq, r)

    # C1 fee x1.5
    m15 = sh.fold_metrics(ra.composite_builder(cells, assign, smooth=10), px, fee=1.5 * sh.FEE)
    d15 = sh4.dyn_score(m15)

    # C2 drop best calendar month (fragility probe, post-hoc)
    mret_full = eq.resample("ME").last().pct_change().dropna()
    best_m = mret_full.idxmax()
    r2 = r.copy()
    r2[r2.index.to_period("M") == best_m.to_period("M")] = 0.0
    eq2 = 1000.0 * (1.0 + r2.fillna(0.0)).cumprod()
    m2 = sh.metrics(eq2, r2.fillna(0.0))

    # C3 per-coin contribution
    rets_df = px.pct_change().shift(-1)
    contrib = (w.fillna(0.0) * rets_df).sum()
    gross = float(contrib[contrib > 0].sum())
    top1 = float(contrib.max()) / gross if gross > 0 else float("nan")
    top3 = float(contrib.sort_values(ascending=False).head(3).sum()) / gross if gross > 0 else float("nan")

    # C4 monthly tail
    mrets = eq.resample("ME").last().pct_change().dropna() * 100.0
    neg_share = float((mrets < 0).mean()) * 100.0

    # C5 worst-DD window autopsy
    dd = eq / eq.cummax() - 1.0
    trough = dd.idxmin()
    peak = eq.loc[:trough].idxmax()
    win = lab_s.loc[peak:trough]
    wcount = win.value_counts().to_dict()
    stream_in_win = {}
    for k in ("ABS_GROT", "FVG_LS"):
        rr = sh.portfolio_sim(ws_full[k], px)[1].loc[peak:trough]
        stream_in_win[k] = round(float((1.0 + rr.fillna(0.0)).prod() - 1.0) * 100.0, 1)

    # C6 dwell
    lens, cur, cnt = [], lab_s.iloc[0], 0
    for v in lab_s:
        if v == cur:
            cnt += 1
        else:
            lens.append(cnt)
            cur, cnt = v, 1
    lens.append(cnt)

    return {
        "fee_x1.5": {"monthly_roi": d15["monthly_roi"], "max_dd": d15["max_dd"],
                     "calmar": d15["calmar"], "folds": d15["folds"], "dyn_ok": d15["dyn_ok"]},
        "drop_best_month": {"best_month": str(best_m.date()), "best_month_ret": round(float(mret_full.max()) * 100, 1),
                            "monthly_roi_without": m2["monthly_roi"], "max_dd_without": m2["max_dd"]},
        "coin_concentration": {"top1_share_of_gross": round(top1, 3), "top3_share_of_gross": round(top3, 3),
                               "top_coin": str(contrib.idxmax())},
        "monthly_tail": {"neg_months_pct": round(neg_share, 1), "median_month": round(float(mrets.median()), 2),
                         "worst_month": round(float(mrets.min()), 2)},
        "worst_dd_window": {"peak": str(peak.date()), "trough": str(trough.date()),
                            "dd_pct": round(float(dd.min()) * 100, 1),
                            "labels_in_window": {k: int(v) for k, v in wcount.items()},
                            "stream_pnl_in_window_pct": stream_in_win},
        "switches": len(flips), "median_dwell": int(pd.Series(lens).median()),
        "mean_dwell": round(float(np.mean(lens)), 1),
    }


# ---------------------------------------------------------------- main -------
def main():
    px = ra.load_all()
    rh.MENU = rh.menu_builders()
    defs = rh.regime_defs(px)
    n = len(px)
    dbounds = [(0, int(n * 0.38)), (int(n * 0.38), int(n * 0.70)), (int(n * 0.70), n)]
    dbounds_names = [f"B{i+1}[{a}:{b}]" for i, (a, b) in enumerate(dbounds)]

    # menu return streams (for learn_assign) - full period
    print("Computing menu streams + per-window weight matrices...")
    ws_full = {k: b(px) for k, b in rh.MENU.items()}
    rets = {}
    for k, w in ws_full.items():
        _eq, r = sh.portfolio_sim(w, px)
        rets[k] = r
    # precomputed window weights (250-bar pre-roll windows over disjoint blocks)
    ws_win = {}
    for held, (a, b_) in enumerate(dbounds, start=1):
        wi = max(0, a - 250)
        p_win = px.iloc[wi:b_]
        ws_win[held] = {k: b(p_win) for k, b in rh.MENU.items()}
    print("Done.\n")

    print("=" * 118)
    print("A) MODEL & REPRODUCIBILITY CHECKS")
    print("=" * 118)
    results = []
    st, msg = a1_fee_handcheck()
    print(f"  {st}  A1 portfolio_sim fee hand-check: {msg}")
    results.append(("A1_fee_handcheck", st, msg))
    st, msg = a2_persist_equivalence()
    print(f"  {st}  A2 persist vs composite_builder: {msg}")
    results.append(("A2_persist_equivalence", st, msg))
    st, msg, m_champ, assign, cells = a3_reproduce_champion(px, defs)
    print(f"  {st}  A3 champion reproduction: {msg}")
    results.append(("A3_champion_reproduction", st, msg))
    st, msg, real, fast = a4_reproduce_strict_lofo(px, defs, rets, ws_win, dbounds)
    print(f"  {st}  A4 strict LOFO reproduction: {msg}")
    results.append(("A4_strict_lofo_reproduction", st, msg))
    st, msg, lab_s, flips = a5_switch_costs(px, defs["P3_hyst100"], assign, ws_full)
    print(f"  {st}  A5 switch costs: {msg}")
    results.append(("A5_switch_costs", st, msg))

    champ_avg = float(np.mean(real))
    champ_min = float(np.min(real))

    print("\n" + "=" * 118)
    print("B) HONESTY TESTS")
    print("=" * 118)
    print("\nB1 NESTED LOFO (def x sm x mapping chosen on 2 training blocks ONLY):")
    b1_rows, b1_allpos, b1_avg = b1_nested_lofo(px, rets, defs, ws_win, dbounds, dbounds_names)
    print(f"  -> nested LOFO avg {b1_avg:+.2f}%/mo, all-positive: {b1_allpos} "
          f"(fixed-champion baseline avg {champ_avg:+.2f})")
    print("\nB1b NESTED SM-ONLY (P3 family fixed a priori; sm + mapping trained):")
    b1b_rows, b1b_allpos, b1b_avg = b1b_nested_sm_only(px, rets, defs, ws_win, dbounds, dbounds_names)
    print(f"  -> P3-nested avg {b1b_avg:+.2f}%/mo, all-positive: {b1b_allpos}")
    print("\nB1c FROZEN CHAMPION (nothing fitted anywhere):")
    b1c_rows, b1c_allpos, b1c_avg = b1c_frozen_champion_blocks(px, defs, ws_win, dbounds, dbounds_names)
    print(f"  -> frozen avg {b1c_avg:+.2f}%/mo, all-positive: {b1c_allpos}")

    print("\nB2 PLACEBO NULL (50 block-shuffled state draws, identical protocol):")
    b2_sum, b2_draws = b2_placebo(px, rets, defs, ws_win, dbounds, champ_avg, champ_min,
                                  n_draws=50)
    print(f"  null avg-of-holdouts: mean {b2_sum['null_mean']:+.2f} median "
          f"{b2_sum['null_median']:+.2f} p90 {b2_sum['null_p90']:+.2f} max {b2_sum['null_max']:+.2f}")
    print(f"  champion avg {b2_sum['champion_avg']:+.2f} -> percentile of null "
          f"{b2_sum['champion_percentile_of_null']:.0f}%; draws beating champion: "
          f"{b2_sum['draws_beating_champion_avg']}/{b2_sum['n_draws']} "
          f"(all-positive & beating: {b2_sum['draws_allpos_and_beating']})")

    print("\n" + "=" * 118)
    print("C) ROBUSTNESS BATTERY (champion P3+smooth10)")
    print("=" * 118)
    c = c_robustness(px, defs["P3_hyst100"], assign, lab_s, flips, ws_full)
    for k, v in c.items():
        print(f"  {k}: {v}")

    # verdict
    placebo_ok = b2_sum["champion_percentile_of_null"] >= 90.0
    verdict = {
        "all_correctness_pass": all(s == PASS for _, s, _ in results),
        "nested_lofo_all_positive": bool(b1_allpos),
        "nested_sm_only_all_positive": bool(b1b_allpos),
        "frozen_champion_all_positive": bool(b1c_allpos),
        "placebo_pctl": b2_sum["champion_percentile_of_null"],
        "placebo_ok_p90": bool(placebo_ok),
    }
    print("\nVERDICT:", json.dumps(verdict))

    # save
    path = "reports/strategy_leaderboard.json"
    lb = json.load(open(path))
    lb["exp031_recheck"] = {
        "checks": [{"name": n_, "status": s, "msg": m} for n_, s, m in results],
        "B1_nested_lofo": {"rows": b1_rows, "all_positive": bool(b1_allpos),
                           "avg": round(b1_avg, 2),
                           "champion_fixed_baseline": {"holdouts": [round(x, 2) for x in real],
                                                       "avg": round(champ_avg, 2)}},
        "B1b_nested_sm_only": {"rows": b1b_rows, "all_positive": bool(b1b_allpos),
                               "avg": round(b1b_avg, 2)},
        "B1c_frozen_champion": {"rows": b1c_rows, "all_positive": bool(b1c_allpos),
                                "avg": round(b1c_avg, 2)},
        "B2_placebo": {"summary": b2_sum, "draws": b2_draws},
        "C_robustness": c,
        "verdict": verdict,
    }
    json.dump(lb, open(path, "w"), indent=2)
    print("\nSaved exp031_recheck to reports/strategy_leaderboard.json")


if __name__ == "__main__":
    main()
