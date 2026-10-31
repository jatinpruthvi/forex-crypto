#!/usr/bin/env python
"""EXP-048 — IMPROVEMENT PLAN Wave 1.5: I-25 volume profile, I-26 RVOL overlay,
I-27 session strategies (Asian range, session momentum), I-28 session VWAP,
I-06 causal hour seasonality, I-18 weekend effect. 15m bars 2019-2025, 10bp/side."""
import warnings, os, sys, json
warnings.filterwarnings("ignore")
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import five_year_test as ft, regime_expansion as rx
from nuclear_edges import metrics_from_pnl, pnl_from_weights, cs_weights

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "reports")
C = 0.0010

def load_15m(a):
    d = pd.read_parquet(f"data/intraday/{a}_usdt_15m.csv.parquet")
    d["timestamp"] = pd.to_datetime(d["timestamp"])
    return d.set_index("timestamp").sort_index()

def fmt(m):
    ys = " ".join(f"{y[2:]}:{x:+5.1f}" for y, x in m["yearly"].items())
    return f"{m['monthly']:+6.2f}%/mo SR {m['sharpe']:+5.2f} DD {m['dd']:5.1f} minYr {m['min_year']:+6.2f} | {ys}"

def block_permute_idx(n, bs=20, rng=None):
    rng = rng or np.random.default_rng(0)
    starts = list(range(0, n, bs)); rng.shuffle(starts)
    return np.concatenate([np.arange(s, min(s + bs, n)) for s in starts])

def placebo_daily_pos(pos, ret_d, cost, n=30):
    """pos: daily position series (decided on t-1 info); placebo block-permutes pos."""
    pnl = pos.shift(1) * ret_d - pos.diff().abs() * cost
    rs = metrics_from_pnl(pnl)["sharpe"]; null = []
    for k in range(n):
        pq = pos.iloc[block_permute_idx(len(pos), 20, np.random.default_rng(400 + k))]
        pq.index = pos.index
        null.append(metrics_from_pnl(pq.shift(1) * ret_d - pq.diff().abs() * cost)["sharpe"])
    null = np.asarray(null)
    return rs, float(null.mean()), float(np.percentile(null, 90)), float((null < rs).mean() * 100)

px = ft.load_all_5y(); idx, cols = px.index, px.columns
gate = (px["BTC"] > px["BTC"].rolling(100).mean()).astype(float)
ws_b, _ = rx.build_full(px)
w_base = pd.DataFrame(0.375 * ws_b["ABS_GROT"] + 0.375 * ws_b["FVG_SHORT"]).reindex(idx).fillna(0.0) + 0.25 * cs_weights((px / px.shift(14) - 1), 5, px, gate=gate)
fund = pd.read_csv("data/derivatives/funding_all.csv")
fund["date"] = pd.to_datetime(fund["timestamp_ms"], unit="ms").dt.normalize()
fpiv = fund.pivot_table(index="date", columns="symbol", values="funding_rate", aggfunc="sum")
fpiv.columns = [c.replace("USDT", "") for c in fpiv.columns]
fpiv = fpiv.reindex(idx).fillna(0.0)[cols]
w_fund = cs_weights(fpiv.rolling(7).mean(), 5, px, invert=True)
fund_pnl = pnl_from_weights(w_fund, px) - (w_fund.fillna(0.0) * fpiv).sum(axis=1)

def sqz_w(n1, n2, th, dsh):
    c = px["ETH"]; r = c.pct_change()
    ratio = r.rolling(n1).std() / r.rolling(n2).std()
    w = pd.DataFrame(0.0, index=idx, columns=cols)
    w["ETH"] = (ratio < th).astype(float) * np.sign(c / c.shift(dsh) - 1)
    return w

w_pair = 0.5 * sqz_w(20, 100, 0.7, 30) + 0.5 * sqz_w(10, 50, 0.8, 30)
R31 = 0.5625 * pnl_from_weights(w_base, px, C) + 0.1875 * fund_pnl + 0.25 * pnl_from_weights(w_pair, px, C)
print("R3.1 baseline:", fmt(metrics_from_pnl(R31)))

res = {}

