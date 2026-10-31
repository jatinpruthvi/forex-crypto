"""FAMILY F6+F3-lite: SEAS-01/02/03 + HLD-01 (calendar seasonality, daily data).

SEAS-01 Month-of-year: long BTC/ETH Oct 1 - Nov 30 ("Uptober/Nov"), flat else.
SEAS-02 Halloween: long Oct 31 - Apr 30, flat May 1 - Oct 30.
SEAS-03 Lunar NY: short 14d before CNY (pre-selling), long 14d after (re-entry).
  CNY dates (fixed public calendar): 2021-02-12, 2022-02-01, 2023-01-22,
  2024-02-10, 2025-01-29, 2026-02-17.
HLD-01 US holiday: long 2 trading days BEFORE each bank holiday (pre-drift);
  first trading day AFTER = fade the pre-drift direction (reversal).
All: 10bp/side on position changes; house metrics; 200-draw position-permute placebo.
"""
import json
import sys
import numpy as np
import pandas as pd
from pathlib import Path

sys.path.insert(0, "scripts")
from nuclear_edges import metrics_from_pnl

COST = 0.001
CNY = ["2021-02-12", "2022-02-01", "2023-01-22", "2024-02-10", "2025-01-29", "2026-02-17"]
# US bank holidays (observed) 2021-2026
HOLIDAYS = [
    "2021-01-01", "2021-01-18", "2021-02-15", "2021-05-31", "2021-07-05", "2021-09-06", "2021-11-25", "2021-12-24",
    "2022-12-26", "2022-11-24", "2022-09-05", "2022-07-04", "2022-05-30", "2022-02-21", "2022-01-17", "2022-01-03",
    "2023-12-25", "2023-11-23", "2023-09-04", "2023-07-04", "2023-05-29", "2023-02-20", "2023-01-16", "2023-01-02",
    "2024-12-25", "2024-11-28", "2024-09-02", "2024-07-04", "2024-05-27", "2024-02-19", "2024-01-15", "2024-01-01",
    "2025-12-25", "2025-11-27", "2025-09-01", "2025-07-04", "2025-05-26", "2025-02-17", "2025-01-20", "2025-01-01",
    "2026-12-25", "2026-11-26", "2026-09-07", "2026-07-03", "2026-05-25", "2026-02-16", "2026-01-19", "2026-01-01",
]


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


def score(name, pos, d, out):
    pos_s = np.concatenate([[0.0], pos[:-1]])
    rets = d["close"].pct_change().fillna(0).values
    pnl = pd.Series(pos_s * rets - np.abs(np.diff(np.concatenate([[0.0], pos_s]))) * COST, index=d.index)
    m = metrics_from_pnl(pnl)
    if m is None:
        print(f"  {name:24s} [no trades]")
        out[name] = {"monthly": 0, "sr": 0, "dd": 0, "minyr": 0, "trades": 0, "placebo_pct": 0, "gate_fails": ["no-trades"]}
        return
    pct = placebo_pct(pos, rets, COST, m["sharpe"], d.index)
    out[name] = {"monthly": m["monthly"], "sr": m["sharpe"], "dd": m["dd"], "minyr": m["min_year"],
                 "trades": int((pnl != 0).sum()), "placebo_pct": round(pct, 1)}
    print(f"  {name:24s} {m['monthly']:+6.2f}%/mo SR {m['sharpe']:5.2f} DD {m['dd']:5.1f} minYr {m['min_year']:+5.2f} | p{pct:.0f} [{int((pnl != 0).sum())}d]")


def main():
    out = {}
    for sym in ["BTC", "ETH"]:
        d = load(sym)
        idx = d.index
        mo = idx.month
        day = idx.day

        # SEAS-01: Oct-Nov long
        pos = np.where((mo == 10) | (mo == 11), 1.0, 0.0)
        score(f"seas_octnov_{sym}", pos, d, out)

        # SEAS-02: Halloween (Oct 31 - Apr 30 long)
        hal = ((mo == 10) & (day >= 31)) | (mo == 11) | (mo == 12) | (mo <= 4) | ((mo == 4))
        pos = np.where(hal, 1.0, 0.0)
        score(f"seas_halloween_{sym}", pos, d, out)

        # SEAS-03: Lunar NY pre/post
        pos = np.zeros(len(d))
        for c in CNY:
            cd = pd.Timestamp(c)
            pre = (idx >= cd - pd.Timedelta(days=14)) & (idx < cd)
            post = (idx >= cd) & (idx < cd + pd.Timedelta(days=14))
            pos[pre.values] = -1.0
            pos[post.values] = 1.0
        score(f"seas_lunar_{sym}", pos, d, out)

        # HLD-01a: pre-holiday drift (long 2 trading days before)
        pos = np.zeros(len(d))
        for h in HOLIDAYS:
            hd = pd.Timestamp(h)
            prior = idx[idx < hd][-2:]
            pos[idx.get_indexer(prior)] = 1.0
        score(f"hld_predrift_{sym}", pos, d, out)

        # HLD-01b: first-day-after reversal (fade pre-drift direction)
        pos = np.zeros(len(d))
        for h in HOLIDAYS:
            hd = pd.Timestamp(h)
            prior = idx[idx < hd][-2:]
            after = idx[idx > hd][:1]
            if len(prior) and len(after):
                drift = float(d["close"].loc[prior[-1]] / d["close"].loc[prior[0]] - 1) if len(prior) > 1 else 0.0
                pos[idx.get_indexer(after)] = -np.sign(drift) if drift != 0 else 0.0
        score(f"hld_postrev_{sym}", pos, d, out)

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

    # per-unit verdicts
    units = {
        "SEAS-01": [k for k in out if k.startswith("seas_octnov")],
        "SEAS-02": [k for k in out if k.startswith("seas_halloween")],
        "SEAS-03": [k for k in out if k.startswith("seas_lunar")],
        "HLD-01": [k for k in out if k.startswith("hld_")],
    }
    results = {}
    for u, keys in units.items():
        passed = [k for k in keys if k in ok]
        results[u] = {"verdict": "PASS" if passed else "FAIL", "pass_nodes": passed}
        print(f"  {u}: {'PASS ' + str(passed) if passed else 'FAIL'}")
    Path("reports").mkdir(exist_ok=True)
    json.dump({"family": "F6+F3-lite", "units": results, "nodes": out},
              open("reports/validation_SEAS_HLD.json", "w"), indent=1)


if __name__ == "__main__":
    main()
