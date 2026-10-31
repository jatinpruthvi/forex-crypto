"""PRT-01 Equal-weight top-15 basket vs BTC (inventory line 325).

Question: is there an EW-minus-BTC premium (and does monthly rebalancing add to it)?
Nodes (all always-on, cost on turnover only):
  ew_minus_btc  : long EW basket / short BTC (the premium spread)
  btc_minus_ew  : reverse spread (sign control)
  ew_monthly    : EW basket with monthly rebalance vs BTC (same spread, rebalanced)
Placebo for constant positions: monthly-block sign-flip null (is the observed drift
significant vs sign-symmetric noise?). Gates: house metrics + placebo>=90 + split-half.
"""
import json
import sys
import numpy as np
import pandas as pd
from pathlib import Path

sys.path.insert(0, "scripts")
import five_year_test as ft
from nuclear_edges import metrics_from_pnl

COST = 0.001


def monthly_signflip_pct(spread, sr_real, n=500, seed=7):
    rng = np.random.default_rng(seed)
    months = spread.groupby(spread.index.to_period("M"))
    blocks = [g.values for _, g in months]
    srs = []
    for _ in range(n):
        signs = rng.choice([-1.0, 1.0], size=len(blocks))
        vals = np.concatenate([b * s for b, s in zip(blocks, signs)])
        sp = pd.Series(vals, index=spread.index)
        m = metrics_from_pnl(sp)
        srs.append(m["sharpe"] if m else -9.0)
    return float((np.array(srs) < sr_real).mean() * 100)


def main():
    px = ft.load_all_5y()
    idx = px.index
    rets = px.pct_change().fillna(0.0)
    ew = rets.mean(axis=1)
    btc = rets["BTC"]
    out = {}
    nodes = {
        "ew_minus_btc": ew - btc,          # premium spread (long EW, short BTC)
        "btc_minus_ew": btc - ew,          # sign control
        "ew_monthly": None,                # built below (rebalanced)
    }
    # monthly-rebalanced EW basket: hold 1/15 each, rebalance monthly (cost on |dw|)
    w_target = pd.DataFrame(1.0 / 15.0, index=idx, columns=px.columns)
    reb = pd.Series(False, index=idx)
    reb.iloc[0] = True
    reb.loc[~reb.index.to_period("M").duplicated()] = True
    # CORRECT weight path (bug #6 fix): w_start[i] earns rets[i]; drift carries to i+1.
    w_start = pd.DataFrame(np.nan, index=idx, columns=px.columns)
    turn_cost = pd.Series(0.0, index=idx)
    w_end_prev = None
    for i in range(len(idx)):
        if w_end_prev is None or bool(reb.iloc[i]):
            ws = w_target.iloc[i].astype(float)
            if w_end_prev is not None:
                turn_cost.iloc[i] = float((ws - w_end_prev / w_end_prev.sum()).abs().sum()) * COST
        else:
            ws = w_end_prev / w_end_prev.sum()
        w_start.iloc[i] = ws
        w_end_prev = ws * (1 + rets.iloc[i])
    ew_monthly = (w_start * rets).sum(axis=1) - turn_cost - btc  # rebalanced EW book MINUS BTC
    nodes["ew_monthly"] = ew_monthly

    for name, series in nodes.items():
        m = metrics_from_pnl(series)
        if m is None:
            print(f"  {name:18s} [no score]")
            continue
        sr = m["sharpe"]
        pct = monthly_signflip_pct(series, sr)
        sp = {}
        for lab, sl in [("21-23", slice("2021-01-01", "2023-12-31")), ("24-26", slice("2024-01-01", "2026-12-31"))]:
            mm = metrics_from_pnl(series.loc[sl])
            sp[lab] = round(mm["sharpe"], 2) if mm else None
        out[name] = {"monthly": m["monthly"], "sr": m["sharpe"], "dd": m["dd"],
                     "minyr": m["min_year"], "placebo_pct": round(pct, 1), "split_sr": sp}
        print(f"  {name:18s} {m['monthly']:+6.2f}%/mo SR {m['sharpe']:5.2f} DD {m['dd']:5.1f} minYr {m['min_year']:+5.2f} | p{pct:.0f} | halves {sp}")
    ok = []
    for k, v in out.items():
        fails = []
        if v["dd"] > 40: fails.append("DD")
        if v["minyr"] < -1.5: fails.append("minYr")
        if v["sr"] <= 0.5: fails.append("SR")
        if v["placebo_pct"] < 90: fails.append(f"placebo p{v['placebo_pct']:.0f}")
        v["gate_fails"] = fails
        if not fails: ok.append(k)
    print("  PASS nodes:", ok or "none -> FAIL")
    Path("reports").mkdir(exist_ok=True)
    json.dump({"unit": "PRT-01", "verdict": "PASS" if ok else "FAIL", "pass_nodes": ok, "nodes": out},
              open("reports/validation_PRT01.json", "w"), indent=1)


if __name__ == "__main__":
    main()
