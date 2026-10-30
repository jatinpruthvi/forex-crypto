"""EXP-035 — NUCLEAR EXPLOSION regime hunt (BFS + DFS, >=100 nodes) for best-of-best.

User: "check with nuclear explosion method as well to hunt best of best."

Protocol (as in EXP-025/026/027): BFS breadth expansion + DFS depth exploitation,
>=100 validated nodes on REAL data (21-coin panel, real fees, honest walk-forward).

PRE-REGISTERED TREE:
  BFS (breadth, sm=10 default): systematic state-family parameter grid -
    T{w} trend windows w in {50,75,100,125,150,200};
    H{w}b{b} hysteresis w in {50,100,150,200} x band {1,2,3,5}%;
    VOL{q} vol-level quantile q in {50,60,70,80}; STRESS{q} q in {70,75,80,85,90};
    DISP{l} dispersion lookback l in {20,40,60,90}; CORR{l} pairwise-corr l in {20,30,60};
    BREADTH{h}{l} 4 threshold pairs; MOM{l} momentum sign l in {10,20,30,40,60};
    DUALMA{f}_{s} fast/slow crosses (50/150, 50/200, 100/200);
    TREND3 3-state hysteresis; ATHDD{d} drawdown depth d in {10,15};
    X crosses: trend100 x {VOL70, STRESS80, DISP60, CORR30, BREADTH, MOM30};
    HX crosses: champ-hyst x {VOL70, STRESS80, BREADTH, DISP60};
    X2 crosses: VOL70xMOM30, BREADTHxDISP60, STRESS80xCORR30.
  DFS (depth): top-6 BFS nodes by min-LOFO-holdout -> each expanded over
    sm {0,3,5,8,15} + top-2 blend variant.
  POLISH: winner x incumbent ensemble (w50) + winner x H4 ensemble (w50).
VERDICT GATES (pre-registered): a challenger is a CERTIFIED REPLACEMENT only if
  (1) min-strict-LOFO-holdout > incumbent's, (2) LOFO all-positive,
  (3) config placebo >= p90 (30 block-shuffled draws), AND
  (4) SELECTION-ADJUSTED: min-holdout >= p90 of the nuclear search-null best
      distribution (8 full BFS->DFS pipeline runs on shuffled labels).
  Anything failing (4) is a shadow candidate at most.
HONESTY: partition asserts (complement cells), no-lookahead spot check,
  incremental leaderboard saves.

Run:  SKIP_LEDGER=1 /tmp/venv/bin/python -W ignore scripts/nuclear_regime.py
"""
from __future__ import annotations

import json
import os
import sys
import time

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


