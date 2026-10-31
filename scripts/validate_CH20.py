"""CH-20 Tweezer tops/bottoms (inventory line 247).

Quantified: TWEEZER TOP = two consecutive bars with highs within 0.1*ATR20 of each
other, at a local high (high = 10d max), second bar closes below its midpoint ->
SHORT. TWEEZER BOT (equal lows at 10d low, close above midpoint) -> LONG.
Entry at 2nd bar close, hold H. 10bp/side. BTC/ETH daily 2021-26.
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
        atr20 = (d["high"] - d["low"]).rolling(20).mean()
        mid = (d["high"] + d["low"]) / 2
        eq_high = (d["high"] - d["high"].shift(1)).abs() < 0.1 * atr20
        eq_low = (d["low"] - d["low"].shift(1)).abs() < 0.1 * atr20
        at_top = d["high"] >= d["high"].rolling(10).max()
        at_bot = d["low"] <= d["low"].rolling(10).min()
        reject_dn = d["close"] < mid
        reject_up = d["close"] > mid
        tweezer_top = eq_high & at_top & reject_dn
        tweezer_bot = eq_low & at_bot & reject_up
        for hold in [3, 5, 10]:
            pos = np.zeros(len(d))
            i = 0
            while i < len(d):
                if bool(tweezer_bot.iloc[i]):
                    pos[i:i + hold] = 1.0
                    i += hold
                elif bool(tweezer_top.iloc[i]):
                    pos[i:i + hold] = -1.0
                    i += hold
                else:
                    i += 1
            pos_s = np.concatenate([[0.0], pos[:-1]])
            rets = d["close"].pct_change().fillna(0).values
            pnl = pd.Series(pos_s * rets - np.abs(np.diff(np.concatenate([[0.0], pos_s]))) * COST, index=d.index)
            m = metrics_from_pnl(pnl)
            if m is None:
                print(f"  tweezer_{sym}_h{hold}            [no trades]")
                continue
            pct = placebo_pct(pos, rets, COST, m["sharpe"], d.index)
            key = f"tweezer_{sym}_h{hold}"
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
    json.dump({"unit": "CH-20", "verdict": "PASS" if ok else "FAIL", "pass_nodes": ok, "nodes": out},
              open("reports/validation_CH20.json", "w"), indent=1)


if __name__ == "__main__":
    main()
