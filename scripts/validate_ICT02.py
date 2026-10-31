#!/usr/bin/env python
"""VALIDATION UNIT ICT-02 — Judas Swing / Power-of-3 (session-open fake-move fade).
Rule (pre-registered): the first hour after London (08:00 UTC) / NY (13:30 UTC) open is the
'manipulation' leg -> FADE it into the session (distribution leg).
  judas_LDN/NY      : pos = -sign(first-hour return), held 09:00-13:30 / 14:30-20:00 UTC
  judas_LDN/NY_sweep: fade ONLY when the lead move swept the Asia range (00:00-08:00) on its
                      own side (up-move above Asia high -> short; down-move below Asia low -> long)
  judas_combo       : 0.5 * sweep-LDN + 0.5 * sweep-NY positions
Execution: 15m bar close decision, fill next bar (pos.shift(1)); cost 10bp/side on |dpos|.
Data: BTC/ETH 15m 2019-2025. Gates: DD<=40, minYr>=-1.5.
AUDIT (Tier A): A1 lead window strictly precedes trade window; A2 cost on |dpos|; A3 identical
windows per node; A5 placebo block-permutes daily positions, recomputes pnl; A7 counts printed."""
import warnings, os, sys, json
warnings.filterwarnings("ignore")
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import five_year_test as ft
from nuclear_edges import metrics_from_pnl

C = 0.0010
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "reports")

def load_15m(a):
    d = pd.read_parquet(f"data/intraday/{a.lower()}_usdt_15m.csv.parquet")
    d["timestamp"] = pd.to_datetime(d["timestamp"])
    return d.set_index("timestamp").sort_index()

def fmt(m):
    ys = " ".join(f"{y[2:]}:{x:+5.1f}" for y, x in m["yearly"].items())
    return f"{m['monthly']:+6.2f}%/mo SR {m['sharpe']:+5.2f} DD {m['dd']:5.1f} minYr {m['min_year']:+6.2f} | {ys}"

def block_permute_idx(n, bs=20, rng=None):
    rng = rng or np.random.default_rng(0)
    starts = list(range(0, n, bs)); rng.shuffle(starts)
    return np.concatenate([np.arange(s, min(s + bs, n)) for s in starts])

def placebo_daily_pos(pos_d, ret_d, cost, n=30):
    pnl = pos_d.shift(1) * ret_d - pos_d.diff().abs() * cost
    rs = metrics_from_pnl(pnl)["sharpe"]; null = []
    for k in range(n):
        pq = pos_d.iloc[block_permute_idx(len(pos_d), 20, np.random.default_rng(800 + k))]
        pq.index = pos_d.index
        null.append(metrics_from_pnl(pq.shift(1) * ret_d - pq.diff().abs() * cost)["sharpe"])
    null = np.asarray(null)
    return rs, float(null.mean()), float(np.percentile(null, 90)), float((null < rs).mean() * 100)

