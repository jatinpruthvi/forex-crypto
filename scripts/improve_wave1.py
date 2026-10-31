#!/usr/bin/env python
"""EXP-047 — IMPROVEMENT PLAN Wave 1: I-01 squeeze-family expansion, I-02 timeframe-winner
book blends, I-03 basis-MR sleeve, I-04 book engineering. Real data, 10bp/side, placebo gates."""
import warnings, os, sys
warnings.filterwarnings("ignore")
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import five_year_test as ft, regime_expansion as rx
from nuclear_edges import metrics_from_pnl, pnl_from_weights, cs_weights

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "reports")

def block_permute_idx(n, bs=20, rng=None):
    rng = rng or np.random.default_rng(0)
    starts = list(range(0, n, bs)); rng.shuffle(starts)
    return np.concatenate([np.arange(s, min(s + bs, n)) for s in starts])

def placebo_blend(base_pnl, cand_w, px, cost, n=30, frac=0.25):
    real = (1 - frac) * base_pnl + frac * pnl_from_weights(cand_w, px, cost)
    rs = metrics_from_pnl(real)["sharpe"]; null = []
    for k in range(n):
        wq = cand_w.iloc[block_permute_idx(len(cand_w), 20, np.random.default_rng(100 + k))]
        wq.index = cand_w.index
        nb = (1 - frac) * base_pnl + frac * pnl_from_weights(wq, px, cost)
        null.append(metrics_from_pnl(nb)["sharpe"])
    null = np.asarray(null)
    return rs, float(null.mean()), float(np.percentile(null, 90)), float((null < rs).mean() * 100)

def placebo_standalone(w, px, cost, n=30):
    rs = metrics_from_pnl(pnl_from_weights(w, px, cost))["sharpe"]; null = []
    for k in range(n):
        wq = w.iloc[block_permute_idx(len(w), 20, np.random.default_rng(200 + k))]
        wq.index = w.index
        null.append(metrics_from_pnl(pnl_from_weights(wq, px, cost))["sharpe"])
    null = np.asarray(null)
    return rs, float(null.mean()), float(np.percentile(null, 90)), float((null < rs).mean() * 100)

def eth_4h():
    d = pd.read_parquet("data/intraday/eth_usdt_15m.csv.parquet")
    d["timestamp"] = pd.to_datetime(d["timestamp"])
    d = d.set_index("timestamp").sort_index()
    return d.resample("4h").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()

def fmt(m):
    ys = " ".join(f"{y[2:]}:{x:+5.1f}" for y, x in m["yearly"].items())
    return f"{m['monthly']:+6.2f}%/mo SR {m['sharpe']:+5.2f} DD {m['dd']:5.1f} minYr {m['min_year']:+6.2f} | {ys}"

px = ft.load_all_5y(); idx, cols = px.index, px.columns
C = 0.0010
gate = (px["BTC"] > px["BTC"].rolling(100).mean()).astype(float)

# ---- R3 build (exact) ----
ws_b, _ = rx.build_full(px)
w_mom = cs_weights((px / px.shift(14) - 1), 5, px, gate=gate)
w_base = pd.DataFrame(0.375 * ws_b["ABS_GROT"] + 0.375 * ws_b["FVG_SHORT"]).reindex(idx).fillna(0.0) + 0.25 * cs_weights((px / px.shift(14) - 1), 5, px, gate=gate)
fund = pd.read_csv("data/derivatives/funding_all.csv")
fund["date"] = pd.to_datetime(fund["timestamp_ms"], unit="ms").dt.normalize()
fpiv = fund.pivot_table(index="date", columns="symbol", values="funding_rate", aggfunc="sum")
fpiv.columns = [c.replace("USDT", "") for c in fpiv.columns]
fpiv = fpiv.reindex(idx).fillna(0.0)[cols]
w_fund = cs_weights(fpiv.rolling(7).mean(), 5, px, invert=True)
fund_pnl = pnl_from_weights(w_fund, px) - (w_fund.fillna(0.0) * fpiv).sum(axis=1)
sqz_now = (px["ETH"].pct_change().rolling(10).std() / px["ETH"].pct_change().rolling(50).std() < 0.7)
w_sqz_now = pd.DataFrame(0.0, index=idx, columns=cols)
w_sqz_now["ETH"] = sqz_now.astype(float) * np.sign(px["ETH"] / px["ETH"].shift(30) - 1)
R3 = 0.5625 * pnl_from_weights(w_base, px, C) + 0.1875 * fund_pnl + 0.25 * pnl_from_weights(w_sqz_now, px, C)
print("R3 baseline:", fmt(metrics_from_pnl(R3)))

res = {}

