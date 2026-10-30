"""EXP-041 (2026-10-30): FROM +1.74%/mo TO +6%/mo - which levers close the gap, at what risk?

User: "how can we reach to 6% from 1.74%? think in depth and check for 5.5y with
commission and spread."

PRE-REGISTERED LEVERS (all evaluated on 2021-01..2026-07, FEE=10bp per side of turnover
= commission + spread + slippage; 15bp stress row; funding band reported separately):
  L1 constant leverage ladder x{1,1.5,2,2.5,3,3.5,4} on the two best books
  L2 causal vol-targeting (trailing-30d realized vol, lag 1): target {20,30,40,50}% ann,
     mult clipped [0.25, cap{4,7}]
  L3 exposure lever: ungated rotation (gate_ma 150->20, still de-risks below 20d MA)
  L5 brain: quarterly (63d) guarded re-pick of top-3 engines from the 7-engine menu by
     trailing-252d monthly (dd_guard 12%), adopt only if >= current + 0.5%/mo (EXP-038
     recipe). Causal = honest forward.
  L6 stacks: vol-target(40%,cap4) x brain; ungated-brain; etc.
  L4 universe check: same books on the OLD 21-coin panel 2020-07..2023-04 (period-limited,
     quantifies the small-cap premium).
SELECTION: report the full %/mo-vs-DD frontier; mark rows at DD<=35 (deployable) and
DD<=50 (aggressive). Nothing is called "the 6% answer" unless it survives 15bp stress.
"""
import os
import sys
import json

sys.path.insert(0, os.path.abspath("scripts"))

import numpy as np
import pandas as pd

import strategy_hunt as sh
import strategy_hunt2 as sh2
import strategy_hunt4 as sh4
import regime_hunt as rh
import regime_audit2 as ra2
import regime_audit as ra
import regime_expansion as rx
import five_year_test as ft

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOARD = os.path.join(BASE, "reports", "strategy_leaderboard.json")
LEDGER = os.path.join(BASE, "reports", "roi_progress_ledger.json")


def ym_of(eq):
    m = eq.resample("ME").last().pct_change().dropna()
    return {int(y): float(((1 + g).prod() ** (1 / max(len(g), 1)) - 1) * 100)
            for y, g in m.groupby(m.index.year)}


def book_metrics(w, px, fee=0.0010, lev_cap=8.0):
    eq, r = sh.portfolio_sim(w, px, fee=fee, lev_cap=lev_cap)
    m = sh.metrics(eq, r)
    ym = ym_of(eq)
    months = max((px.index[-1] - px.index[0]).days / 30.44, 1)
    tot = eq.iloc[-1] / eq.iloc[0]
    gross = w.abs().sum(axis=1)
    short_not = ((-w).clip(lower=0)).sum(axis=1).mean()
    long_not = w.clip(lower=0).sum(axis=1).mean()
    fund_band = (long_not + short_not) * 0.05 / 12 * 100
    return {
        "monthly": round(m["monthly_roi"], 2), "dd": m["max_dd"],
        "worst_m": m["worst_month"],
        "min_year": round(min(ym.values()), 2) if ym else None,
        "yearly": {str(y): round(v, 2) for y, v in ym.items()},
        "total_x": round(float(tot), 2), "months": round(months),
        "gross_avg": round(float(gross.mean()), 2),
        "gross_max": round(float(gross.max()), 2),
        "fund_band_pm": round(fund_band, 2),
        "stressed": round(m["monthly_roi"] - fund_band, 2),
    }


def mix_of(ws, names):
    w = pd.DataFrame(0.0, index=list(ws.values())[0].index,
                     columns=list(ws.values())[0].columns)
    for k in names:
        w = w + ws[k].reindex(w.index).fillna(0.0)
    return w / len(names)


def volscale(w, px, target, cap_hi, look=30, cap_lo=0.25):
    """Causal vol targeting: mult_t from trailing `look`-day realized vol of the BASE
    book (10bp costs), applied from t+1; clipped [cap_lo, cap_hi]."""
    _eq, r = sh.portfolio_sim(w, px, fee=0.0010, lev_cap=12.0)
    rv = r.rolling(look).std() * np.sqrt(365)
    mult = (target / rv.replace(0, np.nan)).clip(cap_lo, cap_hi).shift(1).fillna(1.0)
    return w.mul(mult, axis=0)


