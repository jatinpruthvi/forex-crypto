"""ICT-03 OTE (Optimal Trade Entry): retracement into 62-79% of impulse leg, trend direction.

Setup (causal): leg_hi/lo = rolling 20d max/min shift(1); trend = close>SMA50; impulse
recent if leg high made within last 5 bars; long when low enters [hi-0.79*leg, hi-0.62*leg];
short mirror. Exit hold H bars. Cost 10bp/side.
"""
import json
import numpy as np
import pandas as pd
from pathlib import Path

COST = 0.001


def load(sym):
    d = pd.read_csv(f"data/timeframes/1d_panel_5y/{sym}USDT_1d.csv", parse_dates=["date"])
    d = d.drop_duplicates("date").sort_values("date").set_index("date")
    return d.loc["2021-01-01":]


def metrics(pnl):
    eq = (1 + pnl).cumprod()
    dd = float((eq / eq.cummax() - 1).min() * 100)
    yr = pnl.groupby(pnl.index.year).sum() * 100
    tot = float(pnl.sum() * 100)
    n = max((pnl.index[-1] - pnl.index[0]).days / 365.25, 0.1)
    return tot / n, float(pnl.mean() / (pnl.std() + 1e-12) * np.sqrt(252)), dd, float(yr.min()), len(pnl[pnl != 0])


def main():
    out = {}
    for sym in ["BTC", "ETH"]:
        d = load(sym)
        hi = d["high"].rolling(20).max().shift(1)
        lo = d["low"].rolling(20).min().shift(1)
        hi_age = hi.rolling(5).max() == hi          # 20d high touched within 5 bars
        lo_age = lo.rolling(5).min() == lo
        sma = d["close"].rolling(50).mean()
        leg = hi - lo
        up_t = d["close"] > sma
        dn_t = d["close"] < sma
        zone_hi = hi - 0.62 * leg
        zone_lo = hi - 0.79 * leg
        sz_hi = lo + 0.79 * leg
        sz_lo = lo + 0.62 * leg
        long_sig = up_t & hi_age & (leg > 0.08 * hi) & (d["low"] <= zone_hi) & (d["low"] >= zone_lo)
        short_sig = dn_t & lo_age & (leg > 0.08 * hi) & (d["high"] >= sz_lo) & (d["high"] <= sz_hi)
        for hold in [3, 5, 8]:
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
            for _ in range(30):
                k = rng.integers(1, max(2, len(d) // 20))
                bp = np.concatenate([np.array_split(pnl.values, max(2, len(d) // 20))[j] for j in rng.permutation(max(2, len(d) // 20))])
                srs.append(float(pd.Series(bp).mean() / (pd.Series(bp).std() + 1e-12) * np.sqrt(252)))
            pct = float((np.array(srs) < sr).mean() * 100)
            key = f"ote_{sym}_h{hold}"
            out[key] = {"monthly": round(mo, 2), "sr": round(sr, 2), "dd": round(dd, 1),
                        "minyr": round(myr, 2), "trades": nt, "placebo_pct": round(pct, 1)}
            print(f"  {key:22s} {mo:+6.2f}%/mo SR {sr:5.2f} DD {dd:5.1f} minYr {myr:+5.2f} | p{pct:.0f} [{nt}d]")
    ok = [k for k, v in out.items() if v["dd"] <= 40 and v["minyr"] >= -1.5 and v["sr"] > 0.5]
    print("  PASS nodes:", ok or "none -> FAIL")
    Path("reports").mkdir(exist_ok=True)
    json.dump({"unit": "ICT-03", "verdict": "PASS" if ok else "FAIL", "nodes": out},
              open("reports/validation_ICT03.json", "w"), indent=1)


if __name__ == "__main__":
    main()