# ================= I-01 / I-05: squeeze family expansion =================
print("\n===== I-01 squeeze-family grid (daily) =====")
rows = []
for a in ["BTC", "ETH"]:
    c = px[a]; r = c.pct_change()
    for (n1, n2) in [(5, 30), (10, 50), (20, 100)]:
        for th in [0.6, 0.7, 0.8]:
            for dsh in [20, 30, 60]:
                ratio = r.rolling(n1).std() / r.rolling(n2).std()
                sig = (ratio < th).astype(float) * np.sign(c / c.shift(dsh) - 1)
                w = pd.DataFrame(0.0, index=idx, columns=cols); w[a] = sig
                m = metrics_from_pnl(pnl_from_weights(w, px, C))
                rows.append((f"sqz_{n1}_{n2}_{th}_{dsh}_{a}", m, w))
# common (market-wide) squeeze + EW basket squeeze
rb = px.pct_change().mean(axis=1)
c_ew = px.mean(axis=1) / px.mean(axis=1).iloc[0]
r_ew = c_ew.pct_change()
for (n1, n2) in [(5, 30), (10, 50), (20, 100)]:
    for th in [0.6, 0.7, 0.8]:
        for dsh in [20, 30, 60]:
            ratio = r_ew.rolling(n1).std() / r_ew.rolling(n2).std()
            sig = (ratio < th).astype(float) * np.sign(c_ew / c_ew.shift(dsh) - 1)
            w = pd.DataFrame(np.repeat(sig.values[:, None], len(cols), axis=1) * gate.values[:, None],
                             index=idx, columns=cols) / 3.0
            m = metrics_from_pnl(pnl_from_weights(w, px, C))
            rows.append((f"sqz_EW_{n1}_{n2}_{th}_{dsh}", m, w))
for th in [0.6, 0.7, 0.8]:
    for dsh in [20, 30, 60]:
        ratio = rb.rolling(10).std() / rb.rolling(50).std()
        sig = (ratio < th).astype(float) * np.sign(rb / rb.rolling(dsh).mean() - 1)
        w = pd.DataFrame(np.repeat(sig.values[:, None], len(cols), axis=1) * gate.values[:, None],
                         index=idx, columns=cols) / 3.0
        m = metrics_from_pnl(pnl_from_weights(w, px, C))
        rows.append((f"sqz_common_{th}_{dsh}", m, w))
rows.sort(key=lambda x: -x[1]["sharpe"])
for n, m, _ in rows[:10]:
    print(f"  {n:28s} {fmt(m)}")
best_name, best_m, best_w = rows[0]
print(f"\n  I-01 standalone placebo [{best_name}]:")
rs, nm, p90, pct = placebo_standalone(best_w, px, C)
print(f"    real SR {rs:.2f} vs null mean {nm:.2f} / p90 {p90:.2f} -> pct {pct:.0f}")
res["I-01"] = {"best": best_name, "metrics": best_m, "placebo": {"real": rs, "null_mean": nm, "p90": p90, "pct": pct},
               "top5": [(n, round(m["monthly"], 2), round(m["sharpe"], 2)) for n, m, _ in rows[:5]]}
# does the best squeeze beat/replace the in-book node? blend test both ways
print("  blend test: best squeeze into R3 @25%:")
rs2, nm2, p902, pct2 = placebo_blend(R3, best_w, px, C, frac=0.25)
mix_best = 0.75 * R3 + 0.25 * pnl_from_weights(best_w, px, C)
print(f"    real SR {rs2:.2f} vs null p90 {p902:.2f} -> pct {pct2:.0f}")
print("    mix metrics:", fmt(metrics_from_pnl(mix_best)))
res["I-01"]["blend25"] = {"real": rs2, "p90": p902, "pct": pct2}
# second candidate: highest-return gate-eligible node
cand_name, cand_m, cand_w = [r for r in rows if r[0] == "sqz_10_50_0.8_30_ETH"][0]
print(f"  blend test: {cand_name} (+{cand_m['monthly']:.2f}%/mo, minYr {cand_m['min_year']:+.2f}) into R3 @25%:")
rs3, nm3, p903, pct3 = placebo_blend(R3, cand_w, px, C, frac=0.25)
mix_c = 0.75 * R3 + 0.25 * pnl_from_weights(cand_w, px, C)
print(f"    real SR {rs3:.2f} vs null p90 {p903:.2f} -> pct {pct3:.0f}")
print("    mix metrics:", fmt(metrics_from_pnl(mix_c)))
res["I-01"]["blend25_b"] = {"node": cand_name, "real": rs3, "p90": p903, "pct": pct3}
# both together: squeeze basket 25% (0.5 each)
w_pair = 0.5 * best_w + 0.5 * cand_w
rs4, nm4, p904, pct4 = placebo_blend(R3, w_pair, px, C, frac=0.25)
mix_p = 0.75 * R3 + 0.25 * pnl_from_weights(w_pair, px, C)
print(f"  blend test: pair (0.5/0.5) into R3 @25%: real SR {rs4:.2f} vs p90 {p904:.2f} -> pct {pct4:.0f}")
print("    mix metrics:", fmt(metrics_from_pnl(mix_p)))
res["I-01"]["blend25_pair"] = {"real": rs4, "p90": p904, "pct": pct4}
# SLOT UPGRADE: replace in-book squeeze node with the pair, keep book size
R3_pair = 0.5625 * pnl_from_weights(w_base, px, C) + 0.1875 * fund_pnl + 0.25 * pnl_from_weights(w_pair, px, C)
print("  SLOT-UPGRADE R3 (pair replaces old squeeze node):", fmt(metrics_from_pnl(R3_pair)))
real_slot = metrics_from_pnl(R3_pair)["sharpe"]; null_slot = []
for k in range(30):
    wq = w_pair.iloc[block_permute_idx(len(w_pair), 20, np.random.default_rng(300 + k))]
    wq.index = w_pair.index
    nb = 0.5625 * pnl_from_weights(w_base, px, C) + 0.1875 * fund_pnl + 0.25 * pnl_from_weights(wq, px, C)
    null_slot.append(metrics_from_pnl(nb)["sharpe"])
