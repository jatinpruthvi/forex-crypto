"""EXP-037 (2026-10-30): META-SELECTOR over the top-5 strategies.

Question (user): "one strategy cannot work for all the period... is it possible with
combination of above 5 strategy based on some parameter we will apply based strategy
from top five, so we will have higher [growth] and our capital will not be [idle]."

Design: a causal META-STATE (parameter family) decides which of the top-5 deployable
policies is in command at each moment. Per-cell argmax among the 5 actions by in-cell
monthly (training bars only, dd/Mo<=10 filter, non-idle fallback = lowest-dd action),
optional persistence smoothing on the meta labels. Actions are switched, never cashed:
capital stays invested in one of the five at all times.

ACTIONS (the spec's top-5, full definitions):
  Blend3_75 = 0.75 x (1/3 Champion + 1/3 CORR30_s0 + 1/3 H4_s10)
  ENS_CxH4  = 1/2 CORR30_s0 + 1/2 H4_s10
  Champion_P3 = P3 hysteresis x sm10 {ABS_GROT | FVG_LS}
  ENS_CxP3  = 1/2 CORR30_s0 + 1/2 Champion
  CORR30_s0 = correlation state x sm0 {FVG_LONG | TSMOM}

META-STATE FAMILIES (pre-registered; 7 causal families, 16 cells):
  P3(2), CORR30(2), VOL50(2), STRESS80(2), DISP60(2), TREND3(3), ATHDD10(3)

SEARCH (pre-registered, 42 configs): family x sm{0,5,10} x mode{single, top2}.

PRE-REGISTERED VERDICT GATES (all must pass for CERTIFIED):
  G1  winner min strict-LOFO >= +7.82 (Blend3@75% incumbent min +5.94 + 1.88) AND all LOFO > 0
  G2  config placebo >= p90 (30 block-shuffled draws of the winner family)
  G3  selection-adjusted: real min-LOFO >= p90 of the meta-search null
      (8 full 42-config searches on block-shuffled meta labels)
  G4  non-idle: in-market share >= 95% (user constraint)
  G5  risk gate: report DD<=35 scaling; dyn fields (bull_share<0.8, nonbull avg>0)
Anything failing = SHADOW CANDIDATE at most. EXP-034 lesson: per-period best-of-N is
where selection artifacts live - gate G3 is make-or-break.
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
import regime_audit2 as ra2
import regime_expansion as rx
import nuclear_regime as nr

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOARD = os.path.join(BASE, "reports", "strategy_leaderboard.json")
LEDGER = os.path.join(BASE, "reports", "roi_progress_ledger.json")
DPM = 30.44

META_FAMS = ["H100b2", "CORR30", "VOL50", "STRESS80", "DISP60", "TREND3", "ATHDD10"]
SMS = (0, 5, 10)
MODES = ("single", "top2")


# ------------------------------------------------------------------ actions
def action_cfgs(p3c, c30, h4c):
    """Top-5 as complete deployable policies: (rx.Cfg, scale)."""
    return {
        "Blend3_75": (rx.Cfg("Blend3_75", "ens",
                             parts=[(p3c, 10), (c30, 0), (h4c, 10)]), 0.75),
        "ENS_CxH4": (rx.Cfg("ENS_CxH4", "ens",
                            parts=[(c30, 0), (h4c, 10)]), 1.0),
        "Champion_P3": (rx.Cfg("Champion_P3", "single", cells=p3c, sm=10), 1.0),
        "ENS_CxP3": (rx.Cfg("ENS_CxP3", "ens",
                            parts=[(c30, 0), (p3c, 10)]), 1.0),
        "CORR30_s0": (rx.Cfg("CORR30_s0", "single", cells=c30, sm=0), 1.0),
    }


def build_action_books(acts, ws, streams, train, px):
    """For one train set: {action: (weights over full index, daily return stream)}."""
    out = {}
    for name, (cfg, scale) in acts.items():
        w = rx.comp_w(cfg, ws, streams, train, px.index, px.columns) * scale
        _eq, r = sh.portfolio_sim(w, px, fee=sh.FEE)
        out[name] = (w, r.fillna(0.0))
    return out


# ------------------------------------------------------------------ meta
def meta_learn(cells, books, train_mask, mode):
    """Per-cell argmax among actions (in-cell monthly on train, dd/Mo<=10).
    Non-idle fallback: if no action passes the filter, take lowest dd_monthly."""
    index = train_mask.index
    labels = ra2.labels_from_cells(cells, index)
    assign = {}
    fallbacks = 0
    for cell in cells:
        mask = cells[cell].fillna(False) & train_mask
        if mask.sum() == 0:
            assign[cell] = ("CASH",) if mode == "single" else ("CASH", "CASH")
            continue
        stats = {}
        for a, (_w, r) in books.items():
            s = rh.in_cell_stats(r, mask)
            if s:
                stats[a] = s
        okd = sorted(((k, v) for k, v in stats.items() if v["dd_mo"] <= 10.0),
                     key=lambda kv: kv[1]["monthly"], reverse=True)
        if not okd and stats:
            okd = sorted(stats.items(), key=lambda kv: kv[1]["dd_mo"])[:1]
            fallbacks += 1
        if mode == "single":
            assign[cell] = (okd[0][0],) if okd else ("CASH",)
        else:
            if len(okd) >= 2:
                assign[cell] = (okd[0][0], okd[1][0])
            elif okd:
                assign[cell] = (okd[0][0], okd[0][0])
            else:
                assign[cell] = ("CASH", "CASH")
    return assign, fallbacks


def meta_weights(books, cells, sm, assign, mode, index, columns):
    lab = ra2.labels_from_cells(cells, index)
    lab_s = ra2.persist(lab, sm) if sm > 0 else lab
    w = pd.DataFrame(0.0, index=index, columns=columns)
    for cell, acts in assign.items():
        sel = (lab_s == cell)
        if not sel.any():
            continue
        if mode == "single":
            a = acts[0]
            if a != "CASH":
                w[sel] = books[a][0].reindex(index)[sel]
        else:
            acc = pd.DataFrame(0.0, index=index, columns=columns)
            for a in set(acts):
                if a != "CASH":
                    acc[sel] = acc[sel] + books[a][0].reindex(index)[sel]
            w[sel] = acc[sel] / len(acts)
    return w


def block_metrics(px_b, w):
    w = w.reindex(px_b.index).fillna(0.0)
    eq, r = sh.portfolio_sim(w, px_b, fee=sh.FEE)
    m = sh.metrics(eq, r)
    mret = eq.resample("ME").last().pct_change().dropna()
    m["_med"] = round(float(mret.median() * 100), 1) if len(mret) else 0.0
    m["_eq"] = eq
    return m


def eval_config(cells, sm, mode, books_all, px, dbounds, train_sets):
    """Full + strict-LOFO + frozen. books_all[train_key] = action books for that train."""
    n = len(px)
    index, cols = px.index, px.columns
    # full (deployable view): assignment + books learned on full
    assign, fb = meta_learn(cells, books_all["full"], pd.Series(True, index=index), mode)
    w_full = meta_weights(books_all["full"], cells, sm, assign, mode, index, cols)
    m_full = block_metrics(px, w_full)
    in_mkt = float((w_full.abs().sum(axis=1) > 0).mean() * 100)
    hold, frozen = [], []
    for held in (1, 2, 3):
        a, b_ = dbounds[held - 1]
        tk = f"tr{held}"
        mtr = pd.Series(False, index=index)
        for x, y in train_sets[tk]:
            mtr.iloc[x:y] = True
        asg_h, _ = meta_learn(cells, books_all[tk], mtr, mode)
        w_h = meta_weights(books_all[tk], cells, sm, asg_h, mode, index, cols)
        hold.append(round(block_metrics(px.iloc[a:b_], w_h)["monthly_roi"], 2))
        asg_f, _ = meta_learn(cells, books_all["full"], pd.Series(True, index=index), mode)
        w_f = meta_weights(books_all["full"], cells, sm, asg_f, mode, index, cols)
        frozen.append(round(block_metrics(px.iloc[a:b_], w_f)["monthly_roi"], 2))
    return {
        "full": round(m_full["monthly_roi"], 2),
        "dd": m_full["max_dd"],
        "calmar": m_full["calmar"],
        "med_m": m_full["_med"],
        "worst_m": m_full["worst_month"],
        "lofo": hold,
        "frozen": frozen,
        "min_hold": round(min(hold), 2),
        "avg_hold": round(float(np.mean(hold)), 2),
        "in_market_pct": round(in_mkt, 1),
        "fallbacks": fb,
        "assign_full": {k: list(v) for k, v in assign.items()},
    }


# ------------------------------------------------------------------ nulls
def shuf_cells(cells, rng, index):
    raw = ra2.labels_from_cells(cells, index)
    block = 30
    nblk = int(np.ceil(len(raw) / block))
    perm = rng.permutation(nblk)
    shuf = pd.Series(np.concatenate(
        [raw.iloc[bi * block:(bi + 1) * block].values for bi in perm])[:len(raw)],
        index=index)
    return {c: (shuf == c) for c in cells}


def search_over(fam_map, books_all, px, dbounds, train_sets, verbose=False):
    """The full 42-config search; returns rows + best by min_hold."""
    rows = []
    for fam, cells in fam_map.items():
        for sm in SMS:
            for mode in MODES:
                r = eval_config(cells, sm, mode, books_all, px, dbounds, train_sets)
                r.update({"fam": fam, "sm": sm, "mode": mode,
                          "name": f"{fam}_s{sm}_{mode}"})
                rows.append(r)
                if verbose:
                    print(f"    {r['name']:<22} full {r['full']:+7.2f} "
                          f"lofo {r['lofo']} min {r['min_hold']:+6.2f} "
                          f"dd {r['dd']:5.1f} inMkt {r['in_market_pct']:.0f}%")
    best = max(rows, key=lambda r: r["min_hold"])
    return rows, best


def main():
    px = ra.load_all()
    rh.MENU = rh.menu_builders()
    n = len(px)
    dbounds = [(0, int(n * 0.38)), (int(n * 0.38), int(n * 0.70)), (int(n * 0.70), n)]
    # train sets as lists of (start, end) ranges: held 1 -> blocks 2+3, etc.
    train_masks = {
        "full": [(0, n)],
        "tr1": [(dbounds[1][0], dbounds[2][1])],
        "tr2": [(dbounds[0][0], dbounds[0][1]), (dbounds[2][0], dbounds[2][1])],
        "tr3": [(dbounds[0][0], dbounds[1][1])],
    }
    ws_full, streams = rx.build_full(px)
    fams = nr.fam_registry(px)
    newd = rx.new_defs(px)
    p3c, c30, h4c = fams["H100b2"], fams["CORR30"], newd["H4_hyst_x_breadth"]
    acts = action_cfgs(p3c, c30, h4c)

    # books per train set (mapping learned on that train only)
    books_all = {}
    for key, ranges in train_masks.items():
        books_all[key] = build_action_books(acts, ws_full, streams, ranges, px)
    fam_map = {f: fams[f] for f in META_FAMS}

    print("=" * 118)
    print("EXP-037 META-SELECTOR over top-5: 7 pre-registered meta-state families x sm x mode = 42 configs")
    print("=" * 118)
    print("actions: " + ", ".join(acts))
    print("references (standalone actions, same protocol):")
    ref = {}
    for a in acts:
        r = eval_config({f"ONLY_{a}": pd.Series(True, index=px.index)}, 0, "single",
                        {"full": {a: books_all["full"][a]},
                         "tr1": {a: books_all["tr1"][a]},
                         "tr2": {a: books_all["tr2"][a]},
                         "tr3": {a: books_all["tr3"][a]}},
                        px, dbounds, train_masks)
        # NOTE: with one always-true cell the meta layer degenerates to the action itself
        ref[a] = r
        print(f"  {a:<12} full {r['full']:+7.2f} lofo {r['lofo']} min {r['min_hold']:+6.2f} "
              f"dd {r['dd']:5.1f}")

    print("\nMAIN SEARCH (42 configs):")
    rows, best = search_over(fam_map, books_all, px, dbounds, train_masks, verbose=True)
    print(f"\nBEST: {best['name']} full {best['full']:+.2f} lofo {best['lofo']} "
          f"min {best['min_hold']:+.2f} dd {best['dd']} inMkt {best['in_market_pct']}%")
    print(f"  mapping: {best['assign_full']}  fallbacks {best['fallbacks']}")

    # ---------------- config placebo (winner family, 30 draws) -------------
    print("\n" + "=" * 118)
    print("CONFIG PLACEBO (30 block-shuffled draws of the winner family)")
    print("=" * 118)
    champ_stat = best["avg_hold"]
    rng0 = np.random.default_rng(9000)
    null_cfg = []
    for d in range(30):
        rng = np.random.default_rng(9100 + d)
        cells_s = shuf_cells(fams[best["fam"]], rng, px.index)
        r = eval_config(cells_s, best["sm"], best["mode"], books_all, px, dbounds, train_masks)
        null_cfg.append(r["avg_hold"])
    ncfg = np.array(null_cfg)
    p90c = float(np.quantile(ncfg, 0.9))
    pct_c = float((ncfg < champ_stat).mean() * 100)
    g2 = champ_stat >= p90c
    print(f"  winner avg-LOFO {champ_stat:+.2f} vs null mean {ncfg.mean():+.2f} "
          f"p90 {p90c:+.2f} -> pct {pct_c:.0f} ({int((ncfg >= champ_stat).sum())}/30 beat) "
          f"-> G2 {'PASS' if g2 else 'FAIL'}")

    # ---------------- search-level placebo (8 full searches) ---------------
    print("\n" + "=" * 118)
    print("SEARCH-LEVEL PLACEBO: full 42-config search on shuffled meta labels, 8 draws")
    print("=" * 118)
    null_best = []
    for d in range(8):
        rng = np.random.default_rng(9300 + d)
        fam_map_s = {f: shuf_cells(fams[f], rng, px.index) for f in META_FAMS}
        _rs, b = search_over(fam_map_s, books_all, px, dbounds, train_masks)
        null_best.append(b["min_hold"])
        print(f"  draw {d}: best min-holdout {b['min_hold']:+6.2f} ({b['name']})")
    nb = np.array(null_best)
    p90s = float(np.quantile(nb, 0.9))
    pct_s = float((nb < best["min_hold"]).mean() * 100)
    g3 = best["min_hold"] >= p90s
    print(f"  real best min {best['min_hold']:+.2f} vs search-null mean {nb.mean():+.2f} "
          f"p90 {p90s:+.2f} max {nb.max():+.2f} -> pct {pct_s:.0f} "
          f"({int((nb >= best['min_hold']).sum())}/8 beat) -> G3 {'PASS' if g3 else 'FAIL'}")

    # ---------------- verdict + risk frontier ------------------------------
    inc_min = ref["Blend3_75"]["min_hold"]
    g1 = (best["min_hold"] >= inc_min + 1.88) and all(h > 0 for h in best["lofo"])
    g4 = best["in_market_pct"] >= 95.0
    frontier = []
    w_full_best = None
    assign, _ = meta_learn(fams[best["fam"]], books_all["full"],
                           pd.Series(True, index=px.index), best["mode"])
    w_full_best = meta_weights(books_all["full"], fams[best["fam"]], best["sm"],
                               assign, best["mode"], px.index, px.columns)
    for s in (0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
        m = block_metrics(px, w_full_best * s)
        frontier.append({"scale": s, "monthly": m["monthly_roi"], "dd": m["max_dd"],
                         "calmar": m["calmar"], "worst_m": m["worst_month"]})
        print(f"  frontier @{int(s*100)}%: {m['monthly_roi']:+7.2f}%/mo DD {m['max_dd']:5.1f} "
              f"Cal {m['calmar']:5.2f} worstM {m['worst_month']:+6.1f}"
              f"{'  <=35 FITS' if m['max_dd'] <= 35 else ''}")
    verdict = {
        "winner": best["name"], "winner_min_hold": best["min_hold"],
        "winner_avg_hold": best["avg_hold"], "winner_full": best["full"],
        "winner_lofo": best["lofo"], "winner_dd": best["dd"],
        "winner_in_market": best["in_market_pct"],
        "winner_assign": best["assign_full"],
        "incumbent_blend3_min": inc_min,
        "gates": {"g1_min_hold": bool(g1), "g2_placebo": bool(g2),
                  "g3_selection_adjusted": bool(g3), "g4_non_idle": bool(g4)},
        "config_placebo": {"champion_avg_lofo": champ_stat,
                           "null_mean": round(float(ncfg.mean()), 2),
                           "null_p90": round(p90c, 2), "pct": round(pct_c, 0)},
        "search_null": {"real": best["min_hold"], "null_mean": round(float(nb.mean()), 2),
                        "null_p90": round(p90s, 2), "null_max": round(float(nb.max()), 2),
                        "pct": round(pct_s, 0), "draws": [round(float(x), 2) for x in nb]},
        "certified": bool(g1 and g2 and g3 and g4),
        "risk_frontier": frontier,
    }
    print("\nVERDICT:", json.dumps(verdict["gates"]), "CERTIFIED:", verdict["certified"])

    board = json.load(open(BOARD))
    board["exp037_meta"] = {
        "date": "2026-10-30",
        "question": "meta-selector over top-5 by causal parameter state (non-idle)",
        "actions": list(acts), "meta_families": META_FAMS,
        "references": {a: {k: v for k, v in r.items() if k != "assign_full"}
                       for a, r in ref.items()},
        "configs": [{k: v for k, v in r.items() if k != "assign_full"} for r in rows],
        "verdict": verdict,
    }
    json.dump(board, open(BOARD, "w"), indent=2)
    print("saved exp037_meta")

    if os.environ.get("SKIP_LEDGER") != "1":
        led = json.load(open(LEDGER))
        led["experiments"].append({
            "id": "EXP-037-META-SELECTOR",
            "date": "2026-10-30",
            "focus": ("meta-selector over top-5 by causal meta-state (7 families x sm x mode = 42): "
                      "non-idle switching, config placebo + selection-adjusted search-null"),
            "outcome": "EXP-037-META",
        })
        json.dump(led, open(LEDGER, "w"), indent=2)
        print("ledger:", len(led["experiments"]))


if __name__ == "__main__":
    main()
