"""ICT-05 Turtle Soup CONFIRMED: sweep of 20d low with strong rejection close (>low+0.25*ATR),
close back inside range. Stricter than ICT-01. Long, hold H. Cost 10bp/side. BTC/ETH 2021-25.
"""
import json
import numpy as np
import pandas as pd
from pathlib import Path
import sys
sys.path.insert(0, "scripts")
from nuclear_edges import metrics_from_pnl

COST = 0.001


def load(sym):
    d = pd.read_csv(f"data/timeframes/1d_panel_5y/{sym}USDT_1d.csv", parse_dates=["date"])
    d = d.drop_duplicates("date").sort_values("date").set_index("date")
    return d.loc["2021-01-01":]


def metrics(pnl):
    """House units via metrics_from_pnl: monthly = compounded %/mo, sr sqrt(365),
    min_year = worst-year geometric mean monthly (%/mo) -- gate -1.5 lives in THESE units."""
    m = metrics_from_pnl(pnl)
    if m is None:
        return None
    return m["monthly"], m["sharpe"], m["dd"], m["min_year"], int((pnl != 0).sum())


def main():
    out = {}
    for sym in ["BTC", "ETH"]:
        d = load(sym)
        h20 = d["high"].rolling(20).max().shift(1)
        l20 = d["low"].rolling(20).min().shift(1)
        atr = (d["high"] - d["low"]).rolling(10).mean()
        short_sig = (d["high"] > h20) & (d["close"] < h20 - 0.25 * atr) & (d["close"] < h20) & (d["close"] > l20)
        long_sig = (d["low"] < l20) & (d["close"] > l20 + 0.25 * atr) & (d["close"] > l20) & (d["close"] < h20)
        for hold in [3, 5]:
            pos = np.zeros(len(d))
            i = 0
            while i < len(d):
                if bool(long_sig.iloc[i]):
                    pos[i:i + hold] = 1
                    i += hold
                elif bool(short_sig.iloc[i]):
                    pos[i:i + hold] = -1
                    i += hold
                else:
                    i += 1
            # entry at signal-day CLOSE -> position earns NEXT day's return (no lookahead)
            pos_s = np.concatenate([[0.0], pos[:-1]])
            raw = pos_s * d["close"].pct_change().fillna(0).values
            chg = np.abs(np.diff(np.concatenate([[0.0], pos_s])))
            pnl = pd.Series(raw - chg * COST, index=d.index)
            mo, sr, dd, myr, nt = metrics(pnl)
            rng = np.random.default_rng(7)
            srs = []
            nblk = max(2, len(d) // 20)
            rets = d["close"].pct_change().fillna(0).values
            for _ in range(30):
                blocks = np.array_split(np.arange(len(d)), nblk)
                perm = np.concatenate([blocks[j] for j in rng.permutation(nblk)])
                pq = pos[perm]                                # BLOCK-PERMUTE POSITIONS (binding null design)
                pq_s = np.concatenate([[0.0], pq[:-1]])
                bp = pd.Series(pq_s * rets - np.abs(np.diff(np.concatenate([[0.0], pq_s]))) * COST, index=d.index)
                m = metrics_from_pnl(bp)
                srs.append(m["sharpe"] if m else -9.0)
            pct = float((np.array(srs) < sr).mean() * 100)
            key = f"tsoup2_{sym}_h{hold}"
            out[key] = {"monthly": round(mo, 2), "sr": round(sr, 2), "dd": round(dd, 1),
                        "minyr": round(myr, 2), "trades": nt, "placebo_pct": round(pct, 1)}
            print(f"  {key:22s} {mo:+6.2f}%/mo SR {sr:5.2f} DD {dd:5.1f} minYr {myr:+5.2f} | p{pct:.0f} [{nt}d]")
    ok = [k for k, v in out.items()
          if v["dd"] <= 40 and v["minyr"] >= -1.5 and v["sr"] > 0.5 and v["placebo_pct"] >= 90]
    for k, v in out.items():
        fails = []
        if v["dd"] > 40: fails.append("DD")
        if v["minyr"] < -1.5: fails.append("minYr")
        if v["sr"] <= 0.5: fails.append("SR")
        if v["placebo_pct"] < 90: fails.append(f"placebo p{v['placebo_pct']:.0f}")
        v["gate_fails"] = fails
    print("  PASS nodes:", ok or "none -> FAIL")
    Path("reports").mkdir(exist_ok=True)
    json.dump({"unit": "ICT-05", "verdict": "PASS" if ok else "FAIL", "nodes": out},
              open("reports/validation_ICT05.json", "w"), indent=1)


if __name__ == "__main__":
    main()
