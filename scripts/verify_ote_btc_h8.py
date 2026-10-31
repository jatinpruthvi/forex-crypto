"""Audit #3: independent bar-by-bar re-derivation of ote_BTC_h8 (the ICT-03 near-miss).

Written from scratch: explicit trade list, no shared code with validate_ICT03.py.
Rule: leg_hi/lo = rolling 20d max/min (shift 1); trend = close>SMA50; impulse high
touched within 5 bars; leg > 8% of hi; long when low enters [hi-0.79*leg, hi-0.62*leg];
enter at that day's CLOSE; hold 8 days; 10bp/side on position changes.
Checks: (a) metrics match the validator's recorded numbers; (b) split-half stability;
(c) 200-draw position-permute placebo.
"""
import json
import numpy as np
import pandas as pd
import sys
sys.path.insert(0, "scripts")
from nuclear_edges import metrics_from_pnl

COST = 0.001
d = pd.read_csv("data/timeframes/1d_panel_5y/BTCUSDT_1d.csv", parse_dates=["date"])
d = d.drop_duplicates("date").sort_values("date").set_index("date").loc["2021-01-01":]

hi = d["high"].rolling(20).max().shift(1)
lo = d["low"].rolling(20).min().shift(1)
hi_age = hi.rolling(5).max() == hi
sma = d["close"].rolling(50).mean()
leg = hi - lo
up_t = d["close"] > sma
zone_hi = hi - 0.62 * leg
zone_lo = hi - 0.79 * leg
long_sig = up_t & hi_age & (leg > 0.08 * hi) & (d["low"] <= zone_hi) & (d["low"] >= zone_lo)

HOLD = 8
pos = np.zeros(len(d))
i = 0
while i < len(d):
    if bool(long_sig.iloc[i]):
        pos[i:i + HOLD] = 1.0
        i += HOLD
    else:
        i += 1

pos_s = np.concatenate([[0.0], pos[:-1]])
ret = d["close"].pct_change().fillna(0).values
chg = np.abs(np.diff(np.concatenate([[0.0], pos_s])))
pnl = pd.Series(pos_s * ret - chg * COST, index=d.index)
m = metrics_from_pnl(pnl)
print(f"INDEPENDENT ote_BTC_h8: {m['monthly']:+.2f}%/mo SR {m['sharpe']:.2f} DD {m['dd']:.1f} minYr {m['min_year']:+.2f}")
print(f"validator recorded:    +2.50%/mo SR 1.08 DD 26.7 minYr -1.83")

# explicit trade list for spot checks
trades = []
i = 0
while i < len(d):
    if bool(long_sig.iloc[i]):
        entry = d["close"].iloc[i]
        j = min(i + HOLD, len(d) - 1)
        exit_ = d["close"].iloc[j]
        trades.append((str(d.index[i].date()), str(d.index[j].date()), round((exit_ / entry - 1 - 2 * COST) * 100, 2)))
        i += HOLD
    else:
        i += 1
print(f"trades: {len(trades)}; first 3: {trades[:3]}; last 3: {trades[-3:]}")

# split-half: 2021-2023 vs 2024-2026
for label, sl in [("2021-2023", slice("2021-01-01", "2023-12-31")), ("2024-2026", slice("2024-01-01", "2026-12-31"))]:
    mm = metrics_from_pnl(pnl.loc[sl])
    print(f"  {label}: {mm['monthly']:+.2f}%/mo SR {mm['sharpe']:.2f} DD {mm['dd']:.1f} minYr {mm['min_year']:+.2f}")

# 200-draw position-permute placebo
rng = np.random.default_rng(42)
srs = []
nblk = max(2, len(d) // 20)
for _ in range(200):
    blocks = np.array_split(np.arange(len(d)), nblk)
    perm = np.concatenate([blocks[j] for j in rng.permutation(nblk)])
    pq = pos[perm]
    pq_s = np.concatenate([[0.0], pq[:-1]])
    bp = pd.Series(pq_s * ret - np.abs(np.diff(np.concatenate([[0.0], pq_s]))) * COST, index=d.index)
    mm = metrics_from_pnl(bp)
    srs.append(mm["sharpe"] if mm else -9.0)
pct = float((np.array(srs) < m["sharpe"]).mean() * 100)
print(f"200-draw placebo: real SR {m['sharpe']:.2f} vs null mean {np.mean(srs):.2f}/p90 {np.percentile(srs, 90):.2f} -> p{pct:.1f}")

json.dump({"independent_metrics": m, "trades": len(trades),
           "split": {"2021-2023": metrics_from_pnl(pnl.loc['2021':'2023']),
                     "2024-2026": metrics_from_pnl(pnl.loc['2024':'2026'])},
           "placebo_200_pct": pct},
          open("reports/verify_ote_btc_h8.json", "w"), indent=1)
