"""MNV-02 Minervini Trend Template (SEPA filter) as a GATE (inventory line 282).

SEPA gate: close > MA150 AND close > MA200 AND MA200 rising (MA200 > MA200.shift(20))
AND near 52w high (close > 0.75*rolling252d max) AND relative strength (120d return > 0).
Unit semantics: the gate must IMPROVE a base system. Base = long-only Donchian 20d
breakout (close > prior 20d high, exit close < prior 10d low, hold max 20). Nodes:
{base, gated} x BTC/ETH. PASS = gated node passes standard gates AND SR(gated)>SR(base).
10bp/side. 200-draw position-permute placebo.
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


def placebo_pct(pos, ret, cost, sr_real, n=200, seed=7):
    rng = np.random.default_rng(seed)
    nblk = max(2, len(pos) // 20)
    srs = []
    for _ in range(n):
        blocks = np.array_split(np.arange(len(pos)), nblk)
        perm = np.concatenate([blocks[j] for j in rng.permutation(nblk)])
        pq = pos[perm]
        pq_s = np.concatenate([[0.0], pq[:-1]])
        bp = pd.Series(pq_s * ret - np.abs(np.diff(np.concatenate([[0.0], pq_s]))) * cost, index=d.index)
        m = metrics_from_pnl(bp)
        srs.append(m["sharpe"] if m else -9.0)
    return float((np.array(srs) < sr_real).mean() * 100)


def run_node(d, sepa_gate, hold=20):
    entry = d["close"] > d["high"].rolling(20).max().shift(1)
    exit_sig = d["close"] < d["low"].rolling(10).min().shift(1)
    pos = np.zeros(len(d))
    i = 0
    while i < len(d):
        if bool(entry.iloc[i]) and bool(sepa_gate.iloc[i]):
            j = i
            while j < min(i + hold, len(d)):
                pos[j] = 1.0
                if j > i and bool(exit_sig.iloc[j]):
                    break
                j += 1
            i += 1     # allow re-entry after exit
        else:
            i += 1
    pos_s = np.concatenate([[0.0], pos[:-1]])
    rets = d["close"].pct_change().fillna(0).values
    pnl = pd.Series(pos_s * rets - np.abs(np.diff(np.concatenate([[0.0], pos_s]))) * COST, index=d.index)
    return pos, rets, pnl


def main():
    out = {}
    for sym in ["BTC", "ETH"]:
        d = load(sym)
        ma150 = d["close"].rolling(150).mean()
        ma200 = d["close"].rolling(200).mean()
        sepa = ((d["close"] > ma150) & (d["close"] > ma200)
                & (ma200 > ma200.shift(20))
                & (d["close"] > 0.75 * d["high"].rolling(252).max())
                & (d["close"] / d["close"].shift(120) - 1 > 0))
        always = pd.Series(True, index=d.index)
        for label, gate_ in [("base", always), ("gated", sepa)]:
            pos, rets, pnl = run_node(d, gate_)
            m = metrics_from_pnl(pnl)
            if m is None:
                print(f"  {label}_{sym:4s}               [no trades]")
                continue
            mo, sr, dd, myr, nt = m["monthly"], m["sharpe"], m["dd"], m["min_year"], int((pnl != 0).sum())
            pct = placebo_pct(pos, rets, COST, sr)
            key = f"sepa_{label}_{sym}"
            out[key] = {"monthly": round(mo, 2), "sr": round(sr, 2), "dd": round(dd, 1),
                        "minyr": round(myr, 2), "trades": nt, "placebo_pct": round(pct, 1)}
            print(f"  {key:22s} {mo:+6.2f}%/mo SR {sr:5.2f} DD {dd:5.1f} minYr {myr:+5.2f} | p{pct:.0f} [{nt}d]")
    # gate semantics: gated must beat its base on SR AND pass standard gates
    ok = []
    for sym in ["BTC", "ETH"]:
        g, b = out.get(f"sepa_gated_{sym}"), out.get(f"sepa_base_{sym}")
        if not g or not b:
            continue
        fails = []
        if g["dd"] > 40: fails.append("DD")
        if g["minyr"] < -1.5: fails.append("minYr")
        if g["sr"] <= 0.5: fails.append("SR")
        if g["placebo_pct"] < 90: fails.append(f"placebo p{g['placebo_pct']:.0f}")
        if g["sr"] <= b["sr"]: fails.append(f"gate-no-improvement(SR {g['sr']} vs base {b['sr']})")
        g["gate_fails"] = fails
        b["gate_fails"] = ["(base node)"]
        if not fails: ok.append(f"sepa_gated_{sym}")
    print("  PASS nodes:", ok or "none -> FAIL")
    Path("reports").mkdir(exist_ok=True)
    json.dump({"unit": "MNV-02", "verdict": "PASS" if ok else "FAIL", "pass_nodes": ok, "nodes": out},
              open("reports/validation_MNV02.json", "w"), indent=1)


if __name__ == "__main__":
    main()
