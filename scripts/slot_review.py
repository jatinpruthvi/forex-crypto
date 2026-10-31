"""EXP-059 SLOT REVIEW: can the near-miss slate earn a slot inside champion book R3.1?

Candidates (all with verified rules from their validators):
  C1 ote_BTC_h8    - ICT-03 OTE retracement, both sides, BTC, hold 8
  C2 darvas_h10    - DAR-01 Darvas breakout + volume confirm, BTC+ETH 50/50
  C3 qm_ETH_h5     - ICT-10 Quasimodo short-side, ETH, hold 5
  C4 sepa_gated_BTC - MNV-02 SEPA-gated Donchian, BTC (long-only)

Blend: book_l = (1-l)*R31 + l*C for l in {0.10, 0.15, 0.20}; plus 4-way slate at 5% each.
PRE-REGISTERED ADOPTION: blend SR > base SR AND blend minYr >= base minYr AND
slot placebo >= 90th (block-permuted candidate positions) AND 2024-26 half SR > 0
(recency guard). Split-half reported regardless.
"""
import json
import sys
import numpy as np
import pandas as pd
from pathlib import Path

sys.path.insert(0, "scripts")
import five_year_test as ft
import regime_expansion as rx
from nuclear_edges import cs_weights, metrics_from_pnl

C = 0.0010


def pnl_pos(pos, close):
    pos_s = np.concatenate([[0.0], pos[:-1]])
    ret = close.pct_change().fillna(0).values
    return pd.Series(pos_s * ret - np.abs(np.diff(np.concatenate([[0.0], pos_s]))) * C, index=close.index)


# ---------- champion book R3.1 (verified formulas) ----------
px = ft.load_all_5y()
idx, cols = px.index, px.columns
gate = (px["BTC"] > px["BTC"].rolling(100).mean()).astype(float)
ws_b, _ = rx.build_full(px)
w_mom = cs_weights((px / px.shift(14) - 1), 5, px, gate=gate)
w_base = pd.DataFrame(0.375 * ws_b["ABS_GROT"] + 0.375 * ws_b["FVG_SHORT"]).reindex(idx).fillna(0.0) + 0.25 * w_mom
fund = pd.read_csv("data/derivatives/funding_all.csv")
fund["date"] = pd.to_datetime(fund["timestamp_ms"], unit="ms").dt.normalize()
fpiv = fund.pivot_table(index="date", columns="symbol", values="funding_rate", aggfunc="sum")
fpiv.columns = [c.replace("USDT", "") for c in fpiv.columns]
fpiv = fpiv.reindex(idx).fillna(0.0)[cols]
w_fund = cs_weights(fpiv.rolling(7).mean(), 5, px, invert=True)


def pnl_fresh(w, fee):
    w = w.fillna(0.0)
    fwd = px.pct_change().shift(-1)
    return (w * fwd).sum(axis=1) - w.diff().abs().sum(axis=1) * fee


fund_pnl = pnl_fresh(w_fund, 0.0) - (w_fund.fillna(0.0) * fpiv).sum(axis=1)


def sqz_w(n1, n2, th, dsh):
    c = px["ETH"]; r = c.pct_change()
    sig = (r.rolling(n1).std() / r.rolling(n2).std() < th).astype(float) * np.sign(c / c.shift(dsh) - 1)
    w = pd.DataFrame(0.0, index=idx, columns=cols); w["ETH"] = sig
    return w


w_sqz = 0.5 * sqz_w(20, 100, 0.7, 30) + 0.5 * sqz_w(10, 50, 0.8, 30)
book = 0.5625 * pnl_fresh(w_base, C) + 0.1875 * fund_pnl + 0.25 * pnl_fresh(w_sqz, C)
book = book.reindex(idx).fillna(0.0)

# ---------- candidates ----------
def load1d(sym):
    d = pd.read_csv(f"data/timeframes/1d_panel_5y/{sym}USDT_1d.csv", parse_dates=["date"])
    d = d.drop_duplicates("date").sort_values("date").set_index("date").loc["2021-01-01":]
    return d


cands = {}

