"""AMT-01 Auction Market Theory: excess vs poor extremes (inventory line 245).

Quantified: extreme = 10d high/low touched at bar t.
POOR extreme (thin, unfinished -> fade the move away from it, i.e. trade TOWARD the
extreme for the retest): volume[t] < 0.7*V30.
  poor_high -> LONG (expect retest/repair of the thin high); poor_low -> SHORT.
EXCESS extreme (heavy, rejected -> follow the rejection): volume[t] > 2*V30 AND the
bar closes off its extreme (close_pos<0.35 for a high, >0.65 for a low).
  excess_high -> SHORT; excess_low -> LONG.
Entry at extreme-bar close, hold H. 10bp/side. BTC/ETH daily 2021-26.
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


def run(sig_long, sig_short, d, hold):
    pos = np.zeros(len(d))
    i = 0
    while i < len(d):
        if bool(sig_long.iloc[i]):
            pos[i:i + hold] = 1.0
            i += hold
        elif bool(sig_short.iloc[i]):
            pos[i:i + hold] = -1.0
            i += hold
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
        spread = (d["high"] - d["low"]).replace(0, np.nan)
        close_pos = ((d["close"] - d["low"]) / spread).fillna(0.5)
        v30 = d["volume"].rolling(30).mean()
        hi10 = d["high"].rolling(10).max()
        lo10 = d["low"].rolling(10).min()
        at_hi = d["high"] >= hi10
        at_lo = d["low"] <= lo10
        thin = d["volume"] < 0.7 * v30
        heavy = d["volume"] > 2 * v30
        poor_long = at_hi & thin              # thin 10d high -> retest up
        poor_short = at_lo & thin             # thin 10d low -> retest down
        excess_long = at_lo & heavy & (close_pos > 0.65)   # rejected 10d low -> up
        excess_short = at_hi & heavy & (close_pos < 0.35)  # rejected 10d high -> down
        variants = {"poor": (poor_long, poor_short), "excess": (excess_long, excess_short)}
        for vname, (lg, sh) in variants.items():
            for hold in [5, 10]:
                pos, rets, pnl = run(lg, sh, d, hold)
                m = metrics_from_pnl(pnl)
                if m is None:
                    print(f"  amt_{vname}_{sym}_h{hold}          [no trades]")
                    continue
                mo, sr, dd, myr, nt = m["monthly"], m["sharpe"], m["dd"], m["min_year"], int((pnl != 0).sum())
                pct = placebo_pct(pos, rets, COST, sr, d.index)
                key = f"amt_{vname}_{sym}_h{hold}"
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
    json.dump({"unit": "AMT-01", "verdict": "PASS" if ok else "FAIL", "pass_nodes": ok, "nodes": out},
              open("reports/validation_AMT01.json", "w"), indent=1)


if __name__ == "__main__":
    main()
