"""EXP-032 — Forex regime-conditional policy: best (parameter-state x strategy) per pair.

User's mathematical framing (same as EXP-029, now applied to forex): trading is a
probability model over non-stationary data; divide time by parameter-states; validate
each strategy INSIDE each state; the final policy applies the best (parameter x
strategy) combination per state. EXP-028 tested only STATIC FX strategies (all 37
failed) - the conditional lens has never been applied to forex.

PRE-REGISTERED DESIGN (fixed before results):
  Data: 4 FX pairs (EURUSD, GBPUSD, EURJPY, XAUUSD), H4->daily, 2012-11..2022-03,
  ~2400 bars, fee 5bp/turnover side (FEE_FX).
  MENU (10 strategies + CASH, from the EXP-028 node families - fixed, no additions):
    FVG_LS age15 h3 | FVG_LONG | FVG_SHORT | OB_LS h5 | SWEEP_LS h3 | RANGE_MR h10
    | TSMOM_VOL | DIP_V2 | GATED_ROT K2 lb90 g150 | MR_RSI2 | CASH
  STATE FAMILIES (causal; P1-P6 per-pair own price, G1-G2 global):
    P1 trend100, P2 trend150, P3 hyst100 +-2%, P4 trend x vollevel,
    P5 trend x volstress(q80), P6 vollevel x voltrend,
    G1 breadth (fraction of pairs > MA50), G2 XAUUSD hyst100 (global risk driver)
  ASSIGNMENT RULE: per (pair, cell) argmax in-cell monthly s.t. in-cell dd/Mo <= 10,
    n_days >= 30, else CASH. Composite = per-column strategy selection (each pair's
    column follows its own state), sm=10-day persistence before switches.
  CHAMPION RULE: max min-strict-LOFO-holdout monthly among families with ALL strict
    LOFO holdouts > 0 (mapping learned on 2 disjoint blocks -> applied to 3rd);
    ties by full-period Calmar. If no family qualifies -> report honestly.
  HONESTY STACK (EXP-031): partition-coverage asserts, no-lookahead check,
    strict disjoint-block LOFO (38/32/30), NESTED LOFO (family x sm x mapping chosen
    on training only), PLACEBO NULL (30 block-shuffled state draws).

Run:  SKIP_LEDGER=1 /tmp/venv/bin/python -W ignore scripts/forex_regime.py
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
import regime_audit2 as ra2  # noqa: E402
import forex_validate as fv  # noqa: E402

FEE_FX = fv.FEE_FX
PASS, FAIL = "PASS", "FAIL"


# --------------------------------------------------------------- menu --------
def menu_builders():
    """Pre-registered FX menu (families from EXP-028 nodes; frozen)."""
    def variant(sigfn, long_only, hold, K):
        def builder(p, f=sigfn, lo=long_only, h=hold, k=K):
            o, hgh, l, c = sh5.ohlc(p)
            return sh5.smc_pf(p, f(o, hgh, l, c), hold=h, long_only=lo, K=k)
        return builder

    def fvg_age(age, h=3, K=0):
        return variant((lambda o, hgh, l, c, a=age: sh5.sig_fvg(hgh, l, c, max_age=a)),
                       False, h, K)

    ob = sh5.smc_sigs_global["04"][0]
    sweep = sh5.smc_sigs_global["06"][0]
    return {
        "FVG_LS": fvg_age(15, 3, 0),
        "FVG_LONG": variant((lambda o, hgh, l, c: sh5.sig_fvg(hgh, l, c, max_age=15).clip(lower=0)),
                            True, 3, 0),
        "FVG_SHORT": variant((lambda o, hgh, l, c: sh5.sig_fvg(hgh, l, c, max_age=15).clip(upper=0)),
                             False, 3, 0),
        "OB_LS": variant(ob, False, 5, 0),
        "SWEEP_LS": variant(sweep, False, 3, 0),
        "RANGE_MR": lambda p: sh5.smc_pf(p, sh5.sig_range_mr(sh5.ohlc(p)[1], sh5.ohlc(p)[2],
                                                            sh5.ohlc(p)[3]), hold=10,
                                        long_only=False),
        "TSMOM_VOL": sh.w_tsmom_vol,
        "DIP_V2": sh.w_dip_v2,
        "GATED_ROT": lambda p: sh.w_gated_rot(p, K=2, lb=90, gate_ma=150),
        "MR_RSI2": sh.w_mr_rsi2,
        "CASH": lambda p: pd.DataFrame(0.0, index=p.index, columns=p.columns),
    }


# ------------------------------------------------------- regime states -------
def hyst(x: pd.Series, ma=100, band=0.02) -> pd.Series:
    """Hysteresis state for one series (causal; warmup bars -> 0)."""
    m = x.rolling(ma).mean()
    state, out = 0.0, []
    for i in range(len(x)):
        p, mm = x.iloc[i], m.iloc[i]
        if not np.isnan(mm):
            if p > mm * (1.0 + band):
                state = 1.0
            elif p < mm * (1.0 - band):
                state = 0.0
        out.append(state)
    return pd.Series(out, index=x.index, dtype=float)


def regime_defs_fx(px):
    """{family: {pair: {cell_label: bool mask}}} - causal, complement cells (100% cover)."""
    pairs = list(px.columns)
    out = {f: {p: {} for p in pairs} for f in
           ("P1_trend100", "P2_trend150", "P3_hyst100", "P4_trend_x_vol",
            "P5_trend_x_stress", "P6_vol_x_voltrend", "G1_breadth", "G2_xau_driver")}

    # global breadth across pairs
    breadth = (px > px.rolling(50).mean()).mean(axis=1)
    b_hi = breadth > 0.6
    b_lo = breadth < 0.4
    # global XAU driver
    xau_on = (hyst(px["XAUUSD"], 100, 0.02) > 0.5)

    for p in pairs:
        x = px[p]
        ma100 = x.rolling(100).mean()
        ma150 = x.rolling(150).mean()
        up100 = (x > ma100).fillna(False)      # warmup -> False -> complement fills (EXP-030)
        up150 = (x > ma150).fillna(False)
        out["P1_trend100"][p] = {"UP": up100, "DOWN": ~up100}
        out["P2_trend150"][p] = {"UP": up150, "DOWN": ~up150}
        hy = hyst(x, 100, 0.02)
        out["P3_hyst100"][p] = {"ON": (hy > 0.5), "OFF": (hy <= 0.5)}
        bvol = x.pct_change().rolling(20).std()
        vmed = bvol.expanding().median().shift(1)
        hi_vol = (bvol > vmed).fillna(False)
        out["P4_trend_x_vol"][p] = {"UP_LOVOL": (up100 & ~hi_vol), "UP_HIVOL": (up100 & hi_vol),
                                    "DN_LOVOL": (~up100 & ~hi_vol), "DN_HIVOL": (~up100 & hi_vol)}
        vq80 = bvol.expanding().quantile(0.8).shift(1)
        stress = (bvol > vq80).fillna(False)
        out["P5_trend_x_stress"][p] = {"UP_CALM": (up100 & ~stress), "UP_STRESS": (up100 & stress),
                                       "DN_CALM": (~up100 & ~stress), "DN_STRESS": (~up100 & stress)}
        vrising = (bvol > bvol.shift(10)).fillna(False)
        out["P6_vol_x_voltrend"][p] = {"LO_FELL": (~hi_vol & ~vrising), "LO_RISE": (~hi_vol & vrising),
                                       "HI_FELL": (hi_vol & ~vrising), "HI_RISE": (hi_vol & vrising)}
        out["G1_breadth"][p] = {"BHI": b_hi.fillna(False),
                                "BMID": (~b_hi & ~b_lo).fillna(False), "BLO": b_lo.fillna(False)}
        out["G2_xau_driver"][p] = {"RISK_ON": xau_on, "RISK_OFF": ~xau_on}
    return out


# ------------------------------------------------- per-column streams --------
def col_streams(ws_map, px):
    """Per-strategy per-pair return streams: w_i*ret_i - |dw_i|*fee (sums == portfolio_sim)."""
    ret = px.pct_change().shift(-1)
    out = {}
    for k, w in ws_map.items():
        w = w.fillna(0.0).reindex(px.index).fillna(0.0)
        gross = w.abs().sum(axis=1)
        scale = np.where(gross > 2.0, 2.0 / gross.replace(0, np.nan), 1.0)
        w = w.mul(pd.Series(scale, index=w.index), axis=0)
        dw = w.diff().abs()
        out[k] = {c: (w[c] * ret[c] - dw[c] * FEE_FX).fillna(0.0) for c in px.columns}
    return out


def learn_assign_cols(streams, cells_pair, train_ranges, index):
    """Per pair per cell: argmax in-cell monthly (training bars only), dd/Mo<=10, n>=30."""
    m_ = pd.Series(False, index=index)
    for x, y in train_ranges:
        m_.iloc[x:y] = True
    assign = {}
    for p, cells in cells_pair.items():
        assign[p] = {}
        for cell, mask in cells.items():
            row = {}
            for k in streams:
                if k == "CASH":
                    continue
                s = rh.in_cell_stats(streams[k][p], mask.fillna(False) & m_)
                if s:
                    row[k] = s
            okd = {k: v for k, v in row.items() if v["dd_mo"] <= 10.0}
            assign[p][cell] = (max(okd.items(), key=lambda kv: kv[1]["monthly"])[0]
                               if okd else "CASH")
    return assign


def build_w(ws, cells_pair, assign_pair, sm, index, columns):
    """Per-column composite: each pair's column follows its own (persisted) state."""
    w = pd.DataFrame(0.0, index=index, columns=columns)
    for col in columns:
        cells = cells_pair[col]
        lab = pd.Series("NONE", index=index)
        for cell, m in cells.items():
            lab[m.reindex(index).fillna(False)] = cell
        if sm > 0:
            lab = ra2.persist(lab, sm)
        smap = assign_pair[col]
        for cell in set(lab.unique()) - {"NONE"}:
            sel = (lab == cell)
            strat = smap.get(cell, "CASH")
            w.loc[sel, col] = ws[strat].loc[sel, col]
    return w