# C1: OTE both-sides BTC hold 8 (exact validate_ICT03 rule)
d = load1d("BTC")
hi = d["high"].rolling(20).max().shift(1); lo = d["low"].rolling(20).min().shift(1)
hi_age = hi.rolling(5).max() == hi; lo_age = lo.rolling(5).min() == lo
sma = d["close"].rolling(50).mean(); leg = hi - lo
up_t = d["close"] > sma; dn_t = d["close"] < sma
long_sig = up_t & hi_age & (leg > 0.08 * hi) & (d["low"] <= hi - 0.62 * leg) & (d["low"] >= hi - 0.79 * leg)
short_sig = dn_t & lo_age & (leg > 0.08 * hi) & (d["high"] >= lo + 0.62 * leg) & (d["high"] <= lo + 0.79 * leg)
pos = np.zeros(len(d)); i = 0
while i < len(d):
    if bool(long_sig.iloc[i]): pos[i:i + 8] = 1.0; i += 8
    elif bool(short_sig.iloc[i]): pos[i:i + 8] = -1.0; i += 8
    else: i += 1
cands["ote_BTC_h8"] = (pnl_pos(pos, d["close"]).reindex(idx).fillna(0.0), pos, d)


# C2: Darvas h10 BTC+ETH 50/50 (exact validate_DAR01 rule)
dv_pnls = []
dv_pos = {}
for sym in ["BTC", "ETH"]:
    d2 = load1d(sym)
    v30 = d2["volume"].rolling(30).mean()
    pivot_hi = d2["high"].rolling(20).max().shift(1)
    stop_lo = d2["low"].rolling(10).min().shift(1)
    brk = (d2["close"] > pivot_hi) & (d2["volume"] > 1.5 * v30)
    p2 = np.zeros(len(d2)); i = 0
    while i < len(d2):
        if bool(brk.iloc[i]):
            j = i
            while j < min(i + 10, len(d2)):
                p2[j] = 1.0
                if j > i and bool(d2["close"].iloc[j] < stop_lo.iloc[j]): break
                j += 1
            i += 1
        else:
            i += 1
    dv_pnls.append(pnl_pos(p2, d2["close"]).reindex(idx).fillna(0.0))
    dv_pos[sym] = p2
cands["darvas_h10"] = ((dv_pnls[0] + dv_pnls[1]) / 2.0, dv_pos["BTC"], load1d("BTC"))


# C3: Quasimodo short-only ETH h5 (exact validate_ICT10 rule)
d3 = load1d("ETH")
hi3, lo3, cl3 = d3["high"].values, d3["low"].values, d3["close"].values
n3 = len(d3)
short_sig3 = np.zeros(n3, dtype=bool)
for t in range(30, n3 - 1):
    w0, w1 = t - 12, t - 4
    j = w0 + int(np.argmax(hi3[w0:w1 + 1])); head = hi3[j]
    if head < hi3[max(0, t - 20):t + 1].max() or j < 5: continue
    ls_low = lo3[j - 5:j - 1].min()
    trough = lo3[j + 1:t + 1].min() if t > j + 1 else np.nan
    if not np.isfinite(trough) or trough >= ls_low: continue
    rng_head = head - trough
    if rng_head <= 0: continue
    retr = (cl3[t] - trough) / rng_head
    if 0.62 <= retr <= 1.0 and hi3[t] <= head: short_sig3[t] = True
pos3 = np.zeros(n3); i = 0
while i < n3:
    if short_sig3[i]: pos3[i:i + 5] = -1.0; i += 5
    else: i += 1
cands["qm_ETH_h5"] = (pnl_pos(pos3, d3["close"]).reindex(idx).fillna(0.0), pos3, d3)


# C4: SEPA-gated Donchian BTC (exact validate_MNV02 gated rule)
d4 = load1d("BTC")
ma150 = d4["close"].rolling(150).mean(); ma200 = d4["close"].rolling(200).mean()
sepa = ((d4["close"] > ma150) & (d4["close"] > ma200) & (ma200 > ma200.shift(20))
        & (d4["close"] > 0.75 * d4["high"].rolling(252).max())
        & (d4["close"] / d4["close"].shift(120) - 1 > 0))
entry = d4["close"] > d4["high"].rolling(20).max().shift(1)
exit_sig = d4["close"] < d4["low"].rolling(10).min().shift(1)
pos4 = np.zeros(len(d4)); i = 0
while i < len(d4):
    if bool(entry.iloc[i]) and bool(sepa.iloc[i]):
        j = i
        while j < min(i + 20, len(d4)):
            pos4[j] = 1.0
            if j > i and bool(exit_sig.iloc[j]): break
            j += 1
        i += 1
    else:
        i += 1
