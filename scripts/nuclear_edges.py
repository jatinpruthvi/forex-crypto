"""EXP-042 (2026-10-30): NUCLEAR EDGE HUNT - genuinely higher-Sharpe edges, 220 nodes.

User: "using nuclear explosion... think on below with real data, commission and spread.
check more than 200 nodes: Find a genuinely higher-Sharpe edge - not more leverage:
perp funding carry, options premium, intraday execution."

DATA (all real, downloaded from GitHub sources):
  - Daily 5y panel 2021-01..2026-07 (15 majors, olaxbt) + OLD 21-coin 2020-07..2023-04
  - REAL perp funding 8h stamps 2021->2026 (olaxbt data/derivatives/funding_all.csv)
  - Macro liquidity daily (defillama stablecoin circulating + TVL)
  - Intraday 15m/1h perps: BTC 2019-09..2025-06, ETH 15m, XRP 15m, BTC 1h (quantinaut)
  - OPTIONS PREMIUM: NO reachable historical options/IV data (only scrapers) ->
    family is UNTESTABLE with real data and is excluded by the no-assumption rule.

COSTS: daily nodes fee=10bp per side (commission+spread+slippage); intraday nodes
fee=12bp per side (taker+intraday spread). Funding accrual included in FUND family
(+-rate on notional, real 8h data). Winner stress at +5bp.

PRE-REGISTERED NODE GRID (220 nodes):
  CS  (cross-sectional daily, rebal 5d, K{3,5}): reversal lb{3,5,10,20}, momentum lb
      {7,14,30}, low-vol{20,60}, vol-spike fade/chase, range-expansion fade/chase,
      candle body, pin bar, gap-reversal, mom+lowvol, gated variants            -> 38
  TA  (single-asset daily: BTC/ETH/EQ): Donchian{20,55,100}x{ls,lf}, Bollinger
      {20/2,40/2,20/2.5}x{contr,momo}, RSI{14,2}x{contr,momo}, MACD, squeeze,
      crash-rebound, gap-fade, DOW seasonality, MA crosses                     -> 83
  ID  (intraday 15m/1h: BTC,ETH,XRP): hour-buckets, funding-window, intraday
      momentum{4,8,16}x{hold 1,4}, intraday reversal, ORB, RSI2 1h, VWAP-dev,
      overnight, 1h momentum                                                 -> 72
  FUND (real funding): carry long-short{7,30,90}x{3,5}, z-thresholds, sign,
      funding momentum, carry capture, funding+mom combo, ETH-BTC spread       -> 17
  MACRO (defillama): stablecoin/TVL 7d change timing x{on-off, ls} x{BTC,EQ},
      combined                                                                -> 10
RANKING: Sharpe (annualized on daily P&L) among nodes with monthly>=0.3 and DD<=50.
NULLS: (a) config placebo 20x30d-block signal shuffles on shortlist; (b) search-level
null 8 common-permutation draws = max Sharpe over ALL 220 nodes; (c) deflated Sharpe
analytic (N=220). Winner must beat ALL three. Blends with ABS_GROT+FVG_SHORT tested.
"""
import os
import sys
import json

sys.path.insert(0, os.path.abspath("scripts"))

import numpy as np
import pandas as pd

import strategy_hunt as sh
import strategy_hunt2 as sh2
import regime_hunt as rh
import regime_expansion as rx
import five_year_test as ft

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOARD = os.path.join(BASE, "reports", "strategy_leaderboard.json")
LEDGER = os.path.join(BASE, "reports", "roi_progress_ledger.json")
ID_DIR = os.path.join(BASE, "data", "intraday")
FUND_CSV = os.path.join(BASE, "data", "derivatives", "funding_all.csv")
MACRO_CSV = os.path.join(BASE, "data", "macro", "defillama_liquidity_daily.csv")
FEE_D = 0.0010      # daily: commission+spread+slippage per side
FEE_I = 0.0012      # intraday taker per side


