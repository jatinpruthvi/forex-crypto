"""ICT-04 mitigation (order-block retest): enter on return into displacement-candle origin.

Displacement candle: range > 1.5*ATR10 and close in top/bottom 30% of its range. Block =
[open, low] (bull). When price returns into the block within 10 bars -> long at close, hold H.
Cost 10bp/side. Daily BTC/ETH 2021-25. Null: block-permute daily positions.
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
        atr = (d["high"] - d["low"]).rolling(10).mean()
        rng_c = d["high"] - d["low"]
        bull_disp = (rng_c > 1.5 * atr) & (d["close"] > d["low"] + 0.7 * rng_c)
        bear_disp = (rng_c > 1.5 * atr) & (d["close"] < d["low"] + 0.3 * rng_c)
        bl_top = np.where(bull_disp, d["high"], np.nan)
        bl_bot = np.where(bull_disp, d["open"].where(d["open"] < d["low"], d["low"]), np.nan)
        br_top = np.where(bear_disp, np.maximum(d["open"], d["high"]), np.nan)
        br_bot = np.where(bear_disp, d["low"], np.nan)
        bl_top = pd.Series(bl_top, index=d.index).shift(1).ffill(limit=10)
        bl_bot = pd.Series(bl_bot, index=d.index).shift(1).ffill(limit=10)
        br_top = pd.Series(br_top, index=d.index).shift(1).ffill(limit=10)
        br_bot = pd.Series(br_bot, index=d.index).shift(1).ffill(limit=10)
        long_sig = (d["low"] <= bl_top) & (d["low"] >= bl_bot) & (d["close"] > d["open"])
        short_sig = (d["high"] >= br_bot) & (d["high"] <= br_top) & (d["close"] < d["open"])
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
            for _ in range(30):
                bp = np.concatenate([np.array_split(pnl.values, max(2, len(d) // 20))[j] for j in rng.permutation(max(2, len(d) // 20))])
                srs.append(float(pd.Series(bp).mean() / (pd.Series(bp).std() + 1e-12) * np.sqrt(252)))
            pct = float((np.array(srs) < sr).mean() * 100)
            key = f"mitig_{sym}_h{hold}"
            out[key] = {"monthly": round(mo, 2), "sr": round(sr, 2), "dd": round(dd, 1),
                        "minyr": round(myr, 2), "trades": nt, "placebo_pct": round(pct, 1)}
            print(f"  {key:22s} {mo:+6.2f}%/mo SR {sr:5.2f} DD {dd:5.1f} minYr {myr:+5.2f} | p{pct:.0f} [{nt}d]")
    ok = [k for k, v in out.items() if v["dd"] <= 40 and v["minyr"] >= -1.5 and v["sr"] > 0.5]
    print("  PASS nodes:", ok or "none -> FAIL")
    Path("reports").mkdir(exist_ok=True)
    json.dump({"unit": "ICT-04", "verdict": "PASS" if ok else "FAIL", "nodes": out},
              open("reports/validation_ICT04.json", "w"), indent=1)


if __name__ == "__main__":
    main()