# ------------------------------------------------------- family registry ----
def fam_registry(px):
    """Pre-registered state families (causal; complement cells; 100% coverage)."""
    btc = px["BTC"]
    out = {}
    ret_df = px.pct_change()
    bvol = btc.pct_change().rolling(20).std()

    def two(name, a):
        a = a.fillna(False)
        out[name] = {"A": a, "B": ~a}

    def four(name, u, hi):
        u = u.fillna(False)
        hi = hi.fillna(False)
        out[name] = {"UP_A": (u & hi), "UP_B": (u & ~hi),
                     "DN_A": (~u & hi), "DN_B": (~u & ~hi)}

    # trend windows
    for w in (50, 75, 100, 125, 150, 200):
        ma = btc.rolling(w).mean()
        two(f"T{w}", btc > ma)
    # hysteresis grid
    for w in (50, 100, 150, 200):
        for b in (1, 2, 3, 5):
            hy = sh4.hyst_state(px, w, b / 100.0)
            two(f"H{w}b{b}", hy > 0.5)
    # vol level quantiles
    for q in (50, 60, 70, 80):
        vq = bvol.expanding().quantile(q / 100.0).shift(1)
        two(f"VOL{q}", bvol > vq)
    # stress quantiles
    for q in (70, 75, 80, 85, 90):
        vq = bvol.expanding().quantile(q / 100.0).shift(1)
        two(f"STRESS{q}", bvol > vq)
    # dispersion
    for l in (20, 40, 60, 90):
        disp = px.pct_change(l).std(axis=1)
        two(f"DISP{l}", disp > disp.expanding().median().shift(1))
    # avg pairwise correlation
    cols = list(px.columns)
    pairs = [(a, b) for i, a in enumerate(cols) for b in cols[i + 1:]]
    for l in (20, 30, 60):
        cm = pd.DataFrame({f"{a}-{b}": ret_df[a].rolling(l).corr(ret_df[b]) for a, b in pairs})
        avg = cm.mean(axis=1)
        two(f"CORR{l}", avg > avg.expanding().median().shift(1))
    # breadth thresholds
    breadth = (px > px.rolling(50).mean()).mean(axis=1)
    for h, lo in ((0.5, 0.4), (0.6, 0.4), (0.6, 0.35), (0.7, 0.3)):
        b_hi = (breadth > h).fillna(False)
        b_lo = (breadth < lo).fillna(False)
        out[f"BREADTH{int(h*100)}{int(lo*100)}"] = {
            "BHI": b_hi, "BLO": b_lo, "BMID": ~(b_hi | b_lo)}
    # momentum sign
    for l in (10, 20, 30, 40, 60):
        two(f"MOM{l}", btc.pct_change(l) > 0)
    # dual-MA crosses
    for f_, s_ in ((50, 150), (50, 200), (100, 200)):
        two(f"DUALMA{f_}_{s_}", btc.rolling(f_).mean() > btc.rolling(s_).mean())
    # 3-state hysteresis
    ma = btc.rolling(100).mean()
    on3 = (btc > ma * 1.02).fillna(False)
    off3 = (btc < ma * 0.98).fillna(False)
    out["TREND3"] = {"ON": on3, "OFF": off3, "CHOP": ~(on3 | off3)}
    # drawdown depth
    dd = btc / btc.expanding().max() - 1.0
    for d in (10, 15):
        deep = (dd < -d / 100.0).fillna(False)
        mid = ((dd >= -d / 100.0) & (dd <= -0.03)).fillna(False)
        out[f"ATHDD{d}"] = {"DEEP": deep, "MID": mid, "HIGH": ~(deep | mid)}
    # crosses with trend100
    up100 = (btc > btc.rolling(100).mean()).fillna(False)
    hi_vol70 = (bvol > bvol.expanding().quantile(0.70).shift(1)).fillna(False)
    hi_stress80 = (bvol > bvol.expanding().quantile(0.80).shift(1)).fillna(False)
    disp60 = px.pct_change(60).std(axis=1)
    hi_disp60 = (disp60 > disp60.expanding().median().shift(1)).fillna(False)
    cm30 = pd.DataFrame({f"{a}-{b}": ret_df[a].rolling(30).corr(ret_df[b]) for a, b in pairs})
    avg30 = cm30.mean(axis=1)
    hi_corr30 = (avg30 > avg30.expanding().median().shift(1)).fillna(False)
    b_hi6 = (breadth > 0.6).fillna(False)
    b_lo4 = (breadth < 0.4).fillna(False)
    hi_mom30 = (btc.pct_change(30) > 0).fillna(False)
    four("X_VOL", up100, hi_vol70)
    four("X_STRESS", up100, hi_stress80)
    four("X_DISP", up100, hi_disp60)
    four("X_CORR", up100, hi_corr30)
    four("X_BREADTH", up100, b_hi6 & ~b_lo4)
    four("X_MOM", up100, hi_mom30)
    # champion-hysteresis crosses
    hy2 = (sh4.hyst_state(px, 100, 0.02) > 0.5)
    four("HX_VOL", hy2, hi_vol70)
    four("HX_STRESS", hy2, hi_stress80)
    four("HX_BREADTH", hy2, b_hi6 & ~b_lo4)
    four("HX_DISP", hy2, hi_disp60)
    # 2-way crosses
    four("X2_VOL_MOM", hi_vol70, hi_mom30)
    four("X2_BR_DISP", (b_hi6 & ~b_lo4), hi_disp60)
    four("X2_STR_CORR", hi_stress80, hi_corr30)
    return out