# ============ I-25 volume profile (daily decision from rolling 20d profile) ============
print("\n===== I-25 volume profile (POC / value area / z-reversion) =====")
def vp_series(d15, win=20, nbins=101, va=0.7):
    d = d15.copy(); d["day"] = d.index.normalize()
    grp = {dd: (g["close"].values, g["volume"].values) for dd, g in d.groupby("day")}
    days = sorted(grp)
    rows = []
    for i in range(len(days)):
        if i < win:
            rows.append((days[i], np.nan, np.nan, np.nan, np.nan)); continue
        wdays = days[i - win:i]
        cl = np.concatenate([grp[dd][0] for dd in wdays]); vo = np.concatenate([grp[dd][1] for dd in wdays])
        vo = np.where(np.isfinite(vo) & (vo > 0), vo, 0.0)
        lo, hi = float(cl.min()), float(cl.max())
        if hi <= lo:
            rows.append((days[i], np.nan, np.nan, np.nan, np.nan)); continue
        edges = np.linspace(lo, hi, nbins)
        hist, _ = np.histogram(cl, bins=edges, weights=vo)
        centers = (edges[:-1] + edges[1:]) / 2.0
        poc = float(centers[int(np.argmax(hist))])
        order = np.argsort(hist)[::-1]
        cum = np.cumsum(hist[order])
        thresh = va * float(hist.sum())
        sel = order[cum <= thresh]
        if len(sel) == 0: sel = order[:1]
        vah = float(centers[sel].max()); val = float(centers[sel].min())
        wsum = float(vo.sum()) or 1.0
        sigma = float(np.sqrt(np.average((cl - poc) ** 2, weights=vo)))
        rows.append((days[i], poc, vah, val, sigma))
    out = pd.DataFrame(rows, columns=["day", "poc", "vah", "val", "sigma"]).set_index("day")
    return out.reindex(pd.Index(days)).ffill()

vp_nodes = {}
for a, col in (("BTC", "BTC"), ("ETH", "ETH")):
    d15 = load_15m(a.lower())
    vps = vp_series(d15)
    dclose = d15["close"].resample("1D").last().reindex(vps.index)
    ret_d = px[col].pct_change().reindex(vps.index).fillna(0.0)
    # align to px window
    vps = vps.reindex(idx).ffill(); dclose = dclose.reindex(idx).ffill()
    ret_d = px[col].pct_change()
    c = px[col]
    sig_poc = np.sign(vps["poc"] - c.shift(0))          # fade toward POC
    sig_vab = pd.Series(0.0, idx)
    sig_vab[c.shift(0) > vps["vah"]] = 1.0; sig_vab[c.shift(0) < vps["val"]] = -1.0
    sig_vaf = pd.Series(0.0, idx)
    ext = (c > vps["vah"]) | (c < vps["val"])
    sig_vaf[ext] = -np.sign(c - vps["poc"])[ext]
    z = (c - vps["poc"]) / vps["sigma"]
    sig_zf = pd.Series(0.0, idx); sig_zf[z.abs() > 1.5] = -np.sign(z)[z.abs() > 1.5]
    for nm, sig in (("poc_fade", sig_poc), ("va_break", sig_vab), ("va_fade", sig_vaf), ("z_fade", sig_zf)):
        w = pd.DataFrame(0.0, index=idx, columns=cols); w[col] = sig.fillna(0.0)
        pnl = pnl_from_weights(w, px, C)
        m = metrics_from_pnl(pnl)
        print(f"  VP_{nm}_{a:3s} {fmt(m)}")
        vp_nodes[f"VP_{nm}_{a}"] = (m, w, pnl)

best = sorted(vp_nodes.items(), key=lambda kv: -kv[1][0]["sharpe"])[0]
m_b, w_b, pnl_b = best[1]
rs, nm_, p90, pct = placebo_daily_pos(w_b["BTC"] + w_b["ETH"], (px["BTC"] * 0 + 1), C) if False else (0, 0, 0, 0)
# standalone placebo via block-permute of weight rows (same as prior harness)
def placebo_standalone_w(w, px, cost, n=30):
    rs = metrics_from_pnl(pnl_from_weights(w, px, cost))["sharpe"]; null = []
    for k in range(n):
        wq = w.iloc[block_permute_idx(len(w), 20, np.random.default_rng(500 + k))]
        wq.index = w.index
        null.append(metrics_from_pnl(pnl_from_weights(wq, px, cost))["sharpe"])
    null = np.asarray(null)
    return rs, float(null.mean()), float(np.percentile(null, 90)), float((null < rs).mean() * 100)

print(f"\n  best VP node: {best[0]}")
rs, nm_, p90, pct = placebo_standalone_w(w_b, px, C)
print(f"  standalone placebo: real SR {rs:.2f} vs null mean {nm_:.2f} / p90 {p90:.2f} -> pct {pct:.0f}")
res["I-25"] = {"nodes": {k: v[0] for k, v in vp_nodes.items()}, "best": best[0],
               "placebo": {"real": rs, "null_mean": nm_, "p90": p90, "pct": pct}}
