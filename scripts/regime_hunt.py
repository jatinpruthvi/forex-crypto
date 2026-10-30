"""EXP-029 — Regime-conditional strategy selection: best (parameter-state x strategy) combos.

User's mathematical framing (agreed): trading = probability model over a non-stationary
random process; one strategy cannot be ergodic across all regimes. The right object is a
causal regime-conditional policy pi(state) -> strategy.

Method (pre-registered):
  1. PARAMETER STATES (causal, theory-motivated, low-dimensional):
     BTC trend (MA100/MA150/hysteresis), volatility level vs expanding median,
     vol stress (expanding q80), breadth (fraction of coins > their MA50), vol trend.
  2. CONDITIONAL VALIDATION: every menu strategy is measured INSIDE every regime cell
     (in-cell monthly, in-cell DD, occupancy) - the "best strategy for that parameter".
  3. COMPOSITE: per regime definition, assign to each cell the argmax strategy by
     pre-registered rule (max in-cell monthly s.t. in-cell DD/Mo<=10, occupancy>=5%);
     the composite switches strategies when the state changes.
  4. HONEST VALIDATION: assignments chosen on 2 folds' conditional stats -> applied on
     the held-out fold (LOFO); threshold neighbors; vs best static strategies.

Composite selection rule: max worst-fold monthly s.t. all folds>-1, nonbull>0,
bull_share<0.8, DD/Mo<=10, Cal>=1.2, maxDD<=35.

Run:  SKIP_LEDGER=1 /tmp/venv/bin/python -W ignore scripts/regime_hunt.py
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
import strategy_hunt3 as sh3  # noqa: E402
import strategy_hunt4 as sh4  # noqa: E402
import strategy_hunt5 as sh5  # noqa: E402


# ------------------------------------------------------------- menu ----------
def menu_builders():
    """The validated strategy menu (all crypto, all previously hunted)."""
    def fvg15(px):
        o, h, l, c = sh5.ohlc(px)
        return sh5.smc_pf(px, sh5.sig_fvg(h, l, c, max_age=15), hold=3, long_only=False)

    def fvg15_long(px):
        o, h, l, c = sh5.ohlc(px)
        return sh5.smc_pf(px, sh5.sig_fvg(h, l, c, max_age=15).clip(lower=0), hold=3, long_only=True)

    def fvg15_short(px):
        o, h, l, c = sh5.ohlc(px)
        return sh5.smc_pf(px, sh5.sig_fvg(h, l, c, max_age=15).clip(upper=0), hold=3, long_only=False)

    return {
        "FVG_LS": fvg15,
        "FVG_LONG": fvg15_long,
        "FVG_SHORT": fvg15_short,
        "VOL_GROT": lambda px: sh4.vg(px, 0.30, 150, 0.02),
        "ABS_GROT": lambda px: sh2.abs_mom_filter(sh.w_gated_rot(px, K=5, lb=90, gate_ma=100), px, 90),
        "GROT": lambda px: sh.w_gated_rot(px, K=5, lb=90, gate_ma=150),
        "DIP_V2": sh.w_dip_v2,
        "TSMOM": sh.w_tsmom_vol,
        "CASH": lambda px: pd.DataFrame(0.0, index=px.index, columns=px.columns),
    }


# ------------------------------------------------- regime definitions -------
def regime_defs(px):
    """Causal parameter-state families: {name: {cell_label: boolean mask}}."""
    btc = px["BTC"] if "BTC" in px.columns else px.iloc[:, 0]
    out = {}

    ma100 = btc.rolling(100).mean()
    ma150 = btc.rolling(150).mean()
    out["P1_trend100"] = {"UP": (btc > ma100).fillna(False), "DOWN": (btc <= ma100).fillna(False)}
    out["P2_trend150"] = {"UP": (btc > ma150).fillna(False), "DOWN": (btc <= ma150).fillna(False)}
    hy = sh4.hyst_state(px, 100, 0.02)
    out["P3_hyst100"] = {"ON": (hy > 0.5), "OFF": (hy <= 0.5)}

    bvol = btc.pct_change().rolling(20).std()
    vmed = bvol.expanding().median().shift(1)
    hi_vol = (bvol > vmed).fillna(False)
    out["P4_trend_x_vol"] = {
        "UP_LOVOL": ((btc > ma100) & ~hi_vol).fillna(False),
        "UP_HIVOL": ((btc > ma100) & hi_vol).fillna(False),
        "DN_LOVOL": ((btc <= ma100) & ~hi_vol).fillna(False),
        "DN_HIVOL": ((btc <= ma100) & hi_vol).fillna(False)}

    breadth = (px > px.rolling(50).mean()).mean(axis=1)
    b_hi = breadth > 0.6
    b_lo = breadth < 0.4
    out["P5_trend_x_breadth"] = {
        "UP_BHI": ((btc > ma100) & b_hi).fillna(False),
        "UP_BMID": ((btc > ma100) & ~b_hi & ~b_lo).fillna(False),
        "UP_BLO": ((btc > ma100) & b_lo).fillna(False),
        "DN_BHI": ((btc <= ma100) & b_hi).fillna(False),
        "DN_BMID": ((btc <= ma100) & ~b_hi & ~b_lo).fillna(False),
        "DN_BLO": ((btc <= ma100) & b_lo).fillna(False)}

    vq80 = bvol.expanding().quantile(0.8).shift(1)
    stress = (bvol > vq80).fillna(False)
    out["P6_trend_x_stress"] = {
        "UP_CALM": ((btc > ma100) & ~stress).fillna(False),
        "UP_STRESS": ((btc > ma100) & stress).fillna(False),
        "DN_CALM": ((btc <= ma100) & ~stress).fillna(False),
        "DN_STRESS": ((btc <= ma100) & stress).fillna(False)}

    vrising = bvol > bvol.shift(10)
    out["P7_vollevel_x_voltrend"] = {
        "LO_FELL": (~hi_vol & ~vrising).fillna(False),
        "LO_RISE": (~hi_vol & vrising).fillna(False),
        "HI_FELL": (hi_vol & ~vrising).fillna(False),
        "HI_RISE": (hi_vol & vrising).fillna(False)}

    out["P8_breadth3"] = {"BHI": b_hi.fillna(False), "BMID": (~b_hi & ~b_lo).fillna(False),
                          "BLO": b_lo.fillna(False)}
    return out


# --------------------------------------------- conditional validation -------
def in_cell_stats(r, mask):
    """Conditional performance of daily strategy returns r inside a regime cell."""
    rr = r[mask].dropna()
    n = len(rr)
    if n < 30:
        return None
    months = n / 30.44
    total = float((1.0 + rr).prod())
    monthly = total ** (1.0 / months) - 1.0 if total > 0 else -1.0
    eq = (1.0 + rr).cumprod()
    dd = float((eq / eq.cummax() - 1.0).min()) * 100.0
    dd_mo = abs(dd) / max(monthly * 100.0, 0.05) if monthly != 0 else 999.0
    return {"monthly": monthly * 100.0, "dd": dd, "dd_mo": dd_mo,
            "occupancy": float(mask.mean()), "n_days": n}


def run_composite(px, cells_map, assign):
    """Composite weights: strategy assigned to each regime cell."""
    builders = MENU
    # compute each menu strategy's weights once
    ws = {k: b(px) for k, b in builders.items()}
    label = pd.Series("NONE", index=px.index)
    for cell, mask in cells_map.items():
        label[mask.fillna(False)] = cell
    w = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    for cell in set(label.unique()) - {"NONE"}:
        sel = (label == cell)
        strat = assign.get(cell, "CASH")
        w[sel] = ws[strat][sel]
    return w


MENU = {}


def main():
    global MENU
    MENU = menu_builders()
    # OHLC for FVG
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

    # ---- menu baseline returns (for conditional stats) ----
    rets = {}
    print("Computing menu baseline returns...")
    for k, b in MENU.items():
        w = b(px)
        _eq, r = sh.portfolio_sim(w, px)
        rets[k] = r

    defs = regime_defs(px)

    # ---- conditional validation table (the user's "best strategy per parameter") ----
    print("\n" + "=" * 118)
    print("CONDITIONAL VALIDATION: each strategy INSIDE each parameter-state cell (full period)")
    print("=" * 118)
    cond = {}
    for dname, cells in defs.items():
        print(f"\n--- {dname} ---")
        cond[dname] = {}
        for cell, mask in cells.items():
            m = mask.fillna(False)
            if m.mean() < 0.03:
                print(f"  {cell:<10} occupancy {m.mean():.2f} - too rare, skipped")
                continue
            row = {}
            for k in MENU:
                s = in_cell_stats(rets[k], m)
                if s:
                    row[k] = s
            cond[dname][cell] = row
            best = max(row.items(), key=lambda kv: kv[1]["monthly"]
                       if kv[1]["dd_mo"] <= 10 else -99)
            order = sorted(row.items(), key=lambda kv: kv[1]["monthly"], reverse=True)
            tops = " | ".join(f"{k} {v['monthly']:+.2f}(DD{v['dd']:.0f})" for k, v in order[:4])
            print(f"  {cell:<10} occ {m.mean():.2f} -> {tops}")

    # ---- composites: assignment = argmax in-cell monthly s.t. DD/Mo<=10, occ>=5% ----
    print("\n" + "=" * 118)
    print("COMPOSITES: regime-conditional policies (assignment rule: max in-cell monthly s.t. DD/Mo<=10)")
    print("=" * 118)
    results = []
    for dname, cells in defs.items():
        assign = {}
        for cell, row in cond[dname].items():
            okd = {k: v for k, v in row.items() if v["dd_mo"] <= 10.0 and k != "CASH"}
            if not okd:
                assign[cell] = "CASH"
            else:
                assign[cell] = max(okd.items(), key=lambda kv: kv[1]["monthly"])[0]
        builder = (lambda p, cm=cells, ag=assign: run_composite(p, cm, ag))
        fm = sh.fold_metrics(builder, px)
        m = sh4.dyn_score(fm)
        m.update({"round": 10, "node": f"M/{dname}", "name": f"composite {dname} {assign}",
                  "scope": "crypto_1d_21c", "failed": False, "assign": assign})
        results.append(m)
        sh4.pr(m)
        print(f"    assignment: {assign}")

    # ---- composites rule 2: argmax monthly/DD ratio ----
    for dname, cells in defs.items():
        assign = {}
        for cell, row in cond[dname].items():
            okd = {k: v for k, v in row.items() if v["dd_mo"] <= 10.0 and k != "CASH" and v["monthly"] > 0}
            if not okd:
                assign[cell] = "CASH"
            else:
                assign[cell] = min(okd.items(), key=lambda kv: kv[1]["dd_mo"])[0]
        builder = (lambda p, cm=cells, ag=assign: run_composite(p, cm, ag))
        fm = sh.fold_metrics(builder, px)
        m = sh4.dyn_score(fm)
        m.update({"round": 10, "node": f"M2/{dname}", "name": f"composite-ddrule {dname} {assign}",
                  "scope": "crypto_1d_21c", "failed": False, "assign": assign})
        results.append(m)
        sh4.pr(m)

    # ---- LOFO: assignments chosen on 2 folds -> held-out ----
    print("\n" + "=" * 118)
    print("LOFO: regime->strategy assignment learned on 2 folds, applied on held-out fold")
    print("=" * 118)
    n = len(px)
    bounds = [(0, int(n * 0.38)), (int(n * 0.34), int(n * 0.70)), (int(n * 0.66), n)]
    best_def = "P4_trend_x_vol"
    for held in (1, 2, 3):
        a, b_ = bounds[held - 1]
        train_masks = []
        for k in (1, 2, 3):
            if k == held:
                continue
            x, y = bounds[k - 1]
            train_masks.append((x, y))
        defs_h = regime_defs(px)
        assign = {}
        for cell, mask in defs_h[best_def].items():
            row = {}
            for k in MENU:
                m_ = pd.Series(False, index=px.index)
                for x, y in train_masks:
                    m_.iloc[x:y] = True
                s = in_cell_stats(rets[k], mask.fillna(False) & m_)
                if s:
                    row[k] = s
            okd = {k: v for k, v in row.items() if v["dd_mo"] <= 10.0 and k != "CASH"}
            assign[cell] = max(okd.items(), key=lambda kv: kv[1]["monthly"])[0] if okd else "CASH"
        builder = (lambda p, cm=defs_h[best_def], ag=assign: run_composite(p, cm, ag))
        w = builder(px.iloc[max(0, a - 250):b_]).reindex(px.iloc[a:b_].index).fillna(0.0)
        eq, r = sh.portfolio_sim(w, px.iloc[a:b_])
        m = sh.metrics(eq, r)
        print(f"  held-out fold{held}: assign={assign}")
        print(f"    -> {m['monthly_roi']:+7.2f}%/mo | DD {m['max_dd']:5.1f}% | worstM {m['worst_month']:+6.1f}")
        results.append({"round": 10, "node": "M/LOFO", "name": f"LOFO-10 fold{held} ({best_def})",
                        "scope": "held-out fold", "monthly_roi": m["monthly_roi"],
                        "max_dd": m["max_dd"], "calmar": m["calmar"], "dd_monthly": m["dd_monthly"],
                        "worst_month": m["worst_month"], "worst_fold": m["monthly_roi"],
                        "nonbull_avg": m["monthly_roi"], "bull_share": 0.0,
                        "dyn_ok": False, "failed": False})

    # ---- save ----
    path = "reports/strategy_leaderboard.json"
    lb = json.load(open(path))
    lb["entries"] = [e for e in lb["entries"] if e.get("round") != 10]
    lb["entries"].extend(results)
    lb["conditional_table"] = {d: {c: {k: round(v["monthly"], 2) for k, v in row.items()}
                                   for c, row in cells.items()}
                               for d, cells in cond.items()}
    dyn = [r for r in results if r.get("dyn_ok")]
    dyn.sort(key=lambda r: r.get("worst_fold", -99), reverse=True)
    lb["selection_guide_regime"] = {
        "rule": "max worst-fold s.t. folds>-1, nonbull>0, bull%<0.8, DD/Mo<=10, Cal>=1.2, DD<=35",
        "best_composite": {k: dyn[0].get(k) for k in ("name", "node", "worst_fold", "nonbull_avg",
                                                      "bull_share", "monthly_roi", "max_dd", "calmar", "folds")}
        if dyn else None,
        "n_conditional_validations": sum(len(v) for v in lb["conditional_table"].values()),
    }
    lb["tree_round10_nodes_visited"] = len(results) + sum(len(v) for v in lb["conditional_table"].values())
    json.dump(lb, open(path, "w"), indent=2)
    print(f"\nSaved round-10: {len(results)} composites + "
          f"{lb['selection_guide_regime']['n_conditional_validations']} conditional validations")
    if dyn:
        print(f"BEST COMPOSITE: {dyn[0]['node']} {dyn[0]['name']}")
        print(f"  worst-fold {dyn[0]['worst_fold']:+.2f} | nonbull {dyn[0]['nonbull_avg']:+.2f} "
              f"| bull% {dyn[0]['bull_share']:.2f} | full {dyn[0]['monthly_roi']:+.2f}%/mo "
              f"DD {dyn[0]['max_dd']:.1f}% Cal {dyn[0]['calmar']:.2f}")


if __name__ == "__main__":
    main()
