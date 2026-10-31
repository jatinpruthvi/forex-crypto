"""CH-22 Wolfe waves, simplified 5-point reversal (inventory line 249).

Quantified (causal pivots, 2-bar confirm): BULLISH WW = alternating pivots
p1(L) p2(H) p3(L>p1) p4(H<p2) p5(L) within 60 bars; p5 undercuts the p1-p3 line
by >= 0.3*ATR20 (overshoot); entry LONG at first close back above the p1-p3 line.
BEARISH mirror. TP = point-4 level NOT modeled (documented simplification), hold H.
10bp/side. BTC/ETH daily 2021-26. 200-draw position-permute placebo.
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
        atr20 = (d["high"] - d["low"]).rolling(20).mean().values
        n = len(d)
        ph = [p for p in pivots(hi)]
        pl = [p for p in pivots(lo)]
        long_sig = np.zeros(n, dtype=bool)
        short_sig = np.zeros(n, dtype=bool)
        for p1_i, _ in pl:
            for p2_i, _ in ph:
                if not (p1_i < p2_i <= p1_i + 15):
                    continue
                for p3_i, _ in pl:
                    if not (p2_i < p3_i <= p2_i + 15):
                        continue
                    if lo[p3_i] <= lo[p1_i]:
                        continue
                    for p4_i, _ in ph:
                        if not (p3_i < p4_i <= p3_i + 15):
                            continue
                        if hi[p4_i] >= hi[p2_i]:
                            continue
                        for p5_i, _ in pl:
                            if not (p4_i < p5_i <= p4_i + 15):
                                continue
                            # p1-p3 line at p5's x
                            slope = (lo[p3_i] - lo[p1_i]) / max(p3_i - p1_i, 1)
                            line5 = lo[p1_i] + slope * (p5_i - p1_i)
                            a = atr20[p5_i] if np.isfinite(atr20[p5_i]) else 0
                            if a <= 0:
                                continue
                            if lo[p5_i] < line5 - 0.3 * a:      # overshoot below line
                                for t in range(p5_i + 2, min(p5_i + 15, n)):
                                    if cl[t] > line5 + slope * (t - p5_i):
                                        long_sig[t] = True
                                        break
                            break
                        break
                    break
                break
        # bearish mirror
        for p1_i, _ in ph:
            for p2_i, _ in pl:
                if not (p1_i < p2_i <= p1_i + 15):
                    continue
                for p3_i, _ in ph:
                    if not (p2_i < p3_i <= p2_i + 15):
                        continue
                    if hi[p3_i] >= hi[p1_i]:
                        continue
                    for p4_i, _ in pl:
                        if not (p3_i < p4_i <= p3_i + 15):
                            continue
                        if lo[p4_i] <= lo[p2_i]:
                            continue
                        for p5_i, _ in ph:
                            if not (p4_i < p5_i <= p4_i + 15):
                                continue
                            slope = (hi[p3_i] - hi[p1_i]) / max(p3_i - p1_i, 1)
                            line5 = hi[p1_i] + slope * (p5_i - p1_i)
                            a = atr20[p5_i] if np.isfinite(atr20[p5_i]) else 0
                            if a <= 0:
                                continue
                            if hi[p5_i] > line5 + 0.3 * a:
                                for t in range(p5_i + 2, min(p5_i + 15, n)):
                                    if cl[t] < line5 + slope * (t - p5_i):
                                        short_sig[t] = True
                                        break
                            break
                        break
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
                print(f"  ww_{sym}_h{hold}                    [no trades]")
                continue
            pct = placebo_pct(pos, rets, COST, m["sharpe"], d.index)
            key = f"ww_{sym}_h{hold}"
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
    json.dump({"unit": "CH-22", "verdict": "PASS" if ok else "FAIL", "pass_nodes": ok, "nodes": out},
              open("reports/validation_CH22.json", "w"), indent=1)


if __name__ == "__main__":
    main()