def comp_builder(cells_pair, assign_pair, sm=0):
    def builder(p, cp=cells_pair, ap=assign_pair, s=sm):
        ws = {k: b(p) for k, b in MENU.items()}
        return build_w(ws, cp, ap, s, p.index, p.columns)
    return builder


MENU = {}


# ------------------------------------------------------------- checks --------
def check_partition(defs, px):
    bad = []
    for fam, per_pair in defs.items():
        for p, cells in per_pair.items():
            tot = pd.Series(False, index=px.index)
            for m in cells.values():
                tot = tot | m.fillna(False)
            if float(tot.mean()) < 0.999:
                bad.append((fam, p, float(tot.mean())))
    return (PASS if not bad else FAIL), (f"all {len(defs)} families cover >=99.9% of bars per pair"
                                         if not bad else f"incomplete: {bad}")


def check_no_lookahead(defs_s, defs_f, t):
    mism = 0
    for fam in defs_s:
        for p in defs_s[fam]:
            for cell, m1 in defs_s[fam][p].items():
                m2 = defs_f[fam][p][cell]
                if not (m1.iloc[:t].fillna(False).values == m2.iloc[:t].fillna(False).values).all():
                    mism += 1
    return (PASS if mism == 0 else FAIL), (f"labels up to t invariant under future perturbation"
                                           if mism == 0 else f"{mism} masks leak the future")