def check_all(px, fams):
    bad = []
    for name, cells in fams.items():
        tot = pd.Series(False, index=px.index)
        for m in cells.values():
            tot = tot | m.fillna(False)
        if float(tot.mean()) < 0.999:
            bad.append((name, round(float(tot.mean()), 3)))
    return (PASS if not bad else FAIL), (f"all {len(fams)} families cover >=99.9%"
                                         if not bad else f"incomplete: {bad}")


def eval_node(name, cells, sm, mode, ws_full, streams, px, ws_win, dbounds):
    kind = "top2" if mode == "top2" else "single"
    cfg = rx.Cfg(name, kind, cells=cells, sm=sm)
    full, hold, frozen = rx.scan_eval(cfg, ws_full, streams, px, ws_win, dbounds)
    return {"name": name, "mode": mode, "sm": sm, "full": round(full, 2),
            "lofo": [round(h, 2) for h in hold], "frozen": [round(f, 2) for f in frozen],
            "min_hold": round(min(hold), 2), "avg_hold": round(float(np.mean(hold)), 2),
            "min_frozen": round(min(frozen), 2), "allpos": bool(all(h > 0 for h in hold))}


def shuf_cells(cells, rng):
    raw = ra2.labels_from_cells(cells,  cells[list(cells)[0]].index)
    block = 30
    nblk = int(np.ceil(len(raw) / block))
    perm = rng.permutation(nblk)
    s = pd.Series(np.concatenate(
        [raw.iloc[bi * block:(bi + 1) * block].values for bi in perm])[:len(raw)],
        index=raw.index)
    return {c: (s == c) for c in cells}


def config_placebo_generic(spec, streams, px, ws_win, dbounds, champ_avg, n_draws=30):
    """spec: ("fam", cells, sm, mode) or ("ens", [(cells, sm), (cells, sm)])."""
    draws = []
    for d in range(n_draws):
        rng = np.random.default_rng(7000 + d)
        if spec[0] == "fam":
            _, cells, sm, mode = spec
            cfg = rx.Cfg("x", "top2" if mode == "top2" else "single",
                         cells=shuf_cells(cells, rng), sm=sm)
        else:
            cfg = rx.Cfg("x", "ens",
                         parts=[(shuf_cells(c, rng), sm) for c, sm in spec[1]])
        _f, hold, _fr = rx.scan_eval(cfg, ws_full, streams, px, ws_win, dbounds)
        draws.append(round(float(np.mean(hold)), 2))
    avgs = np.array(draws)
    return {"champion_avg": round(champ_avg, 2), "null_mean": round(float(avgs.mean()), 2),
            "null_p90": round(float(np.quantile(avgs, 0.9)), 2),
            "champion_percentile": round(float((avgs < champ_avg).mean()) * 100.0, 1),
            "draws_beating": int((avgs >= champ_avg).sum())}


def nuclear_null_draw(seed, fams_shuf, ws_full, streams, px, ws_win, dbounds,
                      p3_cells, h4_cells):
    """One shuffled-label run of the FULL pipeline: BFS -> top-6 -> DFS -> polish -> best."""
    rng = np.random.default_rng(seed)
    fam_s = {k: shuf_cells(v, rng) for k, v in fams_shuf.items()}
    p3_s, h4_s = shuf_cells(p3_cells, rng), shuf_cells(h4_cells, rng)
    bfs = []
    for name, cells in fam_s.items():
        r = eval_node(name, cells, 10, "single", ws_full, streams, px, ws_win, dbounds)
        bfs.append((name, cells, r))
    bfs_sorted = sorted(bfs, key=lambda kv: kv[2]["min_hold"], reverse=True)
    best = bfs_sorted[0][2]
    best_cells = bfs_sorted[0][1]
    for name, cells, _r in bfs_sorted[:6]:
        for sm in (0, 3, 5, 8, 15):
            r = eval_node(f"{name}_s{sm}", cells, sm, "single",
                          ws_full, streams, px, ws_win, dbounds)
            if r["min_hold"] > best["min_hold"]:
                best, best_cells = r, cells
        r = eval_node(f"{name}_top2", cells, 10, "top2",
                      ws_full, streams, px, ws_win, dbounds)
        if r["min_hold"] > best["min_hold"]:
            best, best_cells = r, cells
    # polish replication (as in the real pipeline): ens(best, P3) and ens(best, H4) w50
    best_sm = best["sm"] if best.get("mode") != "top2" else 10
    for cells_b in (p3_s, h4_s):
        cfg = rx.Cfg("ens", "ens", parts=[(best_cells, best_sm), (cells_b, 10)])
        _f, hold, _fr = rx.scan_eval(cfg, ws_full, streams, px, ws_win, dbounds)
        mn = min(hold)
        if mn > best["min_hold"]:
            best = {"name": "ens_polish", "min_hold": round(mn, 2)}
    return best


