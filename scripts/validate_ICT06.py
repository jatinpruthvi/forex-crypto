"""ICT-06 NWOG/NDOG (New Week/Day Opening Gap): price reaction to previous period's open.

MR variant: fade today's close deviation from prev week/day open (target = the level).
MOM variant: follow the deviation. Position at close, hold 1 day. Cost 10bp/side.
BTC/ETH 2021-25. Null: block-permute daily positions.
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
        prev_wk_open = d["open"].resample("W").first().shift(1).reindex(d.index, method="ffill")
        prev_dy_open = d["open"].shift(1)
        ret = d["close"].pct_change().fillna(0)
        for label, ref in [("NWOG", prev_wk_open), ("NDOG", prev_dy_open)]:
            dev = (d["close"] - ref) / ref
            for variant, sign in [("MR", -1), ("MOM", 1)]:
                pos = np.sign(dev) * sign
                pos[dev.abs() < 0.005] = 0.0    # deadband: only meaningful gaps
                pos = pos.shift(1).fillna(0)    # trade next day after observing deviation
                pnl = pd.Series(pos * ret - pos.diff().abs().fillna(0) * COST, index=d.index)
                mo, sr, dd, myr, nt = metrics(pnl)
                rng = np.random.default_rng(7)
                srs = []
                nblk = max(2, len(d) // 20)
                for _ in range(30):
                    blocks = np.array_split(np.arange(len(d)), nblk)
                    perm = np.concatenate([blocks[j] for j in rng.permutation(nblk)])
                    pq = pos.iloc[perm].copy()                # BLOCK-PERMUTE POSITIONS (binding null design)
                    pq.index = pos.index
                    bp = pd.Series(pq * ret - pq.diff().abs().fillna(0) * COST, index=d.index)
                    m = metrics_from_pnl(bp)
                    srs.append(m["sharpe"] if m else -9.0)
                pct = float((np.array(srs) < sr).mean() * 100)
                key = f"{label}_{variant}_{sym}"
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
    json.dump({"unit": "ICT-06", "verdict": "PASS" if ok else "FAIL", "nodes": out},
              open("reports/validation_ICT06.json", "w"), indent=1)


if __name__ == "__main__":
    main()