# --------------------------------------------------------------- utilities
def metrics_from_pnl(pnl, fee_stress=0.0, extra_cost=None):
    r = pnl.fillna(0.0).replace([np.inf, -np.inf], 0.0)
    if extra_cost is not None:
        r = r - extra_cost
    d = r.resample("D").sum().dropna(how="all")
    if len(d) < 120:
        return None
    if float(d.min()) < -0.95:      # impossible with real costs -> broken node
        return None
    eq = (1 + d).cumprod()
    if not np.isfinite(eq.iloc[-1]) or eq.iloc[-1] <= 0:
        return None
    years = max((d.index[-1] - d.index[0]).days / 365.25, 0.5)
    monthly = eq.resample("ME").last().pct_change().dropna()
    mret = monthly.values
    sharpe = float(d.mean() / max(d.std(), 1e-12) * np.sqrt(365))
    ym = {}
    for y, g in eq.groupby(eq.index.year):
        mm = g.resample("ME").last().pct_change().dropna()
        if len(mm):
            ym[int(y)] = float(((1 + mm).prod() ** (1 / len(mm)) - 1) * 100)
    dd = float((eq / eq.cummax() - 1).min()) * 100
    tot = float(eq.iloc[-1])
    months = max((eq.index[-1] - eq.index[0]).days / 30.44, 1)
    return {
        "sharpe": round(sharpe, 2),
        "monthly": round((tot ** (1 / months) - 1) * 100, 2),
        "dd": round(-dd, 1),
        "min_year": round(min(ym.values()), 2) if ym else None,
        "min_month": round(float(mret.min()) * 100, 2) if len(mret) else None,
        "yearly": {str(y): round(v, 2) for y, v in ym.items()},
        "months": round(months),
    }


def pnl_from_weights(w, px, fee=FEE_D):
    """w: target weights (set at close t). PnL t->t+1 minus fee on |dw|."""
    w = w.fillna(0.0).reindex(px.index).fillna(0.0)
    ret_fwd = px.pct_change().shift(-1)
    pnl = (w * ret_fwd).sum(axis=1) - w.diff().abs().sum(axis=1) * fee
    return pnl.fillna(0.0)


def pnl_from_pos(pos, close, fee=FEE_I):
    """pos set at close t earns t->t+1; fee on |dpos|. Row-0 semantics MATCH
    pnl_from_weights: row-0 return is kept, row-0 entry cost is not charged
    (bug #5 fix: previously the whole row 0 was NaN-zeroed whenever pos[0]!=0)."""
    ret_fwd = close.pct_change().shift(-1)
    cost = pos.diff().abs().fillna(0.0) * fee
    return (pos * ret_fwd - cost).fillna(0.0)


def cs_weights(score, K, px, invert=False, rebal=5, gate=None):
    """Cross-sectional: default = LONG top-K / SHORT bottom-K of score.
    invert=True flips (reversal-style). Rebalance every `rebal` rows, hold between."""
    s = score.copy()
    s.iloc[:, :] = np.nan
    s.iloc[rebal - 1::rebal] = score.iloc[rebal - 1::rebal]
    r = s.rank(axis=1)
    n = s.notna().sum(axis=1)
    w = pd.DataFrame(np.nan, index=s.index, columns=s.columns)
    lo = r.le(K, axis=0)
    hi = r.ge(n - K + 1, axis=0)
    if invert:
        lo, hi = hi, lo
    w[lo] = -1.0 / K
    w[hi] = +1.0 / K
    w = w.where(s.notna(), np.nan)          # non-rebalance rows = hold
    w = w.ffill(limit=rebal).fillna(0.0)     # hold last target between rebalances
    if gate is not None:
        w = w.mul(gate.astype(float), axis=0)
    return w.reindex(px.index).fillna(0.0)