# ------------------------------------------------------------ evaluation -----
def block_eval(px_block, w):
    eq, r = sh.portfolio_sim(w, px_block, fee=FEE_FX)
    return sh.metrics(eq, r)


def strict_lofo(cells_pair, streams, px, ws_win, dbounds, sm=10):
    """Mapping learned on 2 disjoint blocks -> 3rd (crypto G2 protocol, per-column)."""
    n = len(px)
    hold = []
    for held in (1, 2, 3):
        train = [k for k in (1, 2, 3) if k != held]
        assign = learn_assign_cols(streams, cells_pair, [dbounds[k - 1] for k in train], px.index)
        a, b_ = dbounds[held - 1]
        wi = max(0, a - 250)
        w = build_w(ws_win[held], cells_pair, assign, sm,
                    px.iloc[wi:b_].index, px.columns).reindex(px.iloc[a:b_].index).fillna(0.0)
        m = block_eval(px.iloc[a:b_], w)
        hold.append(m["monthly_roi"])
    return hold


def main():
    global MENU
    MENU = menu_builders()
    O, H, L, C, V = fv.load_forex_ohlcv()
    px = C.dropna(how="any")
    if V.shape[1] == 0:
        V = px * 0.0
    sh5._O, sh5._H, sh5._L, sh5._C, sh5._V = (O.reindex(px.index), H.reindex(px.index),
                                              L.reindex(px.index), px, V.reindex(px.index))
    print(f"FX panel: {len(px)} daily bars, {px.index[0].date()} .. {px.index[-1].date()}, "
          f"{list(px.columns)}")
    n = len(px)
    dbounds = [(0, int(n * 0.38)), (int(n * 0.38), int(n * 0.70)), (int(n * 0.70), n)]

    print("Computing menu weight matrices + per-column streams...")
    ws_full = {k: b(px) for k, b in MENU.items()}
    streams = col_streams(ws_full, px)
    ws_win = {}
    for held, (a, b_) in enumerate(dbounds, start=1):
        p_win = px.iloc[max(0, a - 250):b_]
        ws_win[held] = {k: b(p_win) for k, b in MENU.items()}

    defs = regime_defs_fx(px)
    print("\n" + "=" * 118)
    print("CHECKS")
    print("=" * 118)
    st, msg = check_partition(defs, px)
    print(f"  {st}  partition coverage: {msg}")
    px2 = px.copy()
    t = int(n * 0.6)
    px2.iloc[t:] = px2.iloc[t:] * 1.13
    st2, msg2 = check_no_lookahead(regime_defs_fx(px), regime_defs_fx(px2), t)
    print(f"  {st2}  no-lookahead: {msg2}")

    # ---- conditional validation table (the user's deliverable) ----
    print("\n" + "=" * 118)
    print("CONDITIONAL TABLE: best strategy INSIDE each (pair, parameter-state) cell")
    print("=" * 118)
    cond = {}
    for fam, per_pair in defs.items():
        print(f"\n--- {fam} ---")
        cond[fam] = {}
        for p, cells in per_pair.items():
            cond[fam][p] = {}
            for cell, mask in cells.items():
                m = mask.fillna(False)
                if m.mean() < 0.03:
                    print(f"  {p}/{cell}: occ {m.mean():.2f} too rare")
                    continue
                row = {}
                for k in streams:
                    if k == "CASH":
                        continue
                    s = rh.in_cell_stats(streams[k][p], m)
                    if s:
                        row[k] = s
                okd = {k: v for k, v in row.items() if v["dd_mo"] <= 10.0}
                best = (max(okd.items(), key=lambda kv: kv[1]["monthly"])[0]
                        if okd else "CASH")
                s = row.get(best)
                cond[fam][p][cell] = {"best": best,
                                      "monthly": round(s["monthly"], 2) if s else 0.0,
                                      "dd": round(s["dd"], 1) if s else 0.0,
                                      "occupancy": round(float(m.mean()), 3)}
                print(f"  {p}/{cell:<9} occ {m.mean():.2f}: {best:<10} "
                      f"{s['monthly']:+6.2f}%/mo DD {s['dd']:6.1f}%" if s
                      else f"  {p}/{cell}: CASH")

    # ---- family composites: full-period + strict LOFO ----
    print("\n" + "=" * 118)
    print("FAMILY COMPOSITES (assign argmax per cell, sm=10 persistence)")
    print("=" * 118)
    fam_rows = []
    for fam, per_pair in defs.items():
        assign = learn_assign_cols(streams, per_pair, [(0, n)], px.index)
        fm = sh.fold_metrics(comp_builder(per_pair, assign, sm=10), px, fee=FEE_FX)
        m = sh4.dyn_score(fm)
        hold = strict_lofo(per_pair, streams, px, ws_win, dbounds, sm=10)
        allpos = all(h > 0 for h in hold)
        row = {"family": fam, "monthly_roi": m["monthly_roi"], "max_dd": m["max_dd"],
               "calmar": m["calmar"], "folds": m["folds"], "bull_share": m["bull_share"],
               "dyn_ok": m["dyn_ok"], "strict_lofo": [round(h, 2) for h in hold],
               "lofo_all_positive": bool(allpos),
               "assign": {p: dict(a) for p, a in assign.items()}}
        fam_rows.append(row)
        print(f"  {fam:<18} {m['monthly_roi']:+7.2f}%/mo DD {m['max_dd']:5.1f} Cal {m['calmar']:5.2f} "
              f"folds {m['folds'][0]:+6.2f}/{m['folds'][1]:+6.2f}/{m['folds'][2]:+6.2f} "
              f"LOFO {hold[0]:+6.2f}/{hold[1]:+6.2f}/{hold[2]:+6.2f} "
              f"{'LOFO-VALID' if allpos else ''} {'dyn_ok' if m['dyn_ok'] else ''}")

    # champion rule: all LOFO holdouts > 0, max min-holdout
    valid = [r for r in fam_rows if r["lofo_all_positive"]]
    champion = (max(valid, key=lambda r: (min(r["strict_lofo"]), r["calmar"])) if valid else None)

    # ---- nested LOFO (honesty): family x sm chosen on training only ----
    print("\n" + "=" * 118)
    print("NESTED LOFO (family x sm x mapping chosen on 2 training blocks ONLY)")
    print("=" * 118)
    nested_rows = []
    for held in (1, 2, 3):
        train = [k for k in (1, 2, 3) if k != held]
        scores = []
        for fam, per_pair in defs.items():
            assign = learn_assign_cols(streams, per_pair, [dbounds[k - 1] for k in train], px.index)
            for sm in (0, 5, 10):
                tr_ms = []
                for t_ in train:
                    a, b_ = dbounds[t_ - 1]
                    wi = max(0, a - 250)
                    wt = build_w(ws_win[t_], per_pair, assign, sm,
                                 px.iloc[wi:b_].index, px.columns).reindex(
                        px.iloc[a:b_].index).fillna(0.0)
                    tr_ms.append(block_eval(px.iloc[a:b_], wt)["monthly_roi"])
                scores.append(((fam, sm), assign, min(tr_ms)))
        best = max(scores, key=lambda kv: kv[2])
        (fam, sm), assign, wtr = best
        a, b_ = dbounds[held - 1]
        wi = max(0, a - 250)
        wh = build_w(ws_win[held], defs[fam], assign, sm,
                     px.iloc[wi:b_].index, px.columns).reindex(
            px.iloc[a:b_].index).fillna(0.0)
        mh = block_eval(px.iloc[a:b_], wh)
        nested_rows.append({"held": held, "chosen": fam, "sm": sm,
                            "train_worst": round(wtr, 2),
                            "holdout_monthly": mh["monthly_roi"], "holdout_dd": mh["max_dd"]})
        print(f"  held B{held}: chose {fam} sm{sm} (train worst {wtr:+.2f}) -> "
              f"HELD {mh['monthly_roi']:+.2f}%/mo DD {mh['max_dd']:.1f}%")
    nested_allpos = all(r["holdout_monthly"] > 0 for r in nested_rows)
    nested_avg = float(np.mean([r["holdout_monthly"] for r in nested_rows]))

    # ---- placebo null on the champion family (or best-LOFO family) ----
    tgt = champion if champion else max(fam_rows, key=lambda r: min(r["strict_lofo"]))
    print("\n" + "=" * 118)
    print(f"PLACEBO NULL (30 block-shuffled draws) on family {tgt['family']}")
    print("=" * 118)
    fam = tgt["family"]
    per_pair = defs[fam]
    champ_hold = tgt["strict_lofo"]
    champ_avg = float(np.mean(champ_hold))
    draws = []
    for d in range(30):
        rng = np.random.default_rng(2000 + d)
        shuf_cells = {}
        for p, cells in per_pair.items():
            raw = pd.Series("NONE", index=px.index)
            for cell, m in cells.items():
                raw[m.fillna(False)] = cell
            block = 30
            nblk = int(np.ceil(len(raw) / block))
            perm = rng.permutation(nblk)
            parts = [raw.iloc[bi * block:(bi + 1) * block].values for bi in perm]
            shuf = pd.Series(np.concatenate(parts)[:len(raw)], index=px.index)
            shuf_cells[p] = {cell: (shuf == cell) for cell in cells}
        hold = strict_lofo(shuf_cells, streams, px, ws_win, dbounds, sm=10)
        draws.append({"draw": d, "holdouts": [round(h, 2) for h in hold],
                      "avg": round(float(np.mean(hold)), 2)})
    avgs = np.array([r["avg"] for r in draws])
    placebo = {"champion_avg": round(champ_avg, 2),
               "null_mean": round(float(avgs.mean()), 2),
               "null_p90": round(float(np.quantile(avgs, 0.9)), 2),
               "null_max": round(float(avgs.max()), 2),
               "champion_percentile": round(float((avgs < champ_avg).mean()) * 100.0, 1),
               "draws_beating": int((avgs >= champ_avg).sum())}
    print(f"  null: mean {placebo['null_mean']:+.2f} p90 {placebo['null_p90']:+.2f} "
          f"max {placebo['null_max']:+.2f}; champion {champ_avg:+.2f} -> "
          f"pct {placebo['champion_percentile']:.0f} ({placebo['draws_beating']}/30 beat)")

    verdict = {
        "partition": st == PASS, "no_lookahead": st2 == PASS,
        "champion_family": tgt["family"],
        "champion_lofo_all_positive": bool(tgt["lofo_all_positive"]),
        "nested_all_positive": bool(nested_allpos), "nested_avg": round(nested_avg, 2),
        "placebo_pctl": placebo["champion_percentile"],
    }
    print("\nVERDICT:", json.dumps(verdict))

    # ---- save ----
    path_ = "reports/strategy_leaderboard.json"
    lb = json.load(open(path_))
    lb["entries"] = [e for e in lb["entries"] if e.get("round") != 11]
    lb["entries"].extend([{**r, "round": 11, "scope": "forex_regime_4p_daily_2012-11..2022-03"}
                          for r in fam_rows])
    lb["selection_guide_forex_regime"] = {
        "scope": "forex 4-pair daily 2012-11..2022-03, fee 5bp, sm=10 persistence",
        "conditional_table": cond,
        "family_results": fam_rows,
        "champion": ({"family": tgt["family"], "strict_lofo": champ_hold,
                      "assign": tgt["assign"],
                      "monthly_roi": tgt["monthly_roi"], "max_dd": tgt["max_dd"],
                      "calmar": tgt["calmar"], "folds": tgt["folds"]}
                     if tgt["lofo_all_positive"] else
                     {"family": tgt["family"], "status": "NO LOFO-VALID FX POLICY",
                      "strict_lofo": champ_hold}),
        "nested_lofo": {"rows": nested_rows, "all_positive": bool(nested_allpos),
                        "avg": round(nested_avg, 2)},
        "placebo": placebo,
        "checks": {"partition": st, "no_lookahead": st2},
    }
    lb["tree_round11_nodes_visited"] = len(fam_rows)
    json.dump(lb, open(path_, "w"), indent=2)
    print(f"\nSaved selection_guide_forex_regime ({len(fam_rows)} families).")


if __name__ == "__main__":
    main()
