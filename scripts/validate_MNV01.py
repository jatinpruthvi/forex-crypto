"""MNV-01 Minervini VCP - volatility contraction pattern (inventory line 281).

Quantified (tradingsim/finwiz): (1) compression ATR10 < 0.6*ATR50; (2) volume dry-up
volume < 0.8*V30; (3) progressive contractions: 20d range < prior 20d range < prior-2
20d range; (4) breakout of final pivot: close > prior 20d high (shift(1)) on volume
> 1.4*V30 (+40%); (5) stop under last contraction low: exit early if close < rolling
20d min (shift 1). Long-only (SEPA). Entry at signal close, hold H or stop-out.
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


def main():
    out = {}
    for sym in ["BTC", "ETH"]:
        d = load(sym)
        spread = d["high"] - d["low"]
        atr10 = spread.rolling(10).mean()
        atr50 = spread.rolling(50).mean()
        v30 = d["volume"].rolling(30).mean()
        r20 = (d["high"].rolling(20).max() - d["low"].rolling(20).min()) / d["close"]
        # spec sequence: dry-up DURING contraction (prior bars), breakout ON +40% volume.
        # (fire-rate diagnosis: requiring dry-up on the breakout bar contradicts vol_confirm
        # by construction -> 0 trades; conditions now live on their spec bars.)
        compression = atr10 < 0.6 * atr50
        dry_prior = d["volume"].rolling(5).mean().shift(1) < 0.8 * v30.shift(1)
        contractions = (r20 < r20.shift(20)) & (r20.shift(20) < r20.shift(40))
        pivot_hi = d["high"].rolling(20).max().shift(1)
        stop_lo = d["low"].rolling(20).min().shift(1)
        breakout = d["close"] > pivot_hi
        vol_confirm = d["volume"] > 1.4 * v30
        pre_state = compression & dry_prior & contractions        # contraction-phase states
        sig = pre_state.shift(1) & breakout & vol_confirm         # signal bar: breakout + volume
        for hold in [5, 10, 20]:
            pos = np.zeros(len(d))
            i = 0
            while i < len(d):
                if bool(sig.iloc[i]):
                    j = i
                    while j < min(i + hold, len(d)):
                        pos[j] = 1.0
                        if j > i and bool(d["close"].iloc[j] < stop_lo.iloc[j]):   # stop under contraction low
                            break
                        j += 1
                    i += hold
                else:
                    i += 1
            pos_s = np.concatenate([[0.0], pos[:-1]])
            rets = d["close"].pct_change().fillna(0).values
            pnl = pd.Series(pos_s * rets - np.abs(np.diff(np.concatenate([[0.0], pos_s]))) * COST, index=d.index)
            m = metrics_from_pnl(pnl)
            if m is None:
                print(f"  vcp_{sym}_h{hold:2d}               [no trades]")
                continue
            mo, sr, dd, myr, nt = m["monthly"], m["sharpe"], m["dd"], m["min_year"], int((pnl != 0).sum())
            pct = placebo_pct(pos, rets, COST, sr, d.index)
            key = f"vcp_{sym}_h{hold}"
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
    json.dump({"unit": "MNV-01", "verdict": "PASS" if ok else "FAIL", "pass_nodes": ok, "nodes": out},
              open("reports/validation_MNV01.json", "w"), indent=1)


if __name__ == "__main__":
    main()