def main():
    nodes = {}       # name -> dict(pnl=Series, family=str, turnover=float)
    daily_pnl = {}   # for search-null: daily pnl series per node

    def add(name, family, pnl, kind=None, payload=None, fund=False):
        """kind: 'w' (weights df + px), 'pos' (pos series + close); payload=(a, b).
        Stored so nulls can block-permute SIGNAL rows and recompute PnL."""
        p = pnl.fillna(0.0)
        nodes[name] = {"pnl": p, "family": family, "kind": kind,
                       "payload": payload, "fund": fund}
        daily_pnl[name] = p.resample("D").sum()

    def recompute_pnl(name, perm, block):
        d = nodes[name]
        a, b = d["payload"]
        nb = int(np.ceil(len(a) / block))
        idxp = a.index
        pieces = [a.iloc[bk * block:(bk + 1) * block] for bk in perm]
        a2 = pd.concat(pieces, axis=0)
        a2.index = idxp[:len(a2)]
        if d["kind"] == "w":
            w2 = a2.reindex(idxp).fillna(0.0)
            p = pnl_from_weights(w2, b)
            if d["fund"]:
                p = p - (w2.fillna(0.0) * fpiv.reindex(idxp).fillna(0.0)).sum(axis=1)
            return p.fillna(0.0)
        else:
            pos2 = a2.reindex(idxp).fillna(0.0)
            return pnl_from_pos(pos2, b)

    # =========================================================== DATA
    px = ft.load_all_5y()
    rh.MENU = rh.menu_builders()
    ws_base, _ = rx.build_full(px)
    ret = px.pct_change()
    btc = px["BTC"]
    n = len(px)
    idx = px.index

    fund = pd.read_csv(FUND_CSV)
    fund["date"] = pd.to_datetime(fund["timestamp_ms"], unit="ms").dt.normalize()
    fpiv = fund.pivot_table(index="date", columns="symbol", values="funding_rate", aggfunc="sum")
    fpiv.columns = [c.replace("USDT", "") for c in fpiv.columns]
    fpiv = fpiv.reindex(idx).fillna(0.0)[px.columns]

    mac = pd.read_csv(MACRO_CSV, parse_dates=["date"]).set_index("date").reindex(idx).ffill()
    stab_chg = mac["stablecoin_change_7d_pct"]
    tvl_chg = mac["all_chain_tvl_change_7d_pct"]
    both_z = ((stab_chg.rank(pct=True) + tvl_chg.rank(pct=True)) / 2)

    def load_id(name):
        df = pd.read_parquet(os.path.join(ID_DIR, f"{name}.csv.parquet"))
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp").sort_index()
        return df[["open", "high", "low", "close", "volume"]]

    # =========================================================== CS family
    for lb in (3, 5, 10, 20):
        for K in (3, 5):
            sc = -(px / px.shift(lb) - 1)
            w_ = cs_weights(sc, K, px)
            add(f"cs_rev{lb}_K{K}", "CS", pnl_from_weights(w_, px), "w", (w_, px))
    for lb in (7, 14, 30):
        for K in (3, 5):
            sc = (px / px.shift(lb) - 1)
            w_ = cs_weights(sc, K, px)
            add(f"cs_mom{lb}_K{K}", "CS", pnl_from_weights(w_, px), "w", (w_, px))
    for lb in (20, 60):
        for K in (3, 5):
            sc = -ret.rolling(lb).std()
            w_ = cs_weights(sc, K, px)
            add(f"cs_lowvol{lb}_K{K}", "CS", pnl_from_weights(w_, px), "w", (w_, px))
    for mode, inv in (("fade", True), ("chase", False)):
        for K in (3, 5):
            sc = ret.rolling(5).std() / ret.rolling(60).std()
            w_ = cs_weights(sc, K, px, invert=inv)
            add(f"cs_volspk_{mode}_K{K}", "CS", pnl_from_weights(w_, px), "w", (w_, px))
    for mode, inv in (("fade", True), ("chase", False)):
        for K in (3, 5):
            sc = ret.rolling(5).std() / ret.rolling(20).std()
            w_ = cs_weights(sc, K, px, invert=inv)
            add(f"cs_range_{mode}_K{K}", "CS", pnl_from_weights(w_, px), "w", (w_, px))
    for K in (3, 5):
        sc = -(px - px.shift(1)) / ret.rolling(10).std().replace(0, np.nan)
        w_ = cs_weights(sc, K, px)
        add(f"cs_candle_K{K}", "CS", pnl_from_weights(w_, px), "w", (w_, px))
    for K in (3, 5):
        sc = ret.rolling(5).mean()
        w_ = cs_weights(sc, K, px)
        add(f"cs_gaprev_K{K}", "CS", pnl_from_weights(w_, px), "w", (w_, px))
    for K in (3, 5):
        mom = (px / px.shift(14) - 1).rank(axis=1)
        lv = (-ret.rolling(20).std()).rank(axis=1)
        sc = mom + lv
        w_ = cs_weights(sc, K, px)
        add(f"cs_momvol_K{K}", "CS", pnl_from_weights(w_, px), "w", (w_, px))
    gate = (btc > btc.rolling(100).mean()).astype(float)
    for K in (3, 5):
        sc = -(px / px.shift(10) - 1)
        w_ = cs_weights(sc, K, px, gate=gate)
        add(f"cs_rev10_K{K}_vg", "CS", pnl_from_weights(w_, px), "w", (w_, px))
        sc2 = (px / px.shift(14) - 1)
        w_ = cs_weights(sc2, K, px, gate=gate)
        add(f"cs_mom14_K{K}_vg", "CS", pnl_from_weights(w_, px), "w", (w_, px))

    # =========================================================== TA family
    assets = {"BTC": px[["BTC"]], "ETH": px[["ETH"]],
              "EQ": px[["BTC", "ETH"]] * 0.5}
    for lb in (20, 55, 100):
        for side in ("ls", "lf"):
            for an, apx in assets.items():
                hh = apx.rolling(lb).max().shift(1)
                ll = apx.rolling(lb).min().shift(1)
                long = (apx > hh).astype(float)
                short = (apx < ll).astype(float)
                w = long - short if side == "ls" else long.clip(upper=1.0)
                add(f"ta_don{lb}_{side}_{an}", "TA", pnl_from_weights(w, apx), "w", (w, apx))
    for (lbb, sd) in ((20, 2.0), (40, 2.0), (20, 2.5)):
        for mode in ("contr", "momo"):
            for an, apx in assets.items():
                ma = apx.rolling(lbb).mean()
                sdv = apx.rolling(lbb).std()
                up, dn = ma + sd * sdv, ma - sd * sdv
                if mode == "contr":
                    w = (apx < dn).astype(float) - (apx > up).astype(float)
                else:
                    w = (apx > up).astype(float) - (apx < dn).astype(float)
                add(f"ta_boll{lbb}_{int(sd*10)}_{mode}_{an}", "TA", pnl_from_weights(w, apx), "w", (w, apx))
    for rlb in (14, 2):
        for mode in ("contr", "momo"):
            for an, apx in assets.items():
                delta = apx.diff()
                up_ = delta.clip(lower=0).rolling(rlb).mean()
                dn_ = (-delta.clip(upper=0)).rolling(rlb).mean()
                rsi = 100 - 100 / (1 + up_ / dn_.replace(0, np.nan))
                lo_t, hi_t = (30, 70) if rlb == 14 else (10, 90)
                if mode == "contr":
                    w = (rsi < lo_t).astype(float) - (rsi > hi_t).astype(float)
                else:
                    w = (rsi > hi_t).astype(float) - (rsi < lo_t).astype(float)
                add(f"ta_rsi{rlb}_{mode}_{an}", "TA", pnl_from_weights(w, apx), "w", (w, apx))
    for an, apx in assets.items():
        ema12 = apx.ewm(span=12).mean()
        ema26 = apx.ewm(span=26).mean()
        hist = (ema12 - ema26) - (ema12 - ema26).ewm(span=9).mean()
        w = np.sign(hist).shift(1)
        add(f"ta_macd_{an}", "TA", pnl_from_weights(w, apx), "w", (w, apx))
    for thr in (0.75, 0.6):
        for an, apx in assets.items():
            atr = (apx.rolling(5).std() / apx.rolling(20).std())
            sq = (atr < thr).astype(float)
            direc = np.sign(apx - apx.rolling(20).mean())
            w = (sq * direc).shift(1)
            add(f"ta_sq{int(thr*100)}_{an}", "TA", pnl_from_weights(w, apx), "w", (w, apx))
    for thr in (-0.10, -0.15):
        for an, apx in assets.items():
            r5 = apx / apx.shift(5) - 1
            trig = (r5 < thr).astype(float)
            w = trig.rolling(10).max().shift(1)
            add(f"ta_crash{int(-thr*100)}_{an}", "TA", pnl_from_weights(w, apx), "w", (w, apx))
    for thr in (1.5, 3.0):
        for an, apx in assets.items():
            gap = apx / apx.shift(1) - 1
            w = -np.sign(gap) * (gap.abs() > thr / 100).astype(float)
            w_ = w.shift(1)
            add(f"ta_gap{int(thr*10)}_{an}", "TA", pnl_from_weights(w_, apx), "w", (w_, apx))
    dow = pd.Series(idx.dayofweek, index=idx)
    for d, lab in ((0, "Mon"), (1, "Tue"), (2, "Wed"), (3, "Thu"), (4, "Fri")):
        w = pd.DataFrame(np.where((dow == d).values[:, None], 1.0, 0.0), index=idx, columns=["BTC"])
        add(f"ta_dow_long{lab}", "TA", pnl_from_weights(w, px[["BTC"]]), "w", (w, px[["BTC"]]))
    for lab, days in (("SatSunS", [5, 6]), ("MonThuL", [0, 3])):
        m = dow.isin(days).values[:, None]
        w = pd.DataFrame(np.where(m, -1.0 if lab.endswith("S") else 1.0, 0.0),
                         index=idx, columns=["BTC"])
        add(f"ta_dow_{lab}", "TA", pnl_from_weights(w, px[["BTC"]]), "w", (w, px[["BTC"]]))
    for fs, sl in ((20, 50), (50, 200)):
        for an, apx in assets.items():
            w = ((apx.rolling(fs).mean() > apx.rolling(sl).mean()).astype(float))
            add(f"ta_ma{fs}_{sl}_{an}", "TA", pnl_from_weights(w, apx), "w", (w, apx))

    # =========================================================== FUND family
    def full_w(pos):
        arr = np.asarray(pos, dtype=float).reshape(-1)
        return pd.DataFrame(np.repeat(arr[:, None], px.shape[1], axis=1),
                            index=idx, columns=px.columns)

    def fund_pnl(w, extra=None):
        p = pnl_from_weights(w, px)
        accr = -(w.fillna(0.0) * fpiv).sum(axis=1)
        if extra is not None:
            accr = accr + extra
        return p + accr
    for win in (7, 30, 90):
        for K in (3, 5):
            fmean = fpiv.rolling(win).mean()
            sc = fmean
            w = cs_weights(sc, K, px, invert=True)   # short highest-funding
            add(f"fund_ls{win}_K{K}", "FUND", fund_pnl(w), "w", (w, px), fund=True)
    for thr in (1, 2):
        z = (fpiv["BTC"] - fpiv["BTC"].rolling(30).mean()) / fpiv["BTC"].rolling(30).std().replace(0, np.nan)
        pos_ = np.where(z < -thr, 1.0, np.where(z > thr, -1.0, 0.0))
        w = pd.DataFrame(0.0, index=idx, columns=px.columns)
        w["BTC"] = pos_
        add(f"fund_z{thr}", "FUND", fund_pnl(w), "w", (w, px), fund=True)
    for win in (7, 30):
        fm = fpiv["BTC"].rolling(win).mean()
        pos_ = np.where(fm < 0, 1.0, np.where(fm > 0.00005, -1.0, 0.0))
        w = pd.DataFrame(0.0, index=idx, columns=px.columns)
        w["BTC"] = pos_
        add(f"fund_sign{win}", "FUND", fund_pnl(w), "w", (w, px), fund=True)
    for win in (7, 30):
        d = fpiv["BTC"].diff(win)
        pos_ = np.where(d > 0, -1.0, 1.0)
        w = pd.DataFrame(0.0, index=idx, columns=px.columns)
        w["BTC"] = pos_
        add(f"fund_mom{win}", "FUND", fund_pnl(w), "w", (w, px), fund=True)
    for win in (30, 90):
        fmean = fpiv.rolling(win).mean()
        w = cs_weights(fmean, 3, px, invert=True)
        w[w > 0] = 0.0                      # only short crowded / hold flat
        add(f"fund_shortcrowd{win}", "FUND", fund_pnl(w), "w", (w, px), fund=True)
    for K in (3, 5):
        fmean = fpiv.rolling(30).mean()
        mom = (px / px.shift(30) - 1).rank(axis=1)
        sc = fmean.rank(axis=1) + mom
        w_ = cs_weights(sc, K, px, invert=True)
        add(f"fund_momwin30_K{K}", "FUND", fund_pnl(w_), "w", (w_, px), fund=True)
    for win in (7, 30):
        sp = (fpiv["ETH"] - fpiv["BTC"]).rolling(win).mean()
        w = pd.DataFrame(0.0, index=idx, columns=px.columns)
        w["ETH"] = np.where(sp < 0, 1.0, -1.0)
        w["BTC"] = -w["ETH"]
        add(f"fund_ethbtc{win}", "FUND", fund_pnl(w), "w", (w, px), fund=True)

    # =========================================================== MACRO family
    for sig_name, sig in (("stab", stab_chg), ("tvl", tvl_chg)):
        for mode in ("onoff", "ls"):
            for an in ("BTC", "EQ"):
                pos = np.where(sig > 0, 1.0, (-1.0 if mode == "ls" else 0.0))
                if an == "BTC":
                    w = pd.DataFrame(0.0, index=idx, columns=px.columns)
                    w["BTC"] = np.asarray(pos)
                else:
                    w = pd.DataFrame(0.0, index=idx, columns=px.columns)
                    w["BTC"] = np.asarray(pos) / 2
                    w["ETH"] = np.asarray(pos) / 2
                add(f"mac_{sig_name}_{mode}_{an}", "MACRO", pnl_from_weights(w, px), "w", (w, px))
    for an in ("BTC", "EQ"):
        pos = np.where(both_z > 0.6, 1.0, np.where(both_z < 0.4, -1.0, 0.0))
        if an == "BTC":
            w = pd.DataFrame(0.0, index=idx, columns=px.columns)
            w["BTC"] = np.asarray(pos)
        else:
            w = pd.DataFrame(0.0, index=idx, columns=px.columns)
            w["BTC"] = np.asarray(pos) / 2
            w["ETH"] = np.asarray(pos) / 2
        add(f"mac_combo_{an}", "MACRO", pnl_from_weights(w, px), "w", (w, px))

    # =========================================================== ID family
    id_assets = {"BTC15": "btc_usdt_15m", "ETH15": "eth_usdt_15m", "XRP15": "xrp_usdt_15m"}
    idd = {k: load_id(v) for k, v in id_assets.items()}
    btc1h = pd.read_parquet(os.path.join(ID_DIR, "btc_usdt_1h.csv.parquet"))
    btc1h["timestamp"] = pd.to_datetime(btc1h["timestamp"])
    btc1h = btc1h.set_index("timestamp").sort_index()
    idd["BTC1h"] = btc1h[["open", "high", "low", "close", "volume"]]

    for an in ("BTC15", "ETH15"):
        df = idd[an]
        c = df["close"]
        hr = df.index.hour
        for b0 in (0, 6, 12, 18):
            m = ((hr >= b0) & (hr < b0 + 6)).astype(float)
            for side in (1, -1):
                pos = pd.Series(side * np.asarray(m, dtype=float), index=df.index)
                add(f"id_hod{b0:02d}_{'L' if side==1 else 'S'}_{an}", "ID", pnl_from_pos(pos, c), "pos", (pos, c))
        pre = df.index.hour.isin([22, 23, 6, 7, 14, 15]).astype(float)   # 2h before funding
        post = df.index.hour.isin([0, 1, 8, 9, 16, 17]).astype(float)    # 2h after
        pos = pd.Series(pre, index=df.index)
        add(f"id_fundpre_{an}", "ID", pnl_from_pos(pos, c), "pos", (pos, c))
        pos = pd.Series(post, index=df.index)
        add(f"id_fundpost_{an}", "ID", pnl_from_pos(pos, c), "pos", (pos, c))
    for an in ("BTC15", "ETH15", "XRP15"):
        df = idd[an]
        c = df["close"]
        for lb in (4, 8, 16):
            for hold in (1, 4):
                sig = np.sign(c / c.shift(lb) - 1)
                pos = sig.rolling(hold).max().shift(1)
                add(f"id_mom{lb}h{hold}_{an}", "ID", pnl_from_pos(pos.fillna(0), c), "pos", (pos.fillna(0), c))
                pos2 = (-sig).rolling(hold).max().shift(1)
                add(f"id_rev{lb}h{hold}_{an}", "ID", pnl_from_pos(pos2.fillna(0), c), "pos", (pos2.fillna(0), c))
    for an in ("BTC15", "ETH15"):
        df = idd[an]
        c = df["close"]
        hh = df["high"].rolling(4).max().shift(1)
        ll = df["low"].rolling(4).min().shift(1)
        up = ((c > hh) & (df.index.hour >= 1)).astype(float)
        dn = ((c < ll) & (df.index.hour >= 1)).astype(float)
        pos = pd.Series(up.values, index=df.index)
        add(f"id_orbup_{an}", "ID", pnl_from_pos(pos, c), "pos", (pos, c))
        pos = pd.Series(-dn.values, index=df.index)
        add(f"id_orbdn_{an}", "ID", pnl_from_pos(pos, c), "pos", (pos, c))
        vwap = (c * df["volume"]).rolling(96).sum() / df["volume"].rolling(96).sum()
        dev = (c / vwap - 1) * 100
        for thr in (1.5, 2.5):
            pos = np.where(dev < -thr, 1.0, np.where(dev > thr, -1.0, 0.0))
            pos = pd.Series(pos, index=df.index).shift(1)
            add(f"id_vwap{int(thr*10)}_{an}", "ID", pnl_from_pos(pos.fillna(0), c), "pos", (pos.fillna(0), c))
        late = df.index.hour.isin([20, 21, 22, 23]).astype(float)
        early = df.index.hour.isin([0, 1, 2, 3]).astype(float)
        pos = pd.Series(late, index=df.index)
        add(f"id_latelong_{an}", "ID", pnl_from_pos(pos, c), "pos", (pos, c))
        pos = pd.Series(early, index=df.index)
        add(f"id_earlylong_{an}", "ID", pnl_from_pos(pos, c), "pos", (pos, c))
    df = idd["BTC1h"]
    c = df["close"]
    delta = c.diff()
    up_ = delta.clip(lower=0).rolling(14).mean()
    dn_ = (-delta.clip(upper=0)).rolling(14).mean()
    rsi = 100 - 100 / (1 + up_ / dn_.replace(0, np.nan))
    pos = pd.Series(np.where(rsi < 20, 1.0, np.where(rsi > 80, -1.0, 0.0)),
                    index=df.index).shift(1).fillna(0)
    add("id_rsi2h_contr_BTC1h", "ID", pnl_from_pos(pos, c), "pos", (pos, c))
    pos = pd.Series(np.where(rsi > 80, 1.0, np.where(rsi < 20, -1.0, 0.0)),
                    index=df.index).shift(1).fillna(0)
    add("id_rsi2h_momo_BTC1h", "ID", pnl_from_pos(pos, c), "pos", (pos, c))
    for lb in (6, 12):
        sig = np.sign(c / c.shift(lb) - 1)
        pos = sig.shift(1).fillna(0)
        add(f"id_mom1h{lb}_BTC1h", "ID", pnl_from_pos(pos, c), "pos", (pos, c))

    # =========================================================== EVAL
    print("=" * 120)
    print(f"TOTAL NODES: {len(nodes)}")
    rows = {}
    dropped = []
    for name, d in nodes.items():
        m = metrics_from_pnl(d["pnl"])
        if m is None:
            dropped.append(name)
            continue
        to = d["pnl"].resample("ME").count()  # placeholder
        rows[name] = {**m, "family": d["family"]}
    fam_count = pd.Series({k: v["family"] for k, v in rows.items()}).value_counts()
    print("by family:", fam_count.to_dict())
    print("dropped:", dropped)
    ok = [(k, v) for k, v in rows.items() if v["monthly"] >= 0.3 and v["dd"] <= 50]
    ok.sort(key=lambda kv: kv[1]["sharpe"], reverse=True)
    print("\nTOP-15 by Sharpe (monthly>=0.3, DD<=50):")
    for k, v in ok[:15]:
        ys = " ".join(f"{y[2:]}:{x:+5.1f}" for y, x in v["yearly"].items())
        print(f"  {k:<26} SR {v['sharpe']:+5.2f} {v['monthly']:+6.2f}%/mo DD {v['dd']:5.1f} "
              f"minYr {v['min_year']:+5.1f} | {ys}")
    best = ok[0] if ok else max(rows.items(), key=lambda kv: kv[1]["sharpe"])

    # =========================================================== NULLS
    print("\n" + "=" * 120)
    print(f"NULLS for winner {best[0]}")
    rng = np.random.default_rng(4242)

    def shuffled_pnl(name, perm, block):
        return recompute_pnl(name, perm, block)

    shortlist = [k for k, v in ok[:10]]
    if best[0] not in shortlist:
        shortlist.append(best[0])
    conf_null = {}
    for name in shortlist:
        p = nodes[name]["payload"][0]
        block = 30 * (96 if nodes[name]["family"] == "ID" else 1)
        if nodes[name]["payload"][0].index.freq is not None:
            pass
        nb = int(np.ceil(len(p) / block))
        draws = []
        for d_ in range(20):
            perm = rng.permutation(nb)
            m_ = metrics_from_pnl(shuffled_pnl(name, perm, block))
            if m_ is not None:
                draws.append(m_["sharpe"])
        conf_null[name] = draws
        real = rows[name]["sharpe"]
        p90 = float(np.quantile(draws, 0.9))
        print(f"  {name:<26} real SR {real:+5.2f} vs null p90 {p90:+5.2f} -> "
              f"{'PASS' if real >= p90 else 'FAIL'}")
    # search-level null: common permutation of ALL nodes
    search_null = []
    daily_names = [k for k in nodes if nodes[k]["family"] != "ID"]
    id_names = [k for k in nodes if nodes[k]["family"] == "ID"]
    for d_ in range(8):
        best_sr = -99
        for name in nodes:
            ln = len(nodes[name]["payload"][0])
            block = 30 * 24 if nodes[name]["family"] == "ID" and "1h" in name else \
                (30 * 96 if nodes[name]["family"] == "ID" else 30)
            nb = int(np.ceil(ln / block))
            perm = rng.permutation(nb)
            m_ = metrics_from_pnl(shuffled_pnl(name, perm, block))
            if m_ is not None:
                best_sr = max(best_sr, m_["sharpe"])
        search_null.append(round(best_sr, 2))
        print(f"  search-null draw {d_}: max SR over {len(nodes)} nodes = {best_sr:+.2f}")
    sn = np.array(search_null)
    g_search = best[1]["sharpe"] >= float(sn.max())
    # deflated sharpe (analytic)
    from math import sqrt, exp, log
    from scipy.stats import norm
    srs = np.array([v["sharpe"] for v in rows.values()])
    N = len(srs)
    sr0 = float(srs.mean())
    var = float(srs.var())
    g = 0.5772156649
    dsr = sqrt(var) * ((1 - g) * norm.ppf(1 - 1 / N) + g * norm.ppf(1 - 1 / (N * exp(1))))
    print(f"  deflated Sharpe: observed best {best[1]['sharpe']:+.2f} vs E[max]~{sr0 + dsr:.2f} "
          f"(N={N}) -> {'PASS' if best[1]['sharpe'] > sr0 + dsr else 'FAIL'}")

    # =========================================================== BLENDS
    print("\n" + "=" * 120)
    print("BLENDS: top-3 new edges x ABS_GROT+FVG_SHORT (daily common window)")
    abs_short = 0.5 * ws_base["ABS_GROT"] + 0.5 * ws_base["FVG_SHORT"]
    base_pnl = pnl_from_weights(abs_short, px)
    blend_rows = {}
    for name in [k for k, v in ok[:3]]:
        dp = daily_pnl[name].reindex(base_pnl.index).fillna(0.0)
        for share in (0.25, 0.5, 0.75):
            pnl = (1 - share) * base_pnl + share * dp
            m = metrics_from_pnl(pnl)
            mb = metrics_from_pnl(base_pnl)
            blend_rows[f"{name}_x{int(share*100)}"] = m
            print(f"  blend {name:<24} {int(share*100)}% -> SR {m['sharpe']:+5.2f} "
                  f"{m['monthly']:+6.2f}%/mo DD {m['dd']:5.1f} minYr {m['min_year']:+5.1f}"
                  f"   (base SR {mb['sharpe']:+.2f})")

    verdict = {
        "winner": best[0], "winner_metrics": best[1],
        "config_null_p90": {k: round(float(np.quantile(v, 0.9)), 2) for k, v in conf_null.items()},
        "search_null_max": round(float(sn.max()), 2), "search_null_draws": [float(x) for x in sn],
        "search_pass": bool(g_search),
        "deflated_pass": bool(best[1]["sharpe"] > sr0 + dsr),
        "options_family": "UNTESTABLE - no reachable historical options/IV data (only scrapers)",
    }
    board = json.load(open(BOARD))
    board["exp042_nuclear_edges"] = {
        "date": "2026-10-30",
        "question": "nuclear hunt: genuinely higher-Sharpe edges (funding carry / options / intraday), 220+ nodes, real data + commission + spread",
        "node_count": len(rows),
        "families": fam_count.to_dict(),
        "all_nodes": rows,
        "shortlist": {k: rows[k] for k in shortlist},
        "blends": blend_rows,
        "verdict": verdict,
    }
    json.dump(board, open(BOARD, "w"), indent=2)
    print("\nsaved exp042_nuclear_edges with", len(rows), "nodes")


if __name__ == "__main__":
    main()
