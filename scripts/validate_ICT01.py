#!/usr/bin/env python
"""VALIDATION UNIT ICT-01 — Turtle Soup / liquidity-sweep fade (failed 20d breakout reversal).
Rule (pre-registered): wick through prior-20d extreme that CLOSES back inside -> fade the raid.
LONG:  low_t  < LL20_t (prior 20d low)  and close_t > LL20_t -> long
SHORT: high_t > HH20_t (prior 20d high) and close_t < HH20_t -> short
Execution: decision at close t fills at t+1 (pos.shift(1)). Hold k in {1,3,5}; opposite signal flips.
Data: daily OHLCV BTC/ETH 2021-2026. Cost 10bp/side on |dpos|. Gates: DD<=40, minYr>=-1.5.
AUDIT (quantitative-trading-bug-hunter Tier A): A1 signals use bars <= t, fill t+1; HH/LL shifted 1.
A2 costs on |dpos|; A3 windows identical BTC/ETH; A4 no divisions; A5 block-permute POSITIONS then
recompute pnl; A7 nonzero-position counts printed."""
import warnings, os, sys, json
warnings.filterwarnings("ignore")
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nuclear_edges import metrics_from_pnl

C = 0.0010
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "reports")

def load_daily(sym):
    d = pd.read_csv(f"data/timeframes/1d_panel_5y/{sym}USDT_1d.csv", parse_dates=["date"])
    return d.set_index("date").sort_index()

def fmt(m):
    ys = " ".join(f"{y[2:]}:{x:+5.1f}" for y, x in m["yearly"].items())
    return f"{m['monthly']:+6.2f}%/mo SR {m['sharpe']:+5.2f} DD {m['dd']:5.1f} minYr {m['min_year']:+6.2f} | {ys}"

def block_permute_idx(n, bs=20, rng=None):
    rng = rng or np.random.default_rng(0)
    starts = list(range(0, n, bs)); rng.shuffle(starts)
    return np.concatenate([np.arange(s, min(s + bs, n)) for s in starts])

def placebo_positions(pos, ret, cost, n=30):
    pnl = pos.shift(1) * ret - pos.diff().abs() * cost
    rs = metrics_from_pnl(pnl)["sharpe"]; null = []
    for k in range(n):
        pq = pos.iloc[block_permute_idx(len(pos), 20, np.random.default_rng(700 + k))]
        pq.index = pos.index
        null.append(metrics_from_pnl(pq.shift(1) * ret - pq.diff().abs() * cost)["sharpe"])
    null = np.asarray(null)
    return rs, float(null.mean()), float(np.percentile(null, 90)), float((null < rs).mean() * 100)

res, rows = {}, []
for a in ["BTC", "ETH"]:
    d = load_daily(a)
    hh20 = d["high"].rolling(20).max().shift(1)   # prior 20d high (causal)
    ll20 = d["low"].rolling(20).min().shift(1)    # prior 20d low  (causal)
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
        pnl = pos.shift(1) * ret - pos.diff().abs() * C
        m = metrics_from_pnl(pnl)
        n_trades = int((pos.diff().abs() > 0).sum()); nz = int((pos != 0).sum())
        name = f"turtle_soup_{a}_hold{hold}"
        print(f"  {name:26s} {fmt(m)}  [trades {n_trades}, active days {nz}]")
        rows.append((name, m, pos, ret))

ok = [(n, m, pos, ret) for n, m, pos, ret in rows
      if m["dd"] <= 40 and m["min_year"] >= -1.5 and m["sharpe"] > 0]
best = max(ok, key=lambda r: r[1]["sharpe"]) if ok else max(rows, key=lambda r: r[1]["sharpe"])
bn, bm, bpos, bret = best
print(f"\n  best node: {bn} (gate-eligible: {'yes' if best in ok else 'NO'})")
rs, nm, p90, pct = placebo_positions(bpos, bret, C)
print(f"  standalone placebo: real SR {rs:.2f} vs null mean {nm:.2f} / p90 {p90:.2f} -> pct {pct:.0f}")
verdict = "PASS" if (best in ok and pct >= 90) else "FAIL"
print(f"  VERDICT: {verdict}")
res = {"unit": "ICT-01", "name": "Turtle Soup / liquidity-sweep fade", "nodes_tested": len(rows),
       "nodes": {n: {k: round(v, 3) for k, v in m.items() if k != "yearly"} for n, m, _, _ in rows},
       "best": bn, "placebo": {"real": rs, "null_mean": nm, "p90": p90, "pct": pct},
       "verdict": verdict, "date": "2026-10-30"}
json.dump(res, open(os.path.join(OUT, "validation_ICT01.json"), "w"), indent=1)
print("  saved reports/validation_ICT01.json")
