"""AUDIT #5 Angle 5: END-TO-END DIGIT MATCH for a recorded verdict.

Recompute ALL six ICT-01 (Turtle Soup) nodes from the raw CSV with ZERO repo code
(only pandas/numpy), including the placebo, and compare every recorded field in
reports/validation_ICT01.json digit-for-digit.
"""
import json
import numpy as np
import pandas as pd

COST = 0.001

def metrics_house(pnl):
    """Independent copy of metrics_from_pnl semantics (compounded monthly, sqrt365 SR)."""
    r = pnl.fillna(0.0).replace([np.inf, -np.inf], 0.0)
    d = r.resample("D").sum().dropna(how="all")
    eq = (1 + d).cumprod()
    years = max((d.index[-1] - d.index[0]).days / 365.25, 0.5)
    sharpe = float(d.mean() / max(d.std(), 1e-12) * np.sqrt(365))
    ym = {}
    for y, g in eq.groupby(eq.index.year):
        mm = g.resample("ME").last().pct_change().dropna()
        if len(mm):
            ym[int(y)] = float(((1 + mm).prod() ** (1 / len(mm)) - 1) * 100)
    dd = float((eq / eq.cummax() - 1).min()) * 100
    months = max((eq.index[-1] - eq.index[0]).days / 30.44, 1)
    return {"sharpe": round(sharpe, 2), "monthly": round((float(eq.iloc[-1]) ** (1 / months) - 1) * 100, 2),
            "dd": round(-dd, 1), "min_year": round(min(ym.values()), 2) if ym else None}

def load(sym):
    d = pd.read_csv(f"data/timeframes/1d_panel_5y/{sym}USDT_1d.csv", parse_dates=["date"])
    return d.set_index("date").sort_index()

def block_permute_idx(n, bs=20, rng=None):
    rng = rng or np.random.default_rng(0)
    starts = list(range(0, n, bs)); rng.shuffle(starts)
    return np.concatenate([np.arange(s, min(s + bs, n)) for s in starts])

rec = json.load(open("reports/validation_ICT01.json"))
nodes_rec = rec.get("nodes", rec)
rows = {}
for a in ["BTC", "ETH"]:
    d = load(a)
    hh20 = d["high"].rolling(20).max().shift(1)
    ll20 = d["low"].rolling(20).min().shift(1)
    long_sig = (d["low"] < ll20) & (d["close"] > ll20)
    short_sig = (d["high"] > hh20) & (d["close"] < hh20)
    for hold in (1, 3, 5):
        pos = pd.Series(0.0, index=d.index)
        p, cnt = 0.0, 0
        for i in range(len(d)):
            if long_sig.iloc[i]: p, cnt = 1.0, hold
            elif short_sig.iloc[i]: p, cnt = -1.0, hold
            elif cnt > 0: cnt -= 1
            else: p = 0.0
            pos.iloc[i] = p
        ret = d["close"].pct_change()
        pnl = pos.shift(1) * ret - pos.diff().abs() * COST
        m = metrics_house(pnl)
        # placebo (same design as validator: permute positions, recompute)
        rs = m["sharpe"]; null = []
        for k in range(30):
            pq = pos.iloc[block_permute_idx(len(pos), 20, np.random.default_rng(700 + k))]
            pq.index = pos.index
            null.append(metrics_house(pq.shift(1) * ret - pq.diff().abs() * COST)["sharpe"])
        pct = round(float((np.array(null) < rs).mean() * 100), 1)
        rows[f"turtle_soup_{a}_hold{hold}"] = {**m, "placebo_pct": pct}

# compare digit-for-digit
diffs = []
for name, mine in rows.items():
    ref = nodes_rec.get(name)
    if ref is None:
        diffs.append(f"{name}: MISSING in record"); continue
    for f in ["monthly", "sharpe", "dd", "min_year"]:
        key = {"monthly": "monthly", "sharpe": "sharpe", "dd": "dd", "min_year": "minyr"}.get(f, f)
        rv = ref.get(key, ref.get(f))
        if rv is None and mine.get(f) is None:
            continue
        if rv is None or mine.get(f) is None or abs(float(rv) - float(mine[f])) > 0.011:
            diffs.append(f"{name}.{f}: record={rv} recomputed={mine[f]}")
    rp = ref.get("placebo_pct", ref.get("placebo"))
    if rp is not None and abs(float(rp) - float(mine["placebo_pct"])) > 0.6:
        diffs.append(f"{name}.placebo: record={rp} recomputed={mine['placebo_pct']}")

print("recomputed nodes:")
for k, v in rows.items():
    print(f"  {k:28s} {v['monthly']:+6.2f}%/mo SR {v['sharpe']:5.2f} DD {v['dd']:5.1f} minYr {v['min_year']:+6.2f} p{v['placebo_pct']:.0f}")
print("\nDIGIT COMPARISON vs reports/validation_ICT01.json:")
print("  " + ("\n  ".join(diffs) if diffs else "ALL FIELDS MATCH (tolerance 0.011 on metrics, 0.6 on placebo pct)"))
json.dump({"recomputed": rows, "diffs": diffs,
           "match": not diffs}, open("reports/verify_ict01_e2e.json", "w"), indent=1)