def save_partial(lb_path, block):
    lb = json.load(open(lb_path))
    lb["exp035_nuclear"] = block
    json.dump(lb, open(lb_path, "w"), indent=2)


def main():
    global ws_full, streams
    t0 = time.time()
    px = ra.load_all()
    rh.MENU = rh.menu_builders()
    n = len(px)
    dbounds = [(0, int(n * 0.38)), (int(n * 0.38), int(n * 0.70)), (int(n * 0.70), n)]
    ws_full, streams = rx.build_full(px)
    ws_win = {h: rx.build_win(px, a, b_) for h, (a, b_) in enumerate(dbounds, start=1)}
    LB = "reports/strategy_leaderboard.json"

    fams = fam_registry(px)
    st, msg = check_all(px, fams)
    print(f"{st} partition: {msg}  ({len(fams)} BFS families)")

    # ---------------------------- BFS phase ---------------------------------
    print("\n" + "=" * 118)
    print(f"BFS PHASE: {len(fams)} pre-registered families x sm=10 (real data)")
    print("=" * 118)
    bfs_rows = []
    for i, (name, cells) in enumerate(fams.items()):
        r = eval_node(name, cells, 10, "single", ws_full, streams, px, ws_win, dbounds)
        bfs_rows.append(r)
        if i % 10 == 0 or r["min_hold"] > 1.5:
            print(f"  [{i:3d}] {name:<16} full {r['full']:+7.2f} LOFO "
                  f"{r['lofo'][0]:+7.2f}/{r['lofo'][1]:+6.2f}/{r['lofo'][2]:+6.2f} "
                  f"min {r['min_hold']:+6.2f} {'ALL+' if r['allpos'] else ''}")
    bfs_sorted = sorted(bfs_rows, key=lambda r: (r["min_hold"], r["avg_hold"]), reverse=True)
    print("\n  BFS top-8 by min-holdout:")
    for r in bfs_sorted[:8]:
        print(f"    {r['name']:<16} min {r['min_hold']:+6.2f} avg {r['avg_hold']:+6.2f} "
              f"full {r['full']:+6.2f} {'ALL+' if r['allpos'] else ''}")
    save_partial(LB, {"phase": "BFS", "bfs_nodes": bfs_rows,
                      "bfs_top": [r["name"] for r in bfs_sorted[:8]]})

    # ---------------------------- DFS phase ---------------------------------
    print("\n" + "=" * 118)
    print("DFS PHASE: top-6 branches x {sm 0,3,5,8,15 + top2}")
    print("=" * 118)
    dfs_rows = []
    for name, cells in [(r["name"], fams[r["name"]]) for r in bfs_sorted[:6]]:
        for sm in (0, 3, 5, 8, 15):
            r = eval_node(f"{name}_s{sm}", cells, sm, "single",
                          ws_full, streams, px, ws_win, dbounds)
            dfs_rows.append(r)
        r = eval_node(f"{name}_top2", cells, 10, "top2",
                      ws_full, streams, px, ws_win, dbounds)
        dfs_rows.append(r)
        print(f"  {name}: " + " ".join(f"s{x['sm']}{'T' if x['mode']=='top2' else ''}="
                                       f"{x['min_hold']:+.2f}" for x in dfs_rows[-6:]))

    # ---------------------------- polish nodes ------------------------------
    all_rows = bfs_rows + dfs_rows
    all_sorted = sorted(all_rows, key=lambda r: (r["min_hold"], r["avg_hold"]), reverse=True)
    win = all_sorted[0]
    win_cells = fams[win["name"].split("_s")[0].split("_top2")[0]]
    # polish: winner x incumbent ensemble (w50) and winner x H4 (w50)
    h4c = rx.new_defs(px)["H4_hyst_x_breadth"]
    polish_rows = []
    for tag, cells_b in (("W_P3", fams["H100b2"]), ("W_H4", h4c)):
        cfg = rx.Cfg(tag, "ens", parts=[(win_cells, win["sm"] if win["mode"] != "top2" else 10),
                                        (cells_b, 10)])
        full, hold, frozen = rx.scan_eval(cfg, ws_full, streams, px, ws_win, dbounds)
        r = {"name": f"ENS_{win['name']}x{tag}", "mode": "ens", "sm": 0,
             "full": round(full, 2), "lofo": [round(h, 2) for h in hold],
             "frozen": [round(f, 2) for f in frozen], "min_hold": round(min(hold), 2),
             "avg_hold": round(float(np.mean(hold)), 2),
             "min_frozen": round(min(frozen), 2),
             "allpos": bool(all(h > 0 for h in hold))}
        polish_rows.append(r)
        print(f"  polish {r['name']}: full {r['full']:+.2f} LOFO {r['lofo']} "
              f"min {r['min_hold']:+.2f} {'ALL+' if r['allpos'] else ''}")

    all_rows += polish_rows
    all_sorted = sorted(all_rows, key=lambda r: (r["min_hold"], r["avg_hold"]), reverse=True)
    total = len(all_rows)
    print(f"\n  TOTAL NODES VALIDATED: {total}")
    print("  overall top-8:")
    for r in all_sorted[:8]:
        print(f"    {r['name']:<24} min {r['min_hold']:+6.2f} avg {r['avg_hold']:+6.2f} "
              f"full {r['full']:+6.2f} {'ALL+' if r['allpos'] else ''}")
    save_partial(LB, {"phase": "DFS", "bfs_nodes": bfs_rows, "dfs_nodes": dfs_rows,
                      "polish_nodes": polish_rows, "total_nodes": total,
                      "top": [{"name": r["name"], "min_hold": r["min_hold"],
                               "avg_hold": r["avg_hold"], "full": r["full"]}
                              for r in all_sorted[:8]]})

    # ---------------------------- config placebo ----------------------------
    print("\n" + "=" * 118)
    print("CONFIG PLACEBO (30 draws) for overall top-3 nodes")
    print("=" * 118)
    inc_row = next((r for r in bfs_rows if r["name"] == "H100b2"), None)
    print(f"  incumbent H100b2 (=P3+smooth10 family): min {inc_row['min_hold']:+.2f} "
          f"avg {inc_row['avg_hold']:+.2f} (baseline)")
    p3_cells = fams["H100b2"]
    cp = {}
    for r in all_sorted[:3]:
        nm = r["name"]
        if nm.startswith("ENS_"):
            other = p3_cells if nm.endswith("xW_P3") else h4c
            spec = ("ens", [(win_cells, win["sm"] if win["mode"] != "top2" else 10),
                            (other, 10)])
        else:
            base = nm.split("_s")[0].split("_top2")[0]
            spec = ("fam", fams[base], r["sm"] if r["mode"] != "top2" else 10, r["mode"])
        pl = config_placebo_generic(spec, streams, px, ws_win, dbounds, r["avg_hold"])
        cp[nm] = pl
        print(f"  {nm:<24} avg {pl['champion_avg']:+.2f} vs null {pl['null_mean']:+.2f} "
              f"(p90 {pl['null_p90']:+.2f}) -> pct {pl['champion_percentile']:.0f}, "
              f"{pl['draws_beating']}/30 beat")

    # no-lookahead spot check on the top families
    t = int(n * 0.6)
    px2 = px.copy()
    px2.iloc[t:] = px2.iloc[t:] * 1.13
    fams_f = fam_registry(px2)
    leaks = 0
    for base in {r["name"].split("_s")[0].split("_top2")[0] for r in all_sorted[:5]
                 if not r["name"].startswith("ENS_")}:
        for cell, m1 in fams[base].items():
            m2 = fams_f[base][cell]
            if not (m1.iloc[:t].fillna(False).values == m2.iloc[:t].fillna(False).values).all():
                leaks += 1
    print(f"  no-lookahead on top families: {'PASS' if leaks == 0 else f'FAIL {leaks} leaks'}")

    # ---------------------------- search-level placebo ----------------------
    print("\n" + "=" * 118)
    print("SEARCH-LEVEL PLACEBO: full BFS->DFS->polish pipeline on shuffled labels, 8 draws")
    print("=" * 118)
    null_best = []
    for d in range(8):
        b = nuclear_null_draw(8000 + d, fams, ws_full, streams, px, ws_win, dbounds,
                              p3_cells, h4c)
        null_best.append(b["min_hold"])
        print(f"  draw {d}: best min-holdout {b['min_hold']:+6.2f} ({b['name']})")
    nb = np.array(null_best)
    real_best = all_sorted[0]["min_hold"]
    sl = {"real_best_min_hold": real_best, "null_mean": round(float(nb.mean()), 2),
          "null_p90": round(float(np.quantile(nb, 0.9)), 2),
          "null_max": round(float(nb.max()), 2),
          "real_percentile": round(float((nb < real_best).mean()) * 100.0, 1),
          "draws_beating": int((nb >= real_best).sum()), "n_draws": 8,
          "null_best": [round(float(x), 2) for x in nb]}
    print(f"  -> real best +{real_best:.2f} vs search-null mean {sl['null_mean']:+.2f} "
          f"p90 {sl['null_p90']:+.2f} max {sl['null_max']:+.2f} -> pct {sl['real_percentile']:.0f} "
          f"({sl['draws_beating']}/8 beat)")

    # ---------------------------- verdict -----------------------------------
    winner = all_sorted[0]
    wname = winner["name"]
    gates = {
        "g1_min_hold": bool(winner["min_hold"] > inc_row["min_hold"]),
        "g2_allpos": bool(winner["allpos"]),
        "g3_placebo": bool(cp.get(wname, {}).get("champion_percentile", 0) >= 90),
        "g4_selection_adjusted": bool(real_best >= sl["null_p90"]),
    }
    certified = all(gates.values())
    verdict = {
        "total_nodes": total, "winner": wname,
        "winner_min_hold": winner["min_hold"], "winner_avg": winner["avg_hold"],
        "winner_full": winner["full"], "winner_lofo": winner["lofo"],
        "incumbent_min_hold": inc_row["min_hold"], "incumbent_avg": inc_row["avg_hold"],
        "gates": gates, "certified_replacement": bool(certified),
        "search_null": sl,
        "final": (wname if certified else
                  f"P3+smooth10 (incumbent stands); {wname} = best nuclear node "
                  f"(shadow candidate)"),
    }
    print("\nVERDICT:", json.dumps(verdict))
    save_partial(LB, {"phase": "FINAL", "bfs_nodes": bfs_rows, "dfs_nodes": dfs_rows,
                      "polish_nodes": polish_rows, "total_nodes": total,
                      "top": [{"name": r["name"], "min_hold": r["min_hold"],
                               "avg_hold": r["avg_hold"], "full": r["full"],
                               "lofo": r["lofo"]} for r in all_sorted[:8]],
                      "config_placebo": cp, "search_level_placebo": sl,
                      "verdict": verdict, "runtime_sec": round(time.time() - t0, 1)})
    print(f"\nSaved exp035_nuclear ({total} nodes, {time.time()-t0:.0f}s).")


if __name__ == "__main__":
    main()