null_slot = np.asarray(null_slot)
print(f"    slot placebo: real SR {real_slot:.2f} vs null mean {null_slot.mean():.2f} / p90 {np.percentile(null_slot, 90):.2f} -> pct {(null_slot < real_slot).mean() * 100:.0f}")
res["I-01"]["slot_upgrade"] = {"metrics": metrics_from_pnl(R3_pair),
    "placebo": {"real": float(real_slot), "p90": float(np.percentile(null_slot, 90)), "pct": float((null_slot < real_slot).mean() * 100)}}

# 12h squeeze variant (I-05) from 4h bars x3
print("\n===== I-05 12h squeeze (4h x3) =====")
for a in ["btc", "eth"]:
    if a == "btc":
        p4 = pd.read_csv("data/intraday/btc_usdt_4h.csv", parse_dates=["timestamp"]).set_index("timestamp").sort_index()
    else:
        p4 = eth_4h()
    o12 = p4["open"].resample("12h").first(); c12 = p4["close"].resample("12h").last()
    r12 = c12.pct_change()
    ratio = r12.rolling(10).std() / r12.rolling(50).std()
    sig = (ratio < 0.7).astype(float) * np.sign(c12 / c12.shift(40) - 1)
    pnl12 = sig.shift(1) * r12 - sig.diff().abs() * C
    pnl_d = pnl12.resample("1D").sum().reindex(idx).fillna(0.0)
    m = metrics_from_pnl(pnl_d)
    print(f"  sqz12h_{a.upper():4s} {fmt(m)}")
    res[f"I-05_{a}"] = m

# ================= I-02: timeframe winners into the book =================
print("\n===== I-02 EXP-044 tf winners -> book blends =====")
p4 = eth_4h()
h4, l4, c4 = p4["high"], p4["low"], p4["close"]
pos = pd.Series(0.0, index=c4.index); p = 0.0
for i in range(len(c4)):
    if p == 0:
        if c4.iloc[i] > h4.rolling(55).max().shift(1).iloc[i]: p = 1.0
        elif c4.iloc[i] < l4.rolling(55).min().shift(1).iloc[i]: p = -1.0
    elif p == 1 and c4.iloc[i] < l4.rolling(10).min().shift(1).iloc[i]: p = 0.0
    elif p == -1 and c4.iloc[i] > h4.rolling(10).max().shift(1).iloc[i]: p = 0.0
    pos.iloc[i] = p
don_pnl4 = pos.shift(1) * c4.pct_change() - pos.diff().abs() * C
don_pnl = don_pnl4.resample("1D").sum().reindex(idx).fillna(0.0)
w_don = pd.DataFrame(0.0, index=idx, columns=cols)
w_don["ETH"] = pos.shift(1).resample("1D").last().reindex(idx).ffill().fillna(0.0)
print("  don55_4h_ETH reimpl :", fmt(metrics_from_pnl(don_pnl)))
sma_sig = np.sign(px["ETH"].rolling(20).mean() - px["ETH"].rolling(50).mean())
w_sma = pd.DataFrame(0.0, index=idx, columns=cols); w_sma["ETH"] = sma_sig
sma_pnl = pnl_from_weights(w_sma, px, C)
print("  sma20_50_1d_ETH     :", fmt(metrics_from_pnl(sma_pnl)))
tf_pnl = 0.5 * don_pnl + 0.5 * sma_pnl
w_tf = 0.5 * w_don + 0.5 * w_sma
print("  tf_combo            :", fmt(metrics_from_pnl(tf_pnl)))
for frac in [0.10, 0.20, 0.30]:
    mix = (1 - frac) * R3 + frac * tf_pnl
    print(f"  R3 + {frac:.0%} tf_combo :", fmt(metrics_from_pnl(mix)))
