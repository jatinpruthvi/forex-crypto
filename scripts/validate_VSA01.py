"""VSA-01 No-demand / no-supply bars (inventory line 237).

Rule (quantified): spread(high-low) < 0.6*ATR20 AND volume < 0.7*V30 (30d avg).
Close position (close-low)/(high-low): no-demand = close_pos>0.6 in an UP leg -> fade short;
no-supply = close_pos<0.4 in a DOWN leg -> fade long. Leg = sign(close/close.shift(5)-1).
Entry at signal close, hold H. 10bp/side. BTC/ETH daily 2021-26.
Placebo: block-permute positions, recompute pnl (200 draws). House metrics gates.
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
        spread = d["high"] - d["low"]
        atr20 = spread.rolling(20).mean()
        v30 = d["volume"].rolling(30).mean()
        close_pos = ((d["close"] - d["low"]) / spread.replace(0, np.nan)).fillna(0.5)
        leg = np.sign(d["close"] / d["close"].shift(5) - 1)
        narrow = spread < 0.6 * atr20
        dry = d["volume"] < 0.7 * v30
        no_dem = narrow & dry & (close_pos > 0.6) & (leg > 0)     # weak up-leg -> short
        no_sup = narrow & dry & (close_pos < 0.4) & (leg < 0)     # weak down-leg -> long
        for hold in [3, 5, 10]:
            pos = np.zeros(len(d))
            i = 0
            while i < len(d):
                if bool(no_sup.iloc[i]):
                    pos[i:i + hold] = 1.0
                    i += hold
                elif bool(no_dem.iloc[i]):
                    pos[i:i + hold] = -1.0
                    i += hold
                else:
                    i += 1
            pos_s = np.concatenate([[0.0], pos[:-1]])
            rets = d["close"].pct_change().fillna(0).values
            pnl = pd.Series(pos_s * rets - np.abs(np.diff(np.concatenate([[0.0], pos_s]))) * COST, index=d.index)
            m = metrics_from_pnl(pnl)
            mo, sr, dd, myr, nt = m["monthly"], m["sharpe"], m["dd"], m["min_year"], int((pnl != 0).sum())
            pct = placebo_pct(pos, rets, COST, sr, d.index)
            key = f"vsa01_{sym}_h{hold}"
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
    json.dump({"unit": "VSA-01", "verdict": "PASS" if ok else "FAIL", "pass_nodes": ok, "nodes": out},
              open("reports/validation_VSA01.json", "w"), indent=1)


if __name__ == "__main__":
    main()