cands["sepa_gated_BTC"] = (pnl_pos(pos4, d4["close"]).reindex(idx).fillna(0.0), pos4, d4)


# ---------- evaluation ----------
def slot_placebo(cand_pnl, pos_c, d_c, book, lam, n=200, seed=11):
    real = (1 - lam) * book + lam * cand_pnl
    rs = metrics_from_pnl(real)["sharpe"]
    rng = np.random.default_rng(seed)
    nblk = max(2, len(d_c) // 20)
    srs = []
    for _ in range(n):
        blocks = np.array_split(np.arange(len(d_c)), nblk)
        perm = np.concatenate([blocks[j] for j in rng.permutation(nblk)])
        pq = pos_c[perm]
        bp = pnl_pos(pq, d_c["close"]).reindex(idx).fillna(0.0)
        bl = (1 - lam) * book + lam * bp
        m = metrics_from_pnl(bl)
        srs.append(m["sharpe"] if m else -9.0)
    return rs, float((np.array(srs) < rs).mean() * 100)


def split_srs(series):
    o = {}
    for lab, sl in [("21-23", slice("2021-01-01", "2023-12-31")), ("24-26", slice("2024-01-01", "2026-12-31"))]:
        m = metrics_from_pnl(series.loc[sl])
        o[lab] = round(m["sharpe"], 2) if m else None
    return o


base_m = metrics_from_pnl(book)
base_split = split_srs(book)
print(f"BASELINE R3.1 x1: {base_m['monthly']:+.2f}%/mo SR {base_m['sharpe']:.2f} DD {base_m['dd']:.1f} minYr {base_m['min_year']:+.2f} | halves {base_split}\n")

results = {"baseline": {"monthly": base_m["monthly"], "sr": base_m["sharpe"], "dd": base_m["dd"],
                        "minyr": base_m["min_year"], "split_sr": base_split}}
adopted = []
for name, (cpnl, pos_c, d_c) in cands.items():
    cm = metrics_from_pnl(cpnl)
    print(f"CANDIDATE {name}: standalone {cm['monthly']:+.2f}%/mo SR {cm['sharpe']:.2f} DD {cm['dd']:.1f} minYr {cm['min_year']:+.2f}")
    for lam in [0.10, 0.15, 0.20]:
        blend = (1 - lam) * book + lam * cpnl
        bm = metrics_from_pnl(blend)
        sr_real, pct = slot_placebo(cpnl, pos_c, d_c, book, lam)
        sp = split_srs(blend)
        adopt = (bm["sharpe"] > base_m["sharpe"] and bm["min_year"] >= base_m["min_year"]
                 and pct >= 90 and (sp["24-26"] is not None and sp["24-26"] > 0))
        tag = "ADOPT" if adopt else "reject"
        print(f"  l={lam:.2f}: {bm['monthly']:+.2f}%/mo SR {bm['sharpe']:.2f} DD {bm['dd']:.1f} minYr {bm['min_year']:+.2f} | slot-p{pct:.0f} | halves {sp} -> {tag}")
        results[f"{name}@{lam}"] = {"monthly": bm["monthly"], "sr": bm["sharpe"], "dd": bm["dd"],
                                    "minyr": bm["min_year"], "slot_placebo_pct": pct, "split_sr": sp,
                                    "adopt": bool(adopt)}
        if adopt:
            adopted.append((name, lam, bm["sharpe"]))
    print()

# 4-way slate at 5% each
slate_pnl = sum(cp for cp, _, _ in cands.values()) / len(cands)
blend = 0.80 * book + 0.20 * slate_pnl
bm = metrics_from_pnl(blend)
sp = split_srs(blend)
print(f"SLATE 4x5%: {bm['monthly']:+.2f}%/mo SR {bm['sharpe']:.2f} DD {bm['dd']:.1f} minYr {bm['min_year']:+.2f} | halves {sp}")
results["slate_4x5"] = {"monthly": bm["monthly"], "sr": bm["sharpe"], "dd": bm["dd"],
                        "minyr": bm["min_year"], "split_sr": sp}
print("\nADOPTED SLOTS:", adopted or "NONE")

Path("reports").mkdir(exist_ok=True)
json.dump({"exp": "EXP-059 slot review", "results": results,
           "adopted": [{"candidate": a, "lambda": l, "blend_sr": s} for a, l, s in adopted]},
          open("reports/slot_review.json", "w"), indent=1)