rs, nm, p90, pct = placebo_blend(R3, w_tf, px, C, frac=0.20)
print(f"  blend placebo @20%: real SR {rs:.2f} vs null p90 {p90:.2f} -> pct {pct:.0f}")
res["I-02"] = {"don": metrics_from_pnl(don_pnl), "sma": metrics_from_pnl(sma_pnl),
               "combo": metrics_from_pnl(tf_pnl), "blend20": {"real": rs, "p90": p90, "pct": pct}}

# ================= I-03: basis MR sleeve (perp vs spot daily) =================
print("\n===== I-03 basis-MR sleeve (perp close vs spot close) =====")
spot = px["BTC"]
perp4 = pd.read_csv("data/intraday/btc_usdt_4h.csv", parse_dates=["timestamp"]).set_index("timestamp")["close"]
perp_d = perp4.resample("1D").last()
basis = (perp_d / spot - 1).dropna()
basis = basis.reindex(idx).ffill()
z = (basis - basis.rolling(30).mean()) / basis.rolling(30).std()
w_bas = pd.DataFrame(0.0, index=idx, columns=cols)
w_bas["BTC"] = -np.sign(z) * (z.abs() > 1.0)
print("  basis_MR_BTC :", fmt(metrics_from_pnl(pnl_from_weights(w_bas, px, C))))
rs, nm, p90, pct = placebo_standalone(w_bas, px, C)
print(f"  standalone placebo: real SR {rs:.2f} vs null p90 {p90:.2f} -> pct {pct:.0f}")
rs2, nm2, p902, pct2 = placebo_blend(R3, w_bas, px, C, frac=0.15)
print(f"  blend placebo @15%: real SR {rs2:.2f} vs null p90 {p902:.2f} -> pct {pct2:.0f}")
res["I-03"] = {"metrics": metrics_from_pnl(pnl_from_weights(w_bas, px, C)),
               "placebo": {"real": rs, "p90": p90, "pct": pct}, "blend15": {"real": rs2, "p90": p902, "pct": pct2}}

# ================= I-04: book engineering =================
print("\n===== I-04 book engineering (sleeve weights / vol scaling) =====")
sl = {"base": 0.5625 * pnl_from_weights(w_base, px, C),
      "fund": 0.1875 * fund_pnl,
      "sqz": 0.25 * pnl_from_weights(w_sqz_now, px, C)}
R3_chk = sum(sl.values())
print("  rebuild check:", fmt(metrics_from_pnl(R3_chk)))
vols = {k: v.std() for k, v in sl.items()}
inv = {k: 1.0 / v for k, v in vols.items()}; s = sum(inv.values())
wts = {k: inv[k] / s for k in inv}
print("  current weights: {base: .5625, fund: .1875, sqz: .25}  inv-vol:", {k: round(v, 3) for k, v in wts.items()})
book_iv = sum(wts[k] * (sl[k] / {"base": .5625, "fund": .1875, "sqz": .25}[k]) for k in sl)
print("  inv-vol sleeve book (x1):", fmt(metrics_from_pnl(book_iv)))
for lev in [1.5, 2.0, 2.5]:
    print(f"    inv-vol x{lev}:", fmt(metrics_from_pnl(book_iv * lev)))
# vol-scaled leverage on current R3
tgt = R3.rolling(30).std().shift(1).median()
lev_t = (tgt / R3.rolling(30).std().shift(1)).clip(0.5, 2.0).fillna(1.0)
book_vs = R3 * lev_t
print("  vol-scaled R3 (cap 2x, floor .5x):", fmt(metrics_from_pnl(book_vs)))
res["I-04"] = {"invvol_x1": metrics_from_pnl(book_iv), "invvol_x2": metrics_from_pnl(book_iv * 2),
               "volscaled": metrics_from_pnl(book_vs)}

import json
def clean(o):
    if isinstance(o, dict): return {k: clean(v) for k, v in o.items() if k != "yearly"}
    if isinstance(o, (np.floating,)): return float(o)
    return o
json.dump(clean(res), open(os.path.join(OUT, "improvement_wave1.json"), "w"), indent=1)
print("\nsaved reports/improvement_wave1.json")