if pct >= 90:
    for frac in (0.15, 0.25):
        mix = (1 - frac) * R31 + frac * pnl_from_weights(w_b, px, C)
        print(f"  blend @ {frac:.0%}:", fmt(metrics_from_pnl(mix)))

# ============ I-26 RVOL filter on squeeze pair ============
print("\n===== I-26 RVOL confirmation overlay on squeeze-pair slot =====")
rvol_nodes = {}
for a in ("BTC", "ETH"):
    d15 = load_15m(a.lower())
    vol_d = d15["volume"].resample("1D").sum().reindex(idx).fillna(0.0)
    rvol = vol_d / vol_d.rolling(20).mean()
    rvol_nodes[a] = rvol
w_pair_rvol = w_pair.copy()
for a in ("BTC", "ETH"):
    col_mask = rvol_nodes[a].shift(1) > 1.0
    w_pair_rvol[a] = w_pair[a] * col_mask.reindex(idx).fillna(False).astype(float)
R31r = 0.5625 * pnl_from_weights(w_base, px, C) + 0.1875 * fund_pnl + 0.25 * pnl_from_weights(w_pair_rvol, px, C)
print("  R3.1 with RVOL-gated squeeze:", fmt(metrics_from_pnl(R31r)))
w_pair_no = w_pair.copy()
for a in ("BTC", "ETH"):
    col_mask = rvol_nodes[a].shift(1) <= 1.0
    w_pair_no[a] = w_pair[a] * col_mask.reindex(idx).fillna(False).astype(float)
R31n = 0.5625 * pnl_from_weights(w_base, px, C) + 0.1875 * fund_pnl + 0.25 * pnl_from_weights(w_pair_no, px, C)
print("  R3.1 with LOW-vol squeeze only :", fmt(metrics_from_pnl(R31n)))
res["I-26"] = {"rvol_gated": metrics_from_pnl(R31r), "lowvol_only": metrics_from_pnl(R31n)}

# ============ I-27 sessions: Asian-range breakout + session momentum ============
print("\n===== I-27 session strategies (15m, UTC) =====")
sess_res = {}
for a, col in (("BTC", "BTC"), ("ETH", "ETH")):
    d15 = load_15m(a.lower())
    r15 = d15["close"].pct_change()
    day = d15.index.normalize()
    hod = d15.index.hour
    # --- Asian range breakout: Asia 00-08, trade 08-24 stop-and-reverse ---
    pos = pd.Series(0.0, index=d15.index)
    days = pd.unique(day)
    for dd in days:
        asia = (day == dd) & (hod < 8)
        sess = (day == dd) & (hod >= 8)
        if asia.sum() < 4 or sess.sum() < 4: continue
        rh = float(d15.loc[asia, "high"].max()); rl = float(d15.loc[asia, "low"].min())
        p = 0.0
        for t in d15.index[sess]:
            cl = d15.at[t, "close"]
            if cl > rh: p = 1.0
            elif cl < rl: p = -1.0
            pos.at[t] = p
    pnl15 = pos.shift(1) * r15 - pos.diff().abs() * C
    m = metrics_from_pnl(pnl15.resample("1D").sum().reindex(idx).fillna(0.0))
    print(f"  asiarange_{a:3s}   {fmt(m)}")
    sess_res[f"asiarange_{a}"] = m
    pos_end = pos.resample("1D").last().reindex(idx).fillna(0.0)
    ret_d = px[col].pct_change()
    rs, nm_, p90, pct = placebo_daily_pos(pos_end, ret_d, C)
    print(f"     placebo: real SR {rs:.2f} vs p90 {p90:.2f} -> pct {pct:.0f}")
    sess_res[f"asiarange_{a}_placebo"] = {"real": rs, "p90": p90, "pct": pct}
    # --- session momentum: first hour of London (08-09) -> 09-13:30; US (13:30-14:30) -> 14:30-20 ---
    for nm, h_start, h_end, t_start, t_end in (("lmom", 8, 9, 9, 13), ("umom", 13, 14, 14, 20)):
        pos = pd.Series(0.0, index=d15.index)
        for dd in days:
            lead = (day == dd) & (hod >= h_start) & (hod < h_end)
            trade = (day == dd) & (hod >= t_start) & (hod < t_end)
            if lead.sum() < 2 or trade.sum() < 2: continue
            sig = float(np.sign(d15.loc[lead, "close"].iloc[-1] / d15.loc[lead, "close"].iloc[0] - 1))
            pos.loc[trade] = sig
        pnl15 = pos.shift(1) * r15 - pos.diff().abs() * C
        m = metrics_from_pnl(pnl15.resample("1D").sum().reindex(idx).fillna(0.0))
        print(f"  {nm}_{a:3s}         {fmt(m)}")
        sess_res[f"{nm}_{a}"] = m