def brain(px, ws, menu, base_names, rebal=63, look=252, guard=0.5, dd_guard=12.0):
    """EXP-038 recipe, causal: every `rebal` days pick top-3 engines by trailing-252d
    monthly (trailing equity DD <= dd_guard), equal weight; adopt only if candidate
    trailing monthly >= current + guard. Rows before first rebal = base mix."""
    idx = px.index
    n = len(idx)
    base = mix_of(ws, base_names)
    streams = {}
    for k in menu:
        _e, r = sh.portfolio_sim(ws[k].reindex(idx).fillna(0.0), px, fee=0.0010)
        streams[k] = r.fillna(0.0)
    current = list(base_names)
    w_out = base.copy()
    for t in range(look, n, rebal):
        tr = slice(max(0, t - look), t)
        stats = {}
        for k in menu:
            s = streams[k].iloc[tr]
            months = max(len(s) / 21.3, 1)
            mo = float((1 + s).prod() ** (1 / months) - 1)
            eq = (1 + s).cumprod()
            dd = float((eq / eq.cummax() - 1).min())
            stats[k] = {"mo": mo, "dd": -dd * 100}
        okd = [k for k, v in stats.items() if v["dd"] <= dd_guard]
        if not okd:
            okd = sorted(menu, key=lambda k: stats[k]["dd"])[:3]
        top3 = sorted(okd, key=lambda k: stats[k]["mo"], reverse=True)[:3]
        cand_mo = float(np.mean([stats[k]["mo"] for k in top3]))
        cur_mo = float(np.mean([stats[k]["mo"] for k in current]))
        if cand_mo >= cur_mo + guard / 100:
            current = top3
        w_out.iloc[t:t + rebal] = mix_of(ws, current).iloc[t:t + rebal]
    return w_out, current