px = ft.load_all_5y()
idx = px.index
rows = []
for a in ["BTC", "ETH"]:
    d = load_15m(a)
    r15 = d["close"].pct_change()
    day, hod, hom = d.index.normalize(), d.index.hour, d.index.minute
    days = pd.unique(day)

    def trade_pos(lead_mask_fn, trade_mask_fn, sweep=None):
        pos = pd.Series(0.0, index=d.index)
        for dd in days:
            asia = (day == dd) & (hod < 8)
            if asia.sum() < 4: continue
            a_hi = float(d.loc[asia, "high"].max()); a_lo = float(d.loc[asia, "low"].min())
            lead = lead_mask_fn(dd)
            trade = trade_mask_fn(dd)
            if lead.sum() < 2 or trade.sum() < 2: continue
            lret = float(d.loc[lead, "close"].iloc[-1] / d.loc[lead, "close"].iloc[0] - 1)
            if lret == 0: continue
            sig = -np.sign(lret)  # the Judas fade
            if sweep == "up":   # fade only if up-move took Asia high
                if not (float(d.loc[lead, "high"].max()) > a_hi and sig == -1): continue
            elif sweep == "down":
                if not (float(d.loc[lead, "low"].min()) < a_lo and sig == 1): continue
            pos.loc[trade] = sig
        return pos

    ldn_lead = lambda dd: (day == dd) & (hod >= 8) & (hod < 9)
    ldn_trade = lambda dd: (day == dd) & ((hod >= 9) & ((hod < 13) | ((hod == 13) & (hom < 30))))
    ny_lead = lambda dd: (day == dd) & (((hod == 13) & (hom >= 30)) | ((hod == 14) & (hom < 30)))
    ny_trade = lambda dd: (day == dd) & (((hod == 14) & (hom >= 30)) | (hod > 14)) & (hod < 20)

    specs = [
        ("judas_LDN", lambda: trade_pos(ldn_lead, ldn_trade)),
        ("judas_NY", lambda: trade_pos(ny_lead, ny_trade)),
        ("judas_LDN_sweep", lambda: trade_pos(ldn_lead, ldn_trade, sweep="both")),
        ("judas_NY_sweep", lambda: trade_pos(ny_lead, ny_trade, sweep="both")),
    ]
    pos_map = {}
    for nm, fn in specs:
        pos = fn()
        if nm.endswith("_sweep"):
            # sweep on either side: run up- and down-variants and merge
            pu = trade_pos(ldn_lead if "LDN" in nm else ny_lead,
                           ldn_trade if "LDN" in nm else ny_trade, sweep="up")
            pdn = trade_pos(ldn_lead if "LDN" in nm else ny_lead,
                            ldn_trade if "LDN" in nm else ny_trade, sweep="down")
            pos = pu + pdn
        pos_map[nm] = pos
        pnl15 = pos.shift(1) * r15 - pos.diff().abs() * C
        pnl_d = pnl15.resample("1D").sum().reindex(idx).fillna(0.0)
        m = metrics_from_pnl(pnl_d)
        n_tr = int((pos.diff().abs() > 0).sum() / 2)
        print(f"  {nm + '_' + a:22s} {fmt(m)}  [trade-days {n_tr}]")
        rows.append((f"{nm}_{a}", m, pos.resample("1D").last().reindex(idx).fillna(0.0), px[a].pct_change()))
    combo = 0.5 * pos_map["judas_LDN_sweep"] + 0.5 * pos_map["judas_NY_sweep"]
    pnl15 = combo.shift(1) * r15 - combo.diff().abs() * C
    pnl_d = pnl15.resample("1D").sum().reindex(idx).fillna(0.0)
    m = metrics_from_pnl(pnl_d)
    print(f"  {'judas_combo_' + a:16s} {fmt(m)}")
    rows.append((f"judas_combo_{a}", m, combo.resample("1D").last().reindex(idx).fillna(0.0), px[a].pct_change()))

ok = [(n, m, p, r) for n, m, p, r in rows if m["dd"] <= 40 and m["min_year"] >= -1.5 and m["sharpe"] > 0]
best = max(ok, key=lambda r: r[1]["sharpe"]) if ok else max(rows, key=lambda r: r[1]["sharpe"])
bn, bm, bpos, bret = best
print(f"\n  best node: {bn} (gate-eligible: {'yes' if best in ok else 'NO'})")
rs, nm, p90, pct = placebo_daily_pos(bpos, bret, C)
print(f"  standalone placebo: real SR {rs:.2f} vs null mean {nm:.2f} / p90 {p90:.2f} -> pct {pct:.0f}")
verdict = "PASS" if (best in ok and pct >= 90) else "FAIL"
print(f"  VERDICT: {verdict}")
json.dump({"unit": "ICT-02", "name": "Judas Swing / Power-of-3 fade", "nodes_tested": len(rows),
           "nodes": {n: {k: round(v, 3) for k, v in m.items() if k != "yearly"} for n, m, _, _ in rows},
           "best": bn, "placebo": {"real": rs, "null_mean": nm, "p90": p90, "pct": pct},
           "verdict": verdict, "date": "2026-10-30"},
          open(os.path.join(OUT, "validation_ICT02.json"), "w"), indent=1)
print("  saved reports/validation_ICT02.json")