res["I-27"] = sess_res

# ============ I-28 session VWAP ============
print("\n===== I-28 session VWAP (trend & fade) =====")
vwap_res = {}
for a, col in (("BTC", "BTC"), ("ETH", "ETH")):
    d15 = load_15m(a.lower())
    r15 = d15["close"].pct_change()
    # session resets at 00:00 and at 13:30 (US open) -> two sessions per day
    sess_id = (d15.index.normalize()) + pd.to_timedelta((d15.index.hour >= 13).astype(int) + (d15.index.hour == 13) * 0, unit="h")
    sid = pd.Series(np.arange(len(d15)), index=d15.index)
    grp = ((d15.index.date.astype(str)) + np.where(d15.index.hour < 13, "_a", "_b"))
    vwap = pd.Series(np.nan, index=d15.index)
    for g, ii in pd.Series(grp, index=d15.index).groupby(grp).groups.items():
        sub = d15.loc[ii]
        pv = (sub["close"] * sub["volume"]).cumsum(); vv = sub["volume"].cumsum().replace(0, np.nan)
        vwap.loc[ii] = (pv / vv).values
    dev = d15["close"] - vwap
    pos_t = pd.Series(np.sign(dev).fillna(0.0), index=d15.index)
    pos_f = pd.Series(-np.sign(dev).fillna(0.0), index=d15.index)
    for nm, pos in (("vwap_trend", pos_t), ("vwap_fade", pos_f)):
        pnl15 = pos.shift(1) * r15 - pos.diff().abs() * C
        m = metrics_from_pnl(pnl15.resample("1D").sum().reindex(idx).fillna(0.0))
        print(f"  {nm}_{a:3s}     {fmt(m)}")
        vwap_res[f"{nm}_{a}"] = m
res["I-28"] = vwap_res

# ============ I-06 causal hour-of-day seasonality ============
print("\n===== I-06 causal hour-of-day seasonality (expanding hour means) =====")
sea_res = {}
for a, col in (("BTC", "BTC"), ("ETH", "ETH")):
    d15 = load_15m(a.lower())
    r15 = d15["close"].pct_change()
    hod = d15.index.hour
    mu_all = r15.expanding(2000).mean(); sd_all = r15.expanding(2000).std()
    pos = pd.Series(0.0, index=d15.index)
    for h in range(24):
        mask = hod == h
        sub = r15[mask]
        mu_h = sub.expanding(30).mean().shift(1).reindex(d15.index).ffill()
        z = (mu_h - mu_all) / sd_all
        pos[mask & (z > 1.0)] = 1.0
        pos[mask & (z < -1.0)] = -1.0
    pnl15 = pos.shift(1) * r15 - pos.diff().abs() * C
    m = metrics_from_pnl(pnl15.resample("1D").sum().reindex(idx).fillna(0.0))
    print(f"  hourseason_{a:3s} {fmt(m)}")
    sea_res[f"hourseason_{a}"] = m
res["I-06"] = sea_res

# ============ I-18 weekend effect ============
print("\n===== I-18 weekend exposure (BTC) =====")
wk = {}
ret_d = px["BTC"].pct_change()
pos_wd = pd.Series(np.where(pd.Index(idx).dayofweek < 5, 1.0, 0.0), index=idx)
m_bh = metrics_from_pnl(ret_d - 0.0)
m_wd = metrics_from_pnl(pos_wd.shift(1) * ret_d - pos_wd.diff().abs() * C)
print("  buy-hold BTC        :", fmt(m_bh))
print("  weekdays-only BTC   :", fmt(m_wd))
pos_we = 1.0 - pos_wd
m_we = metrics_from_pnl(pos_we.shift(1) * ret_d - pos_we.diff().abs() * C)
print("  weekends-only BTC   :", fmt(m_we))
wk = {"buyhold": m_bh, "weekdays": m_wd, "weekends": m_we}
res["I-18"] = wk

def clean(o):
    if isinstance(o, dict): return {k: clean(v) for k, v in o.items() if k != "yearly"}
    if isinstance(o, (np.floating,)): return float(o)
    return o
json.dump(clean(res), open(os.path.join(OUT, "improvement_wave15.json"), "w"), indent=1)
print("\nsaved reports/improvement_wave15.json")
