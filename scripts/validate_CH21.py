"""CH-21 Joe Ross 1-2-3 reversal (inventory line 248).

Quantified (5-bar swing pivots, 2-bar confirmation -> causal):
BEARISH 1-2-3: (1) swing high A; (2) pullback to swing low B; (3) rally to swing high
C with C < A (failure to exceed); trigger = close below B's low -> SHORT.
BULLISH mirror (A low, B high, C higher-low... trigger = close above B's high -> LONG).
Ross-hook second entries NOT modeled (documented simplification).
Entry at trigger close, hold H. 10bp/side. BTC/ETH daily 2021-26.
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


def pivots(vals, k=2):
    """Index list of (i, kind) swing pivots, confirmed k bars after the extreme bar."""
    out = []
    for i in range(k, len(vals) - k):
        w = vals[i - k:i + k + 1]
        if vals[i] == w.max() and (w == w.max()).sum() == 1:
            out.append((i, "H"))
        elif vals[i] == w.min() and (w == w.min()).sum() == 1:
            out.append((i, "L"))
    return out


def main():
    out = {}
    for sym in ["BTC", "ETH"]:
        d = load(sym)
        hi, lo, cl = d["high"].values, d["low"].values, d["close"].values
        n = len(d)
        ph = pivots(hi)
        pl = pivots(lo)
        long_sig = np.zeros(n, dtype=bool)
        short_sig = np.zeros(n, dtype=bool)
        # BEARISH 1-2-3: A(H) -> B(L) -> C(H) with C<A; trigger close < B low
        for a_i, a_v in ph:
            for b_i, b_v in pl:
                if not (a_i < b_i < b_i + 20):
                    continue
                if b_i - a_i > 15:
                    continue
                for c_i, c_v in ph:
                    if not (b_i < c_i <= b_i + 15):
                        continue
                    if c_i <= b_i:
                        continue
                    if hi[c_i] < hi[a_i]:               # C < A: failure to exceed
                        b_low = lo[b_i]
                        # trigger: first close below B's low after C confirms (c_i+2)
                        for t in range(c_i + 2, min(c_i + 15, n)):
                            if cl[t] < b_low:
                                short_sig[t] = True
                                break
                        break
        # BULLISH 1-2-3 mirror
        for a_i, a_v in pl:
            for b_i, b_v in ph:
                if not (a_i < b_i):
                    continue
                if b_i - a_i > 15:
                    continue
                for c_i, c_v in pl:
                    if not (b_i < c_i <= b_i + 15):
                        continue
                    if lo[c_i] > lo[a_i]:
                        b_high = hi[b_i]
                        for t in range(c_i + 2, min(c_i + 15, n)):
                            if cl[t] > b_high:
                                long_sig[t] = True
                                break
                        break
        for hold in [3, 5, 10]:
            pos = np.zeros(n)
            i = 0
            while i < n:
                if long_sig[i]:
                    pos[i:i + hold] = 1.0
                    i += hold
                elif short_sig[i]:
                    pos[i:i + hold] = -1.0
                    i += hold
                else:
                    i += 1
            pos_s = np.concatenate([[0.0], pos[:-1]])
            rets = d["close"].pct_change().fillna(0).values
            pnl = pd.Series(pos_s * rets - np.abs(np.diff(np.concatenate([[0.0], pos_s]))) * COST, index=d.index)
            m = metrics_from_pnl(pnl)
            if m is None:
                print(f"  r123_{sym}_h{hold}                 [no trades]")
                continue
            pct = placebo_pct(pos, rets, COST, m["sharpe"], d.index)
            key = f"r123_{sym}_h{hold}"
            out[key] = {"monthly": m["monthly"], "sr": m["sharpe"], "dd": m["dd"],
                        "minyr": m["min_year"], "trades": int((pnl != 0).sum()), "placebo_pct": round(pct, 1)}
            print(f"  {key:22s} {m['monthly']:+6.2f}%/mo SR {m['sharpe']:5.2f} DD {m['dd']:5.1f} minYr {m['min_year']:+5.2f} | p{pct:.0f} [{int((pnl != 0).sum())}d]")
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
    json.dump({"unit": "CH-21", "verdict": "PASS" if ok else "FAIL", "pass_nodes": ok, "nodes": out},
              open("reports/validation_CH21.json", "w"), indent=1)


if __name__ == "__main__":
    main()
