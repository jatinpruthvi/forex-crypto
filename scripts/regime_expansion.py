"""EXP-033 — Crypto regime-policy EXPANSION hunt: are we missing a best-of-best setup?

User: "check other families as well or combination just to make sure we are not missing
any best of best setup. make sure you test on real data and your ans should be realistic."

PRE-REGISTERED SCOPE (fixed before results):
  Baselines: incumbent P3+smooth10 (+16.02%/mo headline) + P3 sm0 + N2 + P6 family rows.
  A) NEW STATE FAMILIES (causal, BTC-driven, complement cells):
     H3 hyst x vol-stress | H4 hyst x breadth3 | H5 MA100-slope x trend | H6 DD-state
     | H7 mom30 x hyst | H8 alt-season(ETH/BTC) x hyst | H9 trend200 | H10 vol-quartile
  B) SMOOTHING VARIANTS: asymmetric persistence on P3 (switch ON fast/OFF slow and
     the reverse).
  C) STRATEGY COMBINATIONS: (1) top-2 50/50 blend per cell (vs argmax single);
     (2) static combo menu entries COMBO_A_GF (ABS_GROT+FVG_LS) and COMBO_A_G
     (ABS_GROT+GROT) as cell-assignable strategies.
  D) POLICY ENSEMBLES: weight-level 50/50 blends of validated composites
     (P3s10 x P6, P3s10 x N2, P3s10 x H3).
  HONESTY STACK (EXP-031): partition asserts, strict disjoint-block LOFO with mapping
    learned on 2 blocks -> 3rd, NESTED LOFO of the whole search (family x sm chosen on
    training only), placebo null (30 block-shuffled draws) for finalists.
  SELECTION RULE (pre-registered): a challenger replaces the incumbent ONLY if
    min-strict-LOFO-holdout > incumbent's AND placebo percentile >= 90 AND nested LOFO
    all-positive. In-sample maxima do NOT count (they rise mechanically with search width).

Run:  SKIP_LEDGER=1 /tmp/venv/bin/python -W ignore scripts/regime_expansion.py
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
import regime_audit as ra  # noqa: E402
import regime_audit2 as ra2  # noqa: E402

PASS, FAIL = "PASS", "FAIL"


def persist_asym(lab: pd.Series, sm_on: int, sm_off: int) -> pd.Series:
    """Asymmetric persistence: switch to ON after sm_on consecutive ON bars, OFF after sm_off."""
    out, cur = [], "NONE"
    pending, cnt = "NONE", 0
    for v in lab:
        if v != cur:
            if v == pending:
                cnt += 1
            else:
                pending, cnt = v, 1
            thr = sm_on if v == "ON" else sm_off
            if cnt >= thr:
                cur, pending, cnt = v, v, 0
        else:
            pending, cnt = v, 0
        out.append(cur)
    return pd.Series(out, index=lab.index)


def new_defs(px):
    """H3-H10 new state families (causal; complement cells everywhere)."""
    btc = px["BTC"]
    hy = sh4.hyst_state(px, 100, 0.02)
    on = (hy > 0.5)
    bvol = btc.pct_change().rolling(20).std()
    stress = (bvol > bvol.expanding().quantile(0.8).shift(1)).fillna(False)
    breadth = (px > px.rolling(50).mean()).mean(axis=1)
    b_hi = (breadth > 0.6).fillna(False)
    b_lo = (breadth < 0.4).fillna(False)
    ma100 = btc.rolling(100).mean()
    up100 = (btc > ma100).fillna(False)
    slope_up = (ma100 > ma100.shift(20)).fillna(False)
    dd = btc / btc.expanding().max() - 1.0
    mom30 = btc.pct_change(30)
    ethbtc = px["ETH"] / px["BTC"]
    rel_up = (ethbtc > ethbtc.rolling(100).mean()).fillna(False)
    ma200 = btc.rolling(200).mean()
    up200 = (btc > ma200).fillna(False)
    q25 = bvol.expanding().quantile(0.25).shift(1)
    q50 = bvol.expanding().quantile(0.5).shift(1)
    q75 = bvol.expanding().quantile(0.75).shift(1)

    out = {}
    out["H3_hyst_x_stress"] = {"ON_CALM": (on & ~stress), "ON_STRESS": (on & stress),
                               "OFF_CALM": (~on & ~stress), "OFF_STRESS": (~on & stress)}
    out["H4_hyst_x_breadth"] = {"ON_BHI": (on & b_hi), "ON_BMID": (on & ~b_hi & ~b_lo),
                                "ON_BLO": (on & b_lo), "OFF_BHI": (~on & b_hi),
                                "OFF_BMID": (~on & ~b_hi & ~b_lo), "OFF_BLO": (~on & b_lo)}
    out["H5_slope_x_trend"] = {"UP_RIS": (up100 & slope_up), "UP_FAL": (up100 & ~slope_up),
                               "DN_RIS": (~up100 & slope_up), "DN_FAL": (~up100 & ~slope_up)}
    out["H6_dd_state"] = {"DD_DEEP": (dd < -0.20), "DD_MID": ((dd >= -0.20) & (dd <= -0.05)),
                          "DD_HIGH": (dd > -0.05)}
    out["H7_mom_x_hyst"] = {"ON_MPOS": (on & (mom30 > 0)), "ON_MNEG": (on & ~(mom30 > 0)),
                            "OFF_MPOS": (~on & (mom30 > 0)), "OFF_MNEG": (~on & ~(mom30 > 0))}
    out["H8_alts_x_hyst"] = {"ON_ALT": (on & rel_up), "ON_BTC": (on & ~rel_up),
                             "OFF_ALT": (~on & rel_up), "OFF_BTC": (~on & ~rel_up)}
    out["H9_trend200"] = {"UP": up200, "DOWN": ~up200}
    q1 = (bvol <= q25).fillna(False)
    q2 = ((bvol > q25) & (bvol <= q50)).fillna(False)
    q3 = ((bvol > q50) & (bvol <= q75)).fillna(False)
    out["H10_vol_quart"] = {"Q1": q1, "Q2": q2, "Q3": q3, "Q4": ~(q1 | q2 | q3)}
    return out


def blend_composite(ws, lab, assign2, index, columns):
    """Top-2 per-cell 50/50 blend. assign2: {cell: (s1, s2)}."""
    w = pd.DataFrame(0.0, index=index, columns=columns)
    for cell in set(lab.unique()) - {"NONE"}:
        sel = (lab == cell)
        pair = assign2.get(cell)
        if not pair or pair[0] == "CASH" and pair[1] == "CASH":
            continue
        a = pair[0] if pair[0] != "CASH" else pair[1]
        b = pair[1] if pair[1] != "CASH" else pair[0]
        w[sel] = 0.5 * ws[a][sel] + 0.5 * ws[b][sel]
    return w


def learn_assign2(streams, cells, train_ranges):
    """Top-2 per cell by in-cell monthly (training only), dd/Mo<=10 filter."""
    index = next(iter(streams.values())).index
    m_ = pd.Series(False, index=index)
    for x, y in train_ranges:
        m_.iloc[x:y] = True
    assign2 = {}
    for cell, mask in cells.items():
        row = {}
        for k, r in streams.items():
            if k == "CASH":
                continue
            s = rh.in_cell_stats(r, mask.fillna(False) & m_)
            if s:
                row[k] = s
        okd = sorted(((k, v) for k, v in row.items() if v["dd_mo"] <= 10.0),
                     key=lambda kv: kv[1]["monthly"], reverse=True)
        if len(okd) >= 2:
            assign2[cell] = (okd[0][0], okd[1][0])
        elif len(okd) == 1:
            assign2[cell] = (okd[0][0], okd[0][0])
        else:
            assign2[cell] = ("CASH", "CASH")
    return assign2


MENU_EXTRA = {}


def build_full(px):
    """Menu weight matrices incl. static combos; streams incl. combos."""
    rh.MENU = rh.menu_builders()
    ws = {k: b(px) for k, b in rh.MENU.items()}
    ws["COMBO_A_GF"] = 0.5 * ws["ABS_GROT"] + 0.5 * ws["FVG_LS"]
    ws["COMBO_A_G"] = 0.5 * ws["ABS_GROT"] + 0.5 * ws["GROT"]
    ret = px.pct_change().shift(-1)
    streams = {}
    for k, w in ws.items():
        w = w.fillna(0.0).reindex(px.index).fillna(0.0)
        gross = w.abs().sum(axis=1)
        scale = np.where(gross > 2.0, 2.0 / gross.replace(0, np.nan), 1.0)
        w = w.mul(pd.Series(scale, index=w.index), axis=0)
        dw = w.diff().abs()
        streams[k] = (w.mul(ret) - dw * sh.FEE).sum(axis=1).fillna(0.0)
    return ws, streams


def build_win(px, a, b_):
    p_win = px.iloc[max(0, a - 250):b_]
    rh.MENU = rh.menu_builders()
    ws = {k: b(p_win) for k, b in rh.MENU.items()}
    ws["COMBO_A_GF"] = 0.5 * ws["ABS_GROT"] + 0.5 * ws["FVG_LS"]
    ws["COMBO_A_G"] = 0.5 * ws["ABS_GROT"] + 0.5 * ws["GROT"]
    return ws


class Cfg:
    def __init__(self, name, kind, cells=None, sm=0, sm_on=0, sm_off=0, parts=None):
        self.name, self.kind, self.cells = name, kind, cells
        self.sm, self.sm_on, self.sm_off = sm, sm_on, sm_off
        self.parts = parts  # for ensembles: [(cells, sm), ...]


def learn_parts(cfg, streams, train_ranges):
    """Learn whatever mapping structure a config needs, on training bars only."""
    if cfg.kind in ("single", "asym", "ens"):
        if cfg.kind == "ens":
            return [learn_assign_local(streams, c, train_ranges) for c, _ in cfg.parts]
        return learn_assign_local(streams, cfg.cells, train_ranges)
    if cfg.kind == "top2":
        return learn_assign2(streams, cfg.cells, train_ranges)
    return None  # static


def apply_parts(cfg, ws, learned, index, columns):
    """Composite weights from precomputed ws + a pre-learned mapping (no re-learning)."""
    if cfg.kind == "single":
        lab = ra2.labels_from_cells(cfg.cells, index)
        lab_s = ra2.persist(lab, cfg.sm) if cfg.sm > 0 else lab
        return ra2.fast_composite(ws, lab_s, learned, index, columns)
    if cfg.kind == "asym":
        lab = ra2.labels_from_cells(cfg.cells, index)
        return ra2.fast_composite(ws, persist_asym(lab, cfg.sm_on, cfg.sm_off), learned,
                                  index, columns)
    if cfg.kind == "top2":
        lab = ra2.labels_from_cells(cfg.cells, index)
        lab_s = ra2.persist(lab, cfg.sm) if cfg.sm > 0 else lab
        return blend_composite(ws, lab_s, learned, index, columns)
    if cfg.kind == "static":
        return ws[cfg.name].reindex(index).fillna(0.0)
    if cfg.kind == "ens":
        w = pd.DataFrame(0.0, index=index, columns=columns)
        for (cells_p, sm_p), asg in zip(cfg.parts, learned):
            lab = ra2.labels_from_cells(cells_p, index)
            lab_s = ra2.persist(lab, sm_p) if sm_p > 0 else lab
            w += ra2.fast_composite(ws, lab_s, asg, index, columns)
        return w / len(cfg.parts)
    raise ValueError(cfg.kind)


def comp_w(cfg, ws, streams, train_ranges, index, columns, learned=None):
    """Composite weights: mapping learned on train_ranges (or given), applied on index."""
    if learned is None:
        learned = learn_parts(cfg, streams, train_ranges)
    return apply_parts(cfg, ws, learned, index, columns)


def learn_assign_local(streams, cells, train_ranges):
    """{cell: argmax in-cell monthly on training bars}, dd/Mo<=10, else CASH.
    Training mask built on the FULL-PERIOD stream index (EXP-031 semantics)."""
    index = next(iter(streams.values())).index
    m_ = pd.Series(False, index=index)
    for x, y in train_ranges:
        m_.iloc[x:y] = True
    assign = {}
    for cell, mask in cells.items():
        row = {}
        for k, r in streams.items():
            if k == "CASH":
                continue
            s = rh.in_cell_stats(r, mask.fillna(False) & m_)
            if s:
                row[k] = s
        okd = {k: v for k, v in row.items() if v["dd_mo"] <= 10.0}
        assign[cell] = max(okd.items(), key=lambda kv: kv[1]["monthly"])[0] if okd else "CASH"
    return assign


def block_eval(px_block, w):
    eq, r = sh.portfolio_sim(w, px_block, fee=sh.FEE)
    return sh.metrics(eq, r)


def scan_eval(cfg, ws_full, streams, px, ws_win, dbounds):
    """Full period + strict-LOFO (mapping learned on 2 blocks) + frozen blocks
    (full-period-learned mapping applied per block - the deployable-policy view)."""
    n = len(px)
    learned_full = learn_parts(cfg, streams, [(0, n)])
    w = comp_w(cfg, ws_full, streams, [(0, n)], px.index, px.columns, learned=learned_full)
    full = block_eval(px, w)["monthly_roi"]
    hold, frozen = [], []
    for held in (1, 2, 3):
        train = [k for k in (1, 2, 3) if k != held]
        a, b_ = dbounds[held - 1]
        wi = max(0, a - 250)
        idx_w = px.iloc[wi:b_].index
        idx_b = px.iloc[a:b_].index
        wh = comp_w(cfg, ws_win[held], streams, [dbounds[k - 1] for k in train],
                    idx_w, px.columns).reindex(idx_b).fillna(0.0)
        hold.append(block_eval(px.iloc[a:b_], wh)["monthly_roi"])
        wf = comp_w(cfg, ws_win[held], streams, [(0, n)], idx_w, px.columns,
                    learned=learned_full).reindex(idx_b).fillna(0.0)
        frozen.append(block_eval(px.iloc[a:b_], wf)["monthly_roi"])
    return full, hold, frozen


def placebo_for(cfg, ws_full, streams, px, ws_win, dbounds, champ_avg, n_draws=30):
    """Block-shuffled label draws (partition-preserving) through the identical protocol."""
    if cfg.kind == "static":
        return {"note": "static policy - no states to shuffle; placebo N/A"}
    draws = []
    for d in range(n_draws):
        rng = np.random.default_rng(3000 + d)

        def shuf_cells(cells):
            raw = ra2.labels_from_cells(cells, px.index)   # one label series (partition intact)
            block = 30
            nblk = int(np.ceil(len(raw) / block))
            perm = rng.permutation(nblk)
            shuf = pd.Series(np.concatenate(
                [raw.iloc[bi * block:(bi + 1) * block].values for bi in perm])[:len(raw)],
                index=px.index)
            return {cell: (shuf == cell) for cell in cells}

        cfg_s = Cfg(cfg.name + "_shuf", cfg.kind, sm=cfg.sm,
                    sm_on=cfg.sm_on, sm_off=cfg.sm_off)
        if cfg.kind in ("single", "asym", "top2"):
            cfg_s.cells = shuf_cells(cfg.cells)
        else:  # ensembles: shuffle each part's labels
            cfg_s.parts = [(shuf_cells(c), sm_p) for c, sm_p in cfg.parts]
        _full, hold, _frozen = scan_eval(cfg_s, ws_full, streams, px, ws_win, dbounds)
        draws.append(round(float(np.mean(hold)), 2))
    avgs = np.array(draws)
    return {"champion_avg": round(champ_avg, 2), "null_mean": round(float(avgs.mean()), 2),
            "null_p90": round(float(np.quantile(avgs, 0.9)), 2),
            "null_max": round(float(avgs.max()), 2),
            "champion_percentile": round(float((avgs < champ_avg).mean()) * 100.0, 1),
            "draws_beating": int((avgs >= champ_avg).sum()), "n_draws": n_draws}


def static_pair_placebo(ws_full, ws_win, px, dbounds, name):
    """Null for a static 50/50 pair: all 45 unordered menu pairs' block performance.
    Is (a,b) the best blend or one lucky draw from the pair space?"""
    keys = [k for k in ws_full if k not in ("CASH",) and not k.startswith("COMBO_")]
    n = len(px)
    rowsp = []
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            w = 0.5 * ws_full[a] + 0.5 * ws_full[b]
            _eq, r = sh.portfolio_sim(w, px, fee=sh.FEE)
            full_m = sh.metrics(_eq, r)["monthly_roi"]
            blocks = []
            for held in (1, 2, 3):
                aa, bb = dbounds[held - 1]
                wi = max(0, aa - 250)
                ww = 0.5 * ws_win[held][a] + 0.5 * ws_win[held][b]
                ww = ww.reindex(px.iloc[aa:bb].index).fillna(0.0)
                blocks.append(block_eval(px.iloc[aa:bb], ww)["monthly_roi"])
            rowsp.append({"pair": f"{a}+{b}", "full": full_m,
                          "min_block": min(blocks), "avg_block": float(np.mean(blocks))})
    ta, tb = {"COMBO_A_GF": ("ABS_GROT", "FVG_LS"),
              "COMBO_A_G": ("ABS_GROT", "GROT")}.get(name, (keys[0], keys[1]))
    tgt = f"{ta}+{tb}"
    this = next((r for r in rowsp if r["pair"] == tgt or r["pair"] == f"{tb}+{ta}"),
                rowsp[0])
    mins = np.array([r["min_block"] for r in rowsp])
    return {"note": f"static pair null over {len(rowsp)} menu pairs (this = {this['pair']})",
            "this_pair": this["pair"], "this_min": round(this["min_block"], 2),
            "this_avg": round(this["avg_block"], 2), "this_full": this["full"],
            "n_pairs": len(rowsp),
            "pair_p90": round(float(np.quantile(mins, 0.9)), 2),
            "pair_max": round(float(mins.max()), 2),
            "pair_percentile": round(float((mins < this["min_block"]).mean()) * 100.0, 1),
            "pairs_beating": int((mins >= this["min_block"]).sum()),
            "best_pairs": sorted(rowsp, key=lambda r: r["min_block"], reverse=True)[:5]}


def main():
    px = ra.load_all()
    rh.MENU = rh.menu_builders()
    defs_old = rh.regime_defs(px)
    defs_new = new_defs(px)
    n = len(px)
    dbounds = [(0, int(n * 0.38)), (int(n * 0.38), int(n * 0.70)), (int(n * 0.70), n)]

    # partition asserts (EXP-030 lesson)
    bad = []
    for fam, cells in {**{k: defs_old[k] for k in ("P3_hyst100", "P6_trend_x_stress")},
                       **defs_new}.items():
        tot = pd.Series(False, index=px.index)
        for m in cells.values():
            tot = tot | m.fillna(False)
        if float(tot.mean()) < 0.999:
            bad.append((fam, float(tot.mean())))
    assert not bad, f"partition incomplete: {bad}"
    print(f"partition check: all families 100% coverage ({len(defs_new)} new + baselines)")

    print("Computing menu + combo weight matrices and streams...")
    ws_full, streams = build_full(px)
    ws_win = {h: build_win(px, a, b_) for h, (a, b_) in enumerate(dbounds, start=1)}
    n2 = ra2.n2_cells(px)

    # ---------------- config registry (pre-registered) ----------------
    cfgs = [
        Cfg("P3_s10", "single", cells=defs_old["P3_hyst100"], sm=10),
        Cfg("P3_s0", "single", cells=defs_old["P3_hyst100"], sm=0),
        Cfg("N2_s10", "single", cells=n2, sm=10),
        Cfg("N2_s0", "single", cells=n2, sm=0),
        Cfg("P6_s10", "single", cells=defs_old["P6_trend_x_stress"], sm=10),
        Cfg("P6_s0", "single", cells=defs_old["P6_trend_x_stress"], sm=0),
    ]
    for fam, cells in defs_new.items():
        cfgs.append(Cfg(fam + "_s10", "single", cells=cells, sm=10))
        cfgs.append(Cfg(fam + "_s0", "single", cells=cells, sm=0))
    cfgs.append(Cfg("P3_asym_onfast", "asym", cells=defs_old["P3_hyst100"], sm_on=3, sm_off=20))
    cfgs.append(Cfg("P3_asym_offfast", "asym", cells=defs_old["P3_hyst100"], sm_on=20, sm_off=3))
    for fam, cells in [("P3_hyst100", defs_old["P3_hyst100"]),
                       ("H3_hyst_x_stress", defs_new["H3_hyst_x_stress"]),
                       ("H5_slope_x_trend", defs_new["H5_slope_x_trend"]),
                       ("H6_dd_state", defs_new["H6_dd_state"]),
                       ("P6_trend_x_stress", defs_old["P6_trend_x_stress"]),
                       ("N2", n2)]:
        cfgs.append(Cfg(fam + "_top2", "top2", cells=cells, sm=10))
    cfgs.append(Cfg("COMBO_A_GF", "static"))
    cfgs.append(Cfg("COMBO_A_G", "static"))
    cfgs.append(Cfg("ENS_P3_P6", "ens",
                    parts=[(defs_old["P3_hyst100"], 10), (defs_old["P6_trend_x_stress"], 10)]))
    cfgs.append(Cfg("ENS_P3_N2", "ens", parts=[(defs_old["P3_hyst100"], 10), (n2, 10)]))
    cfgs.append(Cfg("ENS_P3_H3", "ens",
                    parts=[(defs_old["P3_hyst100"], 10), (defs_new["H3_hyst_x_stress"], 10)]))

    # ---------------- scan ----------------
    print("\n" + "=" * 118)
    print(f"SCAN: {len(cfgs)} pre-registered configs - full period + strict LOFO (real data)")
    print("=" * 118)
    rows = []
    for cfg in cfgs:
        full, hold, frozen = scan_eval(cfg, ws_full, streams, px, ws_win, dbounds)
        allpos = all(h > 0 for h in hold)
        rows.append({"name": cfg.name, "kind": cfg.kind, "full": round(full, 2),
                     "lofo": [round(h, 2) for h in hold],
                     "frozen": [round(h, 2) for h in frozen],
                     "min_hold": round(min(hold), 2), "min_frozen": round(min(frozen), 2),
                     "allpos": bool(allpos), "_cfg": cfg})
        print(f"  {cfg.name:<18} full {full:+7.2f}%/mo  LOFO {hold[0]:+7.2f}/{hold[1]:+6.2f}/"
              f"{hold[2]:+6.2f}  frozen {frozen[0]:+6.2f}/{frozen[1]:+6.2f}/{frozen[2]:+6.2f} "
              f"{'ALL+' if allpos else ''}")

    rows_sorted = sorted(rows, key=lambda r: r["min_hold"], reverse=True)
    inc = next(r for r in rows if r["name"] == "P3_s10")
    print(f"\n  incumbent P3_s10: min-holdout {inc['min_hold']:+.2f}, avg "
          f"{np.mean(inc['lofo']):+.2f}")
    print("  top-5 by min-LOFO-holdout:")
    for r in rows_sorted[:5]:
        print(f"    {r['name']:<18} min {r['min_hold']:+6.2f}  avg {np.mean(r['lofo']):+6.2f} "
              f"full {r['full']:+6.2f}")

    # ---------------- nested LOFO of the whole search ----------------
    print("\n" + "=" * 118)
    print("NESTED LOFO: re-run the whole search on 2 training blocks only -> held block")
    print("=" * 118)
    nested_cands = [r for r in rows if r["kind"] in ("single", "asym", "top2", "ens")
                    and r["name"] != "COMBO_A_GF" and r["name"] != "COMBO_A_G"]
    nested_rows = []
    for held in (1, 2, 3):
        train = [k for k in (1, 2, 3) if k != held]
        tr_ranges = [dbounds[k - 1] for k in train]
        scores = []
        for r in nested_cands:
            cfg = r["_cfg"]
            tr_ms = []
            for t_ in train:
                a, b_ = dbounds[t_ - 1]
                wi = max(0, a - 250)
                wt = comp_w(cfg, ws_win[t_], streams, tr_ranges,
                            px.iloc[wi:b_].index, px.columns).reindex(
                    px.iloc[a:b_].index).fillna(0.0)
                tr_ms.append(block_eval(px.iloc[a:b_], wt)["monthly_roi"])
            scores.append((cfg, min(tr_ms)))
        best = max(scores, key=lambda kv: kv[1])
        cfg, wtr = best
        a, b_ = dbounds[held - 1]
        wi = max(0, a - 250)
        wh = comp_w(cfg, ws_win[held], streams, tr_ranges,
                    px.iloc[wi:b_].index, px.columns).reindex(
            px.iloc[a:b_].index).fillna(0.0)
        mh = block_eval(px.iloc[a:b_], wh)["monthly_roi"]
        nested_rows.append({"held": held, "chosen": cfg.name, "train_worst": round(wtr, 2),
                            "holdout_monthly": round(mh, 2)})
        print(f"  held B{held}: chose {cfg.name} (train worst {wtr:+.2f}) -> HELD {mh:+.2f}%/mo")
    nested_allpos = all(r["holdout_monthly"] > 0 for r in nested_rows)
    nested_avg = float(np.mean([r["holdout_monthly"] for r in nested_rows]))
    print(f"  nested avg {nested_avg:+.2f}, all-positive: {nested_allpos}")

    # ---------------- finalists: dyn_score + placebo ----------------
    print("\n" + "=" * 118)
    print("FINALISTS: full fold_metrics dyn_score + placebo null (30 draws)")
    print("=" * 118)
    finalists = []
    for r in rows_sorted[:3]:
        if r["name"] not in [f["name"] for f in finalists]:
            finalists.append(r)
    if inc not in finalists:
        finalists.append(inc)
    fin_out = []
    for r in finalists:
        cfg = r["_cfg"]
        learned_full = learn_parts(cfg, streams, [(0, n)])

        def builder(p, c=cfg, lf=learned_full):
            ws = build_win_ws(p)
            return apply_parts(c, ws, lf, p.index, p.columns)

        fm = sh.fold_metrics(builder, px, fee=sh.FEE)
        m = sh4.dyn_score(fm)
        avg = float(np.mean(r["lofo"]))
        if cfg.kind == "static":
            placebo = static_pair_placebo(ws_full, ws_win, px, dbounds, cfg.name)
        else:
            placebo = placebo_for(cfg, ws_full, streams, px, ws_win, dbounds, avg)
        fin_out.append({"name": r["name"], "full_dyn": {k: m[k] for k in
                        ("monthly_roi", "max_dd", "calmar", "folds", "worst_fold",
                         "bull_share", "dyn_ok")},
                        "lofo": r["lofo"], "frozen": r["frozen"], "placebo": placebo})
        print(f"  {r['name']:<18} dyn {m['monthly_roi']:+7.2f}%/mo DD {m['max_dd']:5.1f} "
              f"Cal {m['calmar']:5.2f} folds {m['folds'][0]:+6.2f}/{m['folds'][1]:+6.2f}/"
              f"{m['folds'][2]:+6.2f} dyn_ok={m['dyn_ok']}")
        if "champion_percentile" in placebo:
            print(f"    placebo: champ avg {placebo['champion_avg']:+.2f} vs null "
                  f"{placebo['null_mean']:+.2f} (p90 {placebo['null_p90']:+.2f}) -> "
                  f"pct {placebo['champion_percentile']:.0f}, {placebo['draws_beating']}/30 beat")
        else:
            print(f"    {placebo.get('note', placebo)}")
            if "pair_percentile" in placebo:
                print(f"    pair-null: {placebo['n_pairs']} menu pairs, this pair min-block "
                      f"{placebo['this_min']:+.2f} vs pair-null p90 {placebo['pair_p90']:+.2f} "
                      f"-> pct {placebo['pair_percentile']:.0f}, "
                      f"{placebo['pairs_beating']}/{placebo['n_pairs']} beat")

    # ---------------- verdict ----------------
    inc_avg = float(np.mean(inc["lofo"]))
    challengers = [f for f in fin_out if f["name"] != "P3_s10"]
    winner = None
    for f in challengers:
        pctl = f["placebo"].get("champion_percentile", f["placebo"].get("pair_percentile", 0))
        if (min(f["lofo"]) > inc["min_hold"] and pctl >= 90 and nested_allpos):
            winner = f
            break
    verdict = {
        "configs_tested": len(cfgs),
        "incumbent_min_hold": inc["min_hold"], "incumbent_avg": round(inc_avg, 2),
        "incumbent_min_frozen": inc["min_frozen"], "incumbent_frozen": inc["frozen"],
        "best_challenger": rows_sorted[0]["name"] if rows_sorted[0]["name"] != "P3_s10" else None,
        "best_challenger_min_hold": rows_sorted[0]["min_hold"] if rows_sorted[0]["name"] != "P3_s10" else None,
        "best_challenger_frozen": rows_sorted[0]["frozen"] if rows_sorted[0]["name"] != "P3_s10" else None,
        "nested_all_positive": bool(nested_allpos), "nested_avg": round(nested_avg, 2),
        "replacement": winner["name"] if winner else None,
        "final": winner["name"] if winner else "P3_s10 (incumbent stands)",
    }
    print("\nVERDICT:", json.dumps(verdict))

    # ---------------- save ----------------
    path = "reports/strategy_leaderboard.json"
    lb = json.load(open(path))
    lb["exp033_expansion"] = {
        "scan": [{k: v for k, v in r.items() if k != "_cfg"} for r in rows],
        "nested_lofo": {"rows": nested_rows, "all_positive": bool(nested_allpos),
                        "avg": round(nested_avg, 2)},
        "finalists": fin_out,
        "verdict": verdict,
    }
    json.dump(lb, open(path, "w"), indent=2)
    print("\nSaved exp033_expansion to reports/strategy_leaderboard.json")


def build_win_ws(p):
    rh.MENU = rh.menu_builders()
    ws = {k: b(p) for k, b in rh.MENU.items()}
    ws["COMBO_A_GF"] = 0.5 * ws["ABS_GROT"] + 0.5 * ws["FVG_LS"]
    ws["COMBO_A_G"] = 0.5 * ws["ABS_GROT"] + 0.5 * ws["GROT"]
    return ws


def streams_all(p):
    ret = p.pct_change().shift(-1)
    out = {}
    for k, w in build_win_ws(p).items():
        w = w.fillna(0.0).reindex(p.index).fillna(0.0)
        gross = w.abs().sum(axis=1)
        scale = np.where(gross > 2.0, 2.0 / gross.replace(0, np.nan), 1.0)
        w = w.mul(pd.Series(scale, index=w.index), axis=0)
        dw = w.diff().abs()
        out[k] = (w.mul(ret) - dw * sh.FEE).sum(axis=1).fillna(0.0)
    return out


if __name__ == "__main__":
    main()
