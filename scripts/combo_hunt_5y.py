"""EXP-040 (2026-10-30): COMBINATION HUNT on the 5-year panel (2021-01 -> 2026-07).

User directive: "one strategy cannot work for all the period... test on 5 years data
and check which combination will work? share ROI performance of each combination."

PRE-REGISTERED DESIGN (fixed before running):
Phase A - STATIC combinations (no fitting -> per-year numbers fully honest):
  singles (11 engines), all pairs of {ABS_GROT, GROT, COMBO_A_G, COMBO_A_GF, VOL_GROT,
  DIP_V2, FVG_LS, FVG_SHORT}, core triples/sets (survivor+hedger family), the no-TSMOM
  equal-weight portfolio, the kitchen-sink (with TSMOM) reference, BTC_hold, and 3
  pre-registered P3-timing variants of the survivor set.
Phase B - STATE-DRIVEN combinations (the regime lens; LEAVE-ONE-YEAR-OUT):
  actions = {eq4(GROT,ABS_GROT,VOL_GROT,DIP_V2), eq3(GROT,ABS_GROT,VOL_GROT), GROT,
  ABS_GROT, VOL_GROT, DIP_V2, FVG_SHORT, FVG_LS, BTC_hold, CASH}
  states  = P3, CORR30, VOL50, STRESS80, DISP60, TREND3, ATHDD10, H4
  configs = 8 families x sm{0,5,10} single-mode = 24
  For each held-out YEAR: per-cell argmax among actions (in-cell monthly on the OTHER
  years, dd/Mo<=10 filter, non-idle fallback = best non-CASH), apply to held-out year.
  -> every year is out-of-sample; the assembled "LOYO %/mo" is fully OOS.

SELECTION RULE (pre-registered): rank by MIN-YEAR monthly (worst period) subject to
  every year >= -0.5%/mo AND maxDD <= 35% AND full monthly >= +1.5%. Report ALL rows.

PLACEBOS for the winner: 30 block-shuffled label draws (full LOYO protocol) + 4-draw
search-level null over the 24-config search (coarse, flagged). Anything not clearing
the nulls = "works on paper" at most.
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
import five_year_test as ft

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOARD = os.path.join(BASE, "reports", "strategy_leaderboard.json")
LEDGER = os.path.join(BASE, "reports", "roi_progress_ledger.json")
SPLIT = pd.Timestamp("2023-04-15")
YEARS = [2021, 2022, 2023, 2024, 2025, 2026]


# ---------------------------------------------------------------- helpers
def eq_monthlies(eq):
    m = eq.resample("ME").last().pct_change().dropna()
    out = {}
    for y, g in m.groupby(m.index.year):
        out[int(y)] = float(((1 + g).prod() ** (1.0 / max(len(g), 1)) - 1) * 100)
    return out


def metrics_of(w, px):
    eq, r = sh.portfolio_sim(w, px, fee=sh.FEE)
    m = sh.metrics(eq, r)
    ym = eq_monthlies(eq)
    return {
        "full": m["monthly_roi"], "dd": m["max_dd"], "worst_m": m["worst_month"],
        "yearly": {str(y): round(v, 2) for y, v in ym.items()},
        "min_year": round(min(ym.values()), 2) if ym else None,
    }, eq


def mix(ws, names, px):
    w = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    for k in names:
        w = w + ws[k].reindex(px.index).fillna(0.0)
    return w / len(names)


def main():
    px = ft.load_all_5y()
    rh.MENU = rh.menu_builders()
    n = len(px)
    ws, streams = rx.build_full(px)
    fams = nr.fam_registry(px)
    newd = rx.new_defs(px)
    p3c, c30, h4c = fams["H100b2"], fams["CORR30"], newd["H4_hyst_x_breadth"]
    year_of = pd.Series(px.index.year, index=px.index)

    # ------------------------------------------------------------ Phase A
    print("=" * 118)
    print("EXP-040 PHASE A: STATIC COMBINATIONS (no fitting - honest per-year)")
    print("=" * 118)
    rowsA = {}
    def rec(name, w):
        m, _eq = metrics_of(w, px)
        rowsA[name] = m
        ys = " ".join(f"{y[2:]}:{v:+5.1f}" for y, v in m["yearly"].items())
        print(f"  {name:<30} full {m['full']:+6.2f}%/mo DD {m['dd']:5.1f} "
              f"minYr {m['min_year']:+5.1f} | {ys}")

    core = ["ABS_GROT", "GROT", "COMBO_A_G", "COMBO_A_GF", "VOL_GROT", "DIP_V2",
            "FVG_LS", "FVG_SHORT"]
    for k in ["ABS_GROT", "GROT", "COMBO_A_G", "COMBO_A_GF", "VOL_GROT", "DIP_V2",
              "FVG_LS", "FVG_LONG", "FVG_SHORT", "TSMOM"]:
        rec(k, ws[k])
    wb = pd.DataFrame(0.0, index=px.index, columns=px.columns); wb["BTC"] = 1.0
    rec("BTC_hold", wb)
    for i, a in enumerate(core):
        for b in core[i + 1:]:
            rec(f"pair_{a}+{b}", mix(ws, [a, b], px))
    rec("eq3_GROT_ABS_VOL", mix(ws, ["GROT", "ABS_GROT", "VOL_GROT"], px))
    rec("eq4_survivors(+DIP)", mix(ws, ["GROT", "ABS_GROT", "VOL_GROT", "DIP_V2"], px))
    rec("eq5_survivors+SHORT", mix(ws, ["GROT", "ABS_GROT", "VOL_GROT", "DIP_V2", "FVG_SHORT"], px))
    rec("eq4+FVG_LS", mix(ws, ["GROT", "ABS_GROT", "VOL_GROT", "FVG_LS"], px))
    rec("noTSMOM_equal9", mix(ws, [k for k in ws if k != "TSMOM"], px))
    rec("kitchen_sink_all", mix(ws, list(ws.keys()), px))
    # pre-registered P3 timing variants of eq4
    hy = sh4_hyst = None
    import strategy_hunt4 as sh4
    hy = sh4.hyst_state(px, 100, 0.02)
    on = ra2.persist(pd.Series(np.where(hy > 0.5, "ON", "OFF"), index=px.index), 10)
    eq4 = mix(ws, ["GROT", "ABS_GROT", "VOL_GROT", "DIP_V2"], px)
    w_t1 = eq4.copy()
    w_t1[on == "OFF"] = 0.5 * eq4[on == "OFF"]
    rec("eq4_P3timing_half", w_t1)
    w_t2 = eq4.copy()
    w_t2[on == "OFF"] = ws["FVG_SHORT"].reindex(px.index).fillna(0.0)[on == "OFF"]
    rec("eq4_P3timing_SHORT", w_t2)
    w_t3 = eq4.copy()
    w_t3[on == "OFF"] = 0.0
    rec("eq4_P3timing_OFF", w_t3)

    # ------------------------------------------------------------ Phase B
    print("\n" + "=" * 118)
    print("PHASE B: STATE-DRIVEN COMBINATIONS (leave-one-year-out, fully OOS)")
    print("=" * 118)
    actions = {
        "eq4": eq4,
        "eq3": mix(ws, ["GROT", "ABS_GROT", "VOL_GROT"], px),
        "GROT": ws["GROT"].reindex(px.index).fillna(0.0),
        "ABS_GROT": ws["ABS_GROT"].reindex(px.index).fillna(0.0),
        "VOL_GROT": ws["VOL_GROT"].reindex(px.index).fillna(0.0),
        "DIP_V2": ws["DIP_V2"].reindex(px.index).fillna(0.0),
        "FVG_SHORT": ws["FVG_SHORT"].reindex(px.index).fillna(0.0),
        "FVG_LS": ws["FVG_LS"].reindex(px.index).fillna(0.0),
        "BTC_hold": wb,
        "CASH": pd.DataFrame(0.0, index=px.index, columns=px.columns),
    }
    arets = {}
    for a, w in actions.items():
        _eq, r = sh.portfolio_sim(w, px, fee=sh.FEE)
        arets[a] = r.fillna(0.0)

    fam_map = {"P3": p3c, "CORR30": c30, "VOL50": fams["VOL50"], "STRESS80": fams["STRESS80"],
               "DISP60": fams["DISP60"], "TREND3": fams["TREND3"], "ATHDD10": fams["ATHDD10"],
               "H4": h4c}

    def loyo_eval(cells, sm):
        """Per-cell argmax learned on all-but-one year, applied to held-out year."""
        lab = ra2.persist(ra2.labels_from_cells(cells, px.index), sm) if sm > 0 \
            else ra2.labels_from_cells(cells, px.index)
        yearlies, assign_log = {}, {}
        w_full = pd.DataFrame(0.0, index=px.index, columns=px.columns)
        for y in YEARS:
            te = (year_of == y)
            if te.sum() == 0:
                continue
            tr = (year_of != y)
            assign = {}
            for cell, mask in cells.items():
                m_ = mask.fillna(False) & tr
                if m_.sum() < 30:
                    assign[cell] = "eq4"
                    continue
                stats = {a: rh.in_cell_stats(arets[a], m_) for a in actions}
                stats = {a: s for a, s in stats.items() if s}
                okd = sorted(((k, v) for k, v in stats.items()
                              if v["dd_mo"] <= 10.0 and k != "CASH"),
                             key=lambda kv: kv[1]["monthly"], reverse=True)
                if not okd:
                    okd = sorted(((k, v) for k, v in stats.items() if k != "CASH"),
                                 key=lambda kv: kv[1]["dd_mo"])[:1]
                assign[cell] = okd[0][0] if okd else "eq4"
            w = pd.DataFrame(0.0, index=px.index, columns=px.columns)
            for cell, a in assign.items():
                sel = (lab == cell)
                w[sel] = actions[a].reindex(px.index)[sel]
            w_full[te] = w[te]
            eq_y, r_y = sh.portfolio_sim(w[te], px[te], fee=sh.FEE)
            mm = eq_monthlies(eq_y)
            yearlies[y] = round(mm.get(y, list(mm.values())[0] if mm else 0.0), 2)
            assign_log[str(y)] = assign
        m, eq = metrics_of(w_full, px)
        m["loyo_yearly"] = yearlies
        m["min_year"] = round(min(yearlies.values()), 2) if yearlies else None
        m["assign"] = assign_log
        return m

    rowsB = []
    for fam, cells in fam_map.items():
        for sm in (0, 5, 10):
            m = loyo_eval(cells, sm)
            m.update({"fam": fam, "sm": sm, "name": f"{fam}_s{sm}"})
            rowsB.append(m)
            ys = " ".join(f"{str(y)[2:]}:{v:+5.1f}" for y, v in m["loyo_yearly"].items())
            print(f"  {m['name']:<14} LOYO {m['full']:+6.2f}%/mo DD {m['dd']:5.1f} "
                  f"minYr {m['min_year']:+5.1f} | {ys}")

    # ------------------------------------------------------------ selection
    okB = [r for r in rowsB if r["min_year"] is not None
           and r["min_year"] >= -0.5 and r["dd"] <= 35.0 and r["full"] >= 1.5]
    bestB = max(okB, key=lambda r: r["min_year"]) if okB else max(rowsB, key=lambda r: r["min_year"])
    okA = [r for r in rowsA.values() if r["min_year"] >= -0.5 and r["dd"] <= 35.0 and r["full"] >= 1.5]
    bestA = max(okA, key=lambda r: r["min_year"]) if okA else None
    print("\nSELECTION (rule: max min-year, all years >= -0.5, DD <= 35, full >= 1.5):")
    print(f"  best static : {bestA and [k for k, v in rowsA.items() if v is bestA]}")
    print(f"  best state  : {bestB['name']} minYr {bestB['min_year']:+.2f} "
          f"LOYO {bestB['full']:+.2f} DD {bestB['dd']}")

    # ------------------------------------------------------------ placebos
    print("\n" + "=" * 118)
    print(f"PLACEBOS for {bestB['name']} (30 label-shuffles + 4-draw search null)")
    print("=" * 118)
    def shuf_cells(cells, rng):
        raw = ra2.labels_from_cells(cells, px.index)
        block, nblk = 30, int(np.ceil(len(raw) / 30))
        perm = rng.permutation(nblk)
        shuf = pd.Series(np.concatenate(
            [raw.iloc[b * 30:(b + 1) * 30].values for b in perm])[:len(raw)], index=px.index)
        return {c: (shuf == c) for c in cells}
    nulls = []
    for d in range(30):
        rng = np.random.default_rng(9700 + d)
        m = loyo_eval(shuf_cells(fam_map[bestB["fam"]], rng), bestB["sm"])
        nulls.append(m["min_year"])
    nb = np.array(nulls)
    p90 = float(np.quantile(nb, 0.9))
    g_placebo = bestB["min_year"] >= p90
    print(f"  real minYr {bestB['min_year']:+.2f} vs null mean {nb.mean():+.2f} "
          f"p90 {p90:+.2f} -> pct {100 * (nb < bestB['min_year']).mean():.0f} "
          f"({int((nb >= bestB['min_year']).sum())}/30 beat) -> {'PASS' if g_placebo else 'FAIL'}")
    null_best = []
    for d in range(4):
        rng = np.random.default_rng(9800 + d)
        smap = {f: shuf_cells(c, rng) for f, c in fam_map.items()}
        best = max((loyo_eval(smap[f], sm) for f in fam_map for sm in (0, 5, 10)),
                   key=lambda m: m["min_year"])
        null_best.append(best["min_year"])
        print(f"  search-null draw {d}: best minYr {best['min_year']:+.2f}")
    ns = np.array(null_best)
    g_search = bestB["min_year"] >= float(ns.max())
    print(f"  search-null max {ns.max():+.2f} (coarse n=4) -> "
          f"{'PASS' if g_search else 'FAIL - treat as not selection-adjusted'}")

    verdict = {
        "best_static": {k: v for k, v in (bestA or {}).items()},
        "best_static_name": [k for k, v in rowsA.items() if v is bestA][0] if bestA else None,
        "best_state": {k: v for k, v in bestB.items() if k != "assign"},
        "best_state_assign": bestB["assign"],
        "placebo": {"real_min_year": bestB["min_year"], "null_mean": round(float(nb.mean()), 2),
                    "null_p90": round(p90, 2), "pct": round(100 * (nb < bestB["min_year"]).mean(), 0),
                    "pass": bool(g_placebo)},
        "search_null_coarse": {"n": 4, "max": round(float(ns.max()), 2),
                               "draws": [round(float(x), 2) for x in ns],
                               "pass": bool(g_search)},
    }

    board = json.load(open(BOARD))
    board["exp040_combos"] = {
        "date": "2026-10-30",
        "question": "which COMBINATION works in ALL periods? 5y panel 2021-2026",
        "static_combos": rowsA,
        "state_combos": [{k: v for k, v in r.items() if k != "assign"} for r in rowsB],
        "verdict": verdict,
    }
    json.dump(board, open(BOARD, "w"), indent=2)
    print("\nsaved exp040_combos")

    if os.environ.get("SKIP_LEDGER") != "1":
        led = json.load(open(LEDGER))
        led["experiments"].append({
            "id": "EXP-040-COMBO-HUNT-5Y",
            "date": "2026-10-30",
            "focus": "combination hunt on 5y panel ranked by worst-period (min-year): static "
                     "combos (no fitting) + state-driven LOYO combos + placebos",
            "outcome": "EXP-040-COMBOS",
        })
        json.dump(led, open(LEDGER, "w"), indent=2)
        print("ledger:", len(led["experiments"]))


if __name__ == "__main__":
    main()