def main():
    px = ft.load_all_5y()
    rh.MENU = rh.menu_builders()
    ws, _ = rx.build_full(px)
    for k in list(ws):
        ws[k] = ws[k].reindex(px.index).fillna(0.0)

    abs_short = mix_of(ws, ["ABS_GROT", "FVG_SHORT"])
    eq5 = mix_of(ws, ["GROT", "ABS_GROT", "VOL_GROT", "DIP_V2", "FVG_SHORT"])
    rows = {}

    def rec(name, w, note=""):
        m = book_metrics(w, px)
        rows[name] = {**m, "note": note}
        ys = " ".join(f"{str(y)[2:]}:{v:+5.1f}" for y, v in m["yearly"].items())
        flags = "".join(["D35" if m["dd"] <= 35 else "   ",
                         "D50" if m["dd"] <= 50 else "   ",
                         " 6%!" if m["monthly"] >= 6 else "    "])
        print(f"  {name:<28} {m['monthly']:+6.2f}%/mo DD {m['dd']:5.1f} "
              f"minYr {m['min_year']:+5.1f} x{m['total_x']:5.2f} gr{m['gross_avg']:4.2f} "
              f"| {ys} | {flags}")
        return m

    print("=" * 130)
    print("BASELINES (10bp/side)")
    print("=" * 130)
    rec("ABS_GROT+FVG_SHORT", abs_short, "base")
    rec("eq5_survivors+SHORT", eq5, "base")

    print("\n" + "=" * 130)
    print("L1 CONSTANT LEVERAGE (fees scale with turnover)")
    print("=" * 130)
    for name, w0 in [("ABS_SHORT", abs_short), ("eq5", eq5)]:
        for m_ in (1.5, 2.0, 2.5, 3.0, 3.5, 4.0):
            rec(f"{name}_x{m_}", w0 * m_, f"L1 m={m_}")

    print("\n" + "=" * 130)
    print("L2 CAUSAL VOL TARGETING (trailing-30d vol, lag 1)")
    print("=" * 130)
    for tgt in (0.20, 0.30, 0.40, 0.50):
        for cap in (4.0, 7.0):
            rec(f"ABS_SHORT_vt{int(tgt*100)}c{int(cap)}",
                volscale(abs_short, px, tgt, cap), f"L2 tgt={tgt} cap={cap}")
    for tgt in (0.30, 0.40):
        rec(f"eq5_vt{int(tgt*100)}c4", volscale(eq5, px, tgt, 4.0), f"L2 tgt={tgt}")

    print("\n" + "=" * 130)
    print("L3 EXPOSURE LEVER: UNGATED ROTATION (gate_ma 150->20)")
    print("=" * 130)
    ws["GROT_ung"] = sh.w_gated_rot(px, K=5, lb=90, gate_ma=20)
    ws["ABS_GROT_ung"] = sh2.abs_mom_filter(sh.w_gated_rot(px, K=5, lb=90, gate_ma=20), px, 90)
    rec("ABS_GROT_ung", ws["ABS_GROT_ung"], "L3")
    abs_short_ung = mix_of(ws, ["ABS_GROT_ung", "FVG_SHORT"])
    rec("ABS_ung+SHORT", abs_short_ung, "L3")
    eq5_ung = mix_of(ws, ["GROT_ung", "ABS_GROT_ung", "VOL_GROT", "DIP_V2", "FVG_SHORT"])
    rec("eq5_ung+SHORT", eq5_ung, "L3")

    print("\n" + "=" * 130)
    print("L5 BRAIN (quarterly guarded top-3, causal)")
    print("=" * 130)
    menu7 = ["GROT", "ABS_GROT", "VOL_GROT", "DIP_V2", "FVG_SHORT", "FVG_LS", "BTC_h"]
    ws["BTC_h"] = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    ws["BTC_h"]["BTC"] = 1.0
    w_brain, final_picks = brain(px, ws, menu7, ["ABS_GROT", "FVG_SHORT"])
    rec(f"brain_ABS_SHORT(picks={'/'.join(final_picks)})", w_brain, "L5")
    w_brain2, fp2 = brain(px, ws, menu7,
                          ["GROT", "ABS_GROT", "VOL_GROT", "DIP_V2", "FVG_SHORT"])
    rec(f"brain_eq5(picks={'/'.join(fp2)})", w_brain2, "L5")

    print("\n" + "=" * 130)
    print("L6 STACKS")
    print("=" * 130)
    for tgt, cap in ((0.40, 4.0), (0.50, 4.0), (0.50, 7.0)):
        rec(f"vt{int(tgt*100)}c{int(cap)}_brain_ABS_SHORT",
            volscale(w_brain, px, tgt, cap), "L6")
    rec("vt40c4_ABS_ung+SHORT", volscale(abs_short_ung, px, 0.40, 4.0), "L6")
    for m_ in (1.5, 2.0):
        rec(f"brain_eq5_x{m_}", w_brain2 * m_, "L6")

    print("\n" + "=" * 130)
    print("L4 UNIVERSE CHECK: OLD 21-coin panel 2020-07..2023-04 (period-limited!)")
    print("=" * 130)
    try:
        opx = ra.load_all()
        ws_old, _ = rx.build_full(opx)
        for k in list(ws_old):
            ws_old[k] = ws_old[k].reindex(opx.index).fillna(0.0)
        for name, w in [("ABS_GROT+FVG_SHORT", mix_of(ws_old, ["ABS_GROT", "FVG_SHORT"])),
                        ("eq5_survivors+SHORT", mix_of(ws_old, ["GROT", "ABS_GROT", "VOL_GROT",
                                                                "DIP_V2", "FVG_SHORT"]))]:
            eq, r = sh.portfolio_sim(w, opx, fee=0.0010, lev_cap=2.0)
            m = sh.metrics(eq, r)
            ym = ym_of(eq)
            print(f"  OLD21 {name:<22} {m['monthly_roi']:+6.2f}%/mo DD {m['max_dd']:5.1f} "
                  f"| yearly " + " ".join(f"{str(y)[2:]}:{v:+5.1f}" for y, v in ym.items()))
    except Exception as e:
        print("  old panel unavailable:", e)

    # ------------------------------------------------- selection + verdict
    def best(filter_fn):
        c = [(k, v) for k, v in rows.items() if filter_fn(v)]
        return max(c, key=lambda kv: kv[1]["monthly"]) if c else None

    b35 = best(lambda v: v["dd"] <= 35 and v["stressed"] > 0)
    b50 = best(lambda v: v["dd"] <= 50 and v["stressed"] > 0)
    b6 = best(lambda v: v["monthly"] >= 6.0 and v["stressed"] >= 5.0)
    print("\n" + "=" * 130)
    print("FRONTIER SUMMARY (best monthly at each risk cap, stressed = minus funding band)")
    for lbl, b in (("DD<=35", b35), ("DD<=50", b50), (">=6%/mo", b6)):
        if b:
            print(f"  {lbl:<8} {b[0]:<30} {b[1]['monthly']:+.2f}%/mo  DD {b[1]['dd']}  "
                  f"minYr {b[1]['min_year']}  stressed {b[1]['stressed']:+.2f}")
    print("=" * 130)

    board = json.load(open(BOARD))
    board["exp041_reach6"] = {
        "date": "2026-10-30",
        "question": "how to reach 6%/mo from 1.74% - lever ladder on 5.5y with commission+spread",
        "rows": rows,
        "frontier": {"dd35": b35 and {b35[0]: b35[1]}, "dd50": b50 and {b50[0]: b50[1]},
                     "six_pct": b6 and {b6[0]: b6[1]}},
    }
    json.dump(board, open(BOARD, "w"), indent=2)
    print("saved exp041_reach6")


if __name__ == "__main__":
    main()
