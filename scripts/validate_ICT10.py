"""ICT-10 Quasimodo (over-under) reversal (inventory line 246).

Quantified (causal, 5-bar swing pivots confirmed 2 bars later via shift):
SHORT setup: head = 20d high made 4-12 bars ago (pivot high); the drop after the head
broke BELOW the prior swing low (the 'under' = 5d low before the head); price then
retraces into 62-100% of the head->low drop at a bar whose high <= head (the 'over'
retest, aligned with the left-shoulder zone) -> SHORT at close.
LONG mirror. Entry at close, hold H. 10bp/side. BTC/ETH daily 2021-26.
200-draw position-permute placebo. House gates.
"""
import json
import sys
import numpy as np
import pandas as pd
from pathlib import Path

sys.path.insert(0, "scripts")
from nuclear_edges import metrics_from_pnl

COST = 0.001


def load(sym):
    d = pd.read_csv(f"data/timeframes/1d_panel_5y/{sym}USDT_1d.csv", parse_dates=["date"])
    d = d.drop_duplicates("date").sort_values("date").set_index("date")
    return d.loc["2021-01-01":]


def placebo_pct(pos, ret, cost, sr_real, idx, n=200, seed=7):
    rng = np.random.default_rng(seed)
    nblk = max(2, len(pos) // 20)
    srs = []
    for _ in range(n):
        blocks = np.array_split(np.arange(len(pos)), nblk)
        perm = np.concatenate([blocks[j] for j in rng.permutation(nblk)])
        pq = pos[perm]
        pq_s = np.concatenate([[0.0], pq[:-1]])
        bp = pd.Series(pq_s * ret - np.abs(np.diff(np.concatenate([[0.0], pq_s]))) * cost, index=idx)
        m = metrics_from_pnl(bp)
        srs.append(m["sharpe"] if m else -9.0)
    return float((np.array(srs) < sr_real).mean() * 100)


def main():
    out = {}
    for sym in ["BTC", "ETH"]:
        d = load(sym)
        hi = d["high"].values
        lo = d["low"].values
        cl = d["close"].values
        n = len(d)
        long_sig = np.zeros(n, dtype=bool)
        short_sig = np.zeros(n, dtype=bool)
        # pivot confirmed at t (2 bars after the extreme bar)
        for t in range(30, n - 1):
            # SHORT: head = rolling 20d high attained 4..12 bars ago
            w0, w1 = t - 12, t - 4
            j = w0 + int(np.argmax(hi[w0:w1 + 1]))
            head = hi[j]
            if head < hi[max(0, t - 20):t + 1].max() or j < 5:
                continue
            ls_low = lo[j - 5:j - 1].min()              # swing low before the head (left shoulder zone)
            drop = cl[t - 1] if False else None
            trough = lo[j + 1:t + 1].min() if t > j + 1 else np.nan
            if not np.isfinite(trough) or trough >= ls_low:
                continue                                 # no 'under' break
            rng_head = head - trough
            if rng_head <= 0:
                continue
            retr = (cl[t] - trough) / rng_head           # retrace into 0.62-1.0 of the drop
            if 0.62 <= retr <= 1.0 and hi[t] <= head:
                short_sig[t] = True
            # LONG mirror
            w0b, w1b = t - 12, t - 4
            jb = w0b + int(np.argmin(lo[w0b:w1b + 1]))
            head_lo = lo[jb]
            if head_lo > lo[max(0, t - 20):t + 1].min() or jb < 5:
                continue
            ls_high = hi[jb - 5:jb - 1].max()
            peak = hi[jb + 1:t + 1].max() if t > jb + 1 else np.nan
            if not np.isfinite(peak) or peak <= ls_high:
                continue
            rng_lo = peak - head_lo
            if rng_lo <= 0:
                continue
            retr_l = (peak - cl[t]) / rng_lo
            if 0.62 <= retr_l <= 1.0 and lo[t] >= head_lo:
                long_sig[t] = True
        long_sig = pd.Series(long_sig, index=d.index)
        short_sig = pd.Series(short_sig, index=d.index)
        for hold in [3, 5, 10]:
            pos = np.zeros(n)
            i = 0
            while i < n:
                if bool(long_sig.iloc[i]):
                    pos[i:i + hold] = 1.0
                    i += hold
                elif bool(short_sig.iloc[i]):
                    pos[i:i + hold] = -1.0
                    i += hold
                else:
                    i += 1
            pos_s = np.concatenate([[0.0], pos[:-1]])
            rets = d["close"].pct_change().fillna(0).values
            pnl = pd.Series(pos_s * rets - np.abs(np.diff(np.concatenate([[0.0], pos_s]))) * COST, index=d.index)
            m = metrics_from_pnl(pnl)
            if m is None:
                print(f"  qm_{sym}_h{hold}                   [no trades]")
                continue
            mo, sr, dd, myr, nt = m["monthly"], m["sharpe"], m["dd"], m["min_year"], int((pnl != 0).sum())
            pct = placebo_pct(pos, rets, COST, sr, d.index)
            key = f"qm_{sym}_h{hold}"
            out[key] = {"monthly": round(mo, 2), "sr": round(sr, 2), "dd": round(dd, 1),
                        "minyr": round(myr, 2), "trades": nt, "placebo_pct": round(pct, 1)}
            print(f"  {key:22s} {mo:+6.2f}%/mo SR {sr:5.2f} DD {dd:5.1f} minYr {myr:+5.2f} | p{pct:.0f} [{nt}d]")
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
    json.dump({"unit": "ICT-10", "verdict": "PASS" if ok else "FAIL", "pass_nodes": ok, "nodes": out},
              open("reports/validation_ICT10.json", "w"), indent=1)


if __name__ == "__main__":
    main()
