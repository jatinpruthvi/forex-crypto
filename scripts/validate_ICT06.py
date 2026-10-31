"""ICT-06 NWOG/NDOG (New Week/Day Opening Gap): price reaction to previous period's open.

MR variant: fade today's close deviation from prev week/day open (target = the level).
MOM variant: follow the deviation. Position at close, hold 1 day. Cost 10bp/side.
BTC/ETH 2021-25. Null: block-permute daily positions.
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
                for _ in range(30):
                    bp = np.concatenate([np.array_split(pnl.values, max(2, len(d) // 20))[j] for j in rng.permutation(max(2, len(d) // 20))])
                    srs.append(float(pd.Series(bp).mean() / (pd.Series(bp).std() + 1e-12) * np.sqrt(252)))
                pct = float((np.array(srs) < sr).mean() * 100)
                key = f"{label}_{variant}_{sym}"
                out[key] = {"monthly": round(mo, 2), "sr": round(sr, 2), "dd": round(dd, 1),
                            "minyr": round(myr, 2), "trades": nt, "placebo_pct": round(pct, 1)}
                print(f"  {key:22s} {mo:+6.2f}%/mo SR {sr:5.2f} DD {dd:5.1f} minYr {myr:+5.2f} | p{pct:.0f} [{nt}d]")
    ok = [k for k, v in out.items() if v["dd"] <= 40 and v["minyr"] >= -1.5 and v["sr"] > 0.5]
    print("  PASS nodes:", ok or "none -> FAIL")
    Path("reports").mkdir(exist_ok=True)
    json.dump({"unit": "ICT-06", "verdict": "PASS" if ok else "FAIL", "nodes": out},
              open("reports/validation_ICT06.json", "w"), indent=1)


if __name__ == "__main__":
    main()
