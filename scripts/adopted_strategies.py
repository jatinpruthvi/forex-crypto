"""EXP-046b (2026-10-30): ADOPTED STRATEGIES from the GitHub repo mine — testbed.

User: "check is there any strategy we can adopt so we can have higher results."
After scanning >=500 strategy repos (reports/strategy_repo_mine.json), the dominant
implementable families are classic TA systems. This script implements the canonical
rules EXACTLY as such repos standardly define them and tests them on our 5.5y panel
(15 coins daily + BTC/ETH/EQ), FEE 10bp/side (commission+spread), gates DD<=40,
minYr>=-1.5, ranked by ROI %/mo. Placebo top-3 + blend into book R2.

NODES (20 adopted systems x {BTC, ETH, EQ} = 60):
  supertrend(10,3), ichimoku(9,26,52), keltner(20,2xATR10), aroon(25), adx_dmi(14),
  ema_ribbon(8,21,55), macd_hist_flip(12,26,9), psar_flip, boll_rsi(20,2/RSI14-30),
  stochrsi(14,14,3,3), cci(20,+-100), willr(14,-80/-20), zscore_rev(20,+-2),
  obv_trend(20), heikin_trend, turtle(20,55,10,20), rsi_macd_double, mom_volcombo,
  vwap_month_rev, squeeze_daily
"""
import os
import sys
import json

sys.path.insert(0, os.path.abspath("scripts"))

import numpy as np
import pandas as pd

import strategy_hunt as sh
import regime_hunt as rh
import regime_expansion as rx
import five_year_test as ft
from nuclear_edges import metrics_from_pnl, pnl_from_weights

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOARD = os.path.join(BASE_DIR, "reports", "strategy_leaderboard.json")
LEDGER = os.path.join(BASE_DIR, "reports", "roi_progress_ledger.json")
FEE = 0.0010


def supertrend(h, l, c, n=10, mult=3.0):
    hl2 = (h + l) / 2
    atr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1) \
        .rolling(n).mean()
    ub, lb = hl2 + mult * atr, hl2 - mult * atr
    st = pd.Series(np.nan, index=c.index)
    direction = pd.Series(1, index=c.index)
    for i in range(1, len(c)):
        ub.iloc[i] = min(ub.iloc[i], ub.iloc[i - 1]) if c.iloc[i - 1] <= ub.iloc[i - 1] else ub.iloc[i]
        lb.iloc[i] = max(lb.iloc[i], lb.iloc[i - 1]) if c.iloc[i - 1] >= lb.iloc[i - 1] else lb.iloc[i]
        direction.iloc[i] = 1 if c.iloc[i] > ub.iloc[i] else (-1 if c.iloc[i] < lb.iloc[i]
                                                             else direction.iloc[i - 1])
    return direction


def ichimoku(h, l, c):
    tenkan = (h.rolling(9).max() + l.rolling(9).min()) / 2
    kijun = (h.rolling(26).max() + l.rolling(26).min()) / 2
    span_a = ((tenkan + kijun) / 2).shift(26)
    span_b = ((h.rolling(52).max() + l.rolling(52).min()) / 2).shift(26)
    kumo_top = pd.concat([span_a, span_b], axis=1).max(axis=1)
    kumo_bot = pd.concat([span_a, span_b], axis=1).min(axis=1)
    long_sig = (tenkan > kijun) & (c > kumo_top)
    short_sig = (tenkan < kijun) & (c < kumo_bot)
    return pd.Series(np.where(long_sig, 1.0, np.where(short_sig, -1.0, 0.0)), index=c.index) \
        .replace(0, np.nan).ffill().fillna(0.0)


def keltner(c, n=20, atrn=10, mult=2.0):
    ma = c.rolling(n).mean()
    rng = (c.rolling(atrn).std())
    up, dn = ma + mult * rng, ma - mult * rng
    return pd.Series(np.where(c > up, 1.0, np.where(c < dn, -1.0, 0.0)), index=c.index) \
        .replace(0, np.nan).ffill().fillna(0.0)


def aroon(h, l, n=25):
    up = h.rolling(n + 1).apply(lambda s: s.argmax(), raw=True) / n * 100
    dn = l.rolling(n + 1).apply(lambda s: s.argmin(), raw=True) / n * 100
    return pd.Series(np.where((up > 70) & (dn < 30), 1.0,
                              np.where((dn > 70) & (up < 30), -1.0, 0.0)), index=h.index) \
        .replace(0, np.nan).ffill().fillna(0.0)


def adx_dmi(h, l, c, n=14):
    up, dn = h.diff(), -l.diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=h.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=h.index)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(n).mean()
    plus_di = 100 * (plus_dm.rolling(n).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(n).mean() / atr)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.rolling(n).mean()
    return pd.Series(np.where((adx > 25) & (plus_di > minus_di), 1.0,
                              np.where((adx > 25) & (minus_di > plus_di), -1.0, 0.0)),
                     index=h.index).replace(0, np.nan).ffill().fillna(0.0)


def ema_ribbon(c):
    e8, e21, e55 = c.ewm(span=8).mean(), c.ewm(span=21).mean(), c.ewm(span=55).mean()
    return pd.Series(np.where((e8 > e21) & (e21 > e55), 1.0,
                              np.where((e8 < e21) & (e21 < e55), -1.0, 0.0)), index=c.index) \
        .replace(0, np.nan).ffill().fillna(0.0)


def macd_hist_flip(c):
    macd = c.ewm(span=12).mean() - c.ewm(span=26).mean()
    hist = macd - macd.ewm(span=9).mean()
    return np.sign(hist).replace(0, np.nan).ffill().fillna(0.0)


def psar_flip(h, l, c, af=0.02, max_af=0.2):
    sar = pd.Series(np.nan, index=c.index)
    direction = pd.Series(1, index=c.index)
    ep, cur_af = h.iloc[0], af
    sar.iloc[0] = l.iloc[0]
    for i in range(1, len(c)):
        prev = sar.iloc[i - 1]
        sar.iloc[i] = prev + cur_af * (ep - prev)
        if direction.iloc[i - 1] == 1:
            if c.iloc[i] < sar.iloc[i]:
                direction.iloc[i], sar.iloc[i], ep, cur_af = -1, ep, l.iloc[i], af
            else:
                direction.iloc[i] = 1
                if h.iloc[i] > ep:
                    ep, cur_af = h.iloc[i], min(cur_af + af, max_af)
        else:
            if c.iloc[i] > sar.iloc[i]:
                direction.iloc[i], sar.iloc[i], ep, cur_af = 1, ep, h.iloc[i], af
            else:
                direction.iloc[i] = -1
                if l.iloc[i] < ep:
                    ep, cur_af = l.iloc[i], min(cur_af + af, max_af)
    return direction


def boll_rsi(c):
    ma, sd = c.rolling(20).mean(), c.rolling(20).std()
    d = c.diff()
    up_ = d.clip(lower=0).rolling(14).mean()
    dn_ = (-d.clip(upper=0)).rolling(14).mean()
    rsi = 100 - 100 / (1 + up_ / dn_.replace(0, np.nan))
    long_sig = (c < ma - 2 * sd) & (rsi < 30)
    short_sig = (c > ma + 2 * sd) & (rsi > 70)
    return pd.Series(np.where(long_sig, 1.0, np.where(short_sig, -1.0, 0.0)), index=c.index) \
        .replace(0, np.nan).ffill().fillna(0.0)


def stochrsi(c):
    d = c.diff()
    up_ = d.clip(lower=0).rolling(14).mean()
    dn_ = (-d.clip(upper=0)).rolling(14).mean()
    rsi = 100 - 100 / (1 + up_ / dn_.replace(0, np.nan))
    srsi = (rsi - rsi.rolling(14).min()) / (rsi.rolling(14).max() - rsi.rolling(14).min())
    k = srsi.rolling(3).mean()
    return pd.Series(np.where(k < 0.2, 1.0, np.where(k > 0.8, -1.0, 0.0)), index=c.index) \
        .replace(0, np.nan).ffill().fillna(0.0)


def cci(h, l, c, n=20):
    tp = (h + l + c) / 3
    cc = (tp - tp.rolling(n).mean()) / (0.015 * tp.rolling(n).std())
    return pd.Series(np.where(cc < -100, 1.0, np.where(cc > 100, -1.0, 0.0)), index=c.index) \
        .replace(0, np.nan).ffill().fillna(0.0)


def willr(h, l, c, n=14):
    hh, ll = h.rolling(n).max(), l.rolling(n).min()
    wr = -100 * (hh - c) / (hh - ll).replace(0, np.nan)
    return pd.Series(np.where(wr < -80, 1.0, np.where(wr > -20, -1.0, 0.0)), index=c.index) \
        .replace(0, np.nan).ffill().fillna(0.0)


def zscore_rev(c, n=20, thr=2.0):
    z = (c - c.rolling(n).mean()) / c.rolling(n).std().replace(0, np.nan)
    return pd.Series(np.where(z < -thr, 1.0, np.where(z > thr, -1.0, 0.0)), index=c.index) \
        .replace(0, np.nan).ffill().fillna(0.0)


def obv_trend(c, v):
    obv = (np.sign(c.diff()) * v).fillna(0).cumsum()
    return pd.Series(np.where(obv > obv.rolling(20).mean(), 1.0, -1.0), index=c.index)


def heikin_trend(o, h, l, c):
    ha_close = (o + h + l + c) / 4
    ha_open = ((o + c) / 2).shift(1).fillna((o + c) / 2)
    return pd.Series(np.where(ha_close > ha_open, 1.0, -1.0), index=c.index)


def turtle(h, l, c):
    hh20, ll20 = h.rolling(20).max().shift(1), l.rolling(20).min().shift(1)
    hh55, ll55 = h.rolling(55).max().shift(1), l.rolling(55).min().shift(1)
    ll10, hh10 = l.rolling(10).min().shift(1), h.rolling(10).max().shift(1)
    pos = pd.Series(0.0, index=c.index)
    p = 0.0
    for i in range(len(c)):
        ci = c.iloc[i]
        if p == 0:
            if ci > hh55.iloc[i] or ci > hh20.iloc[i]:
                p = 1.0
            elif ci < ll55.iloc[i] or ci < ll20.iloc[i]:
                p = -1.0
        elif p == 1:
            if ci < ll10.iloc[i]:
                p = 0.0
        else:
            if ci > hh10.iloc[i]:
                p = 0.0
        pos.iloc[i] = p
    return pos


def rsi_macd_double(c):
    d = c.diff()
    up_ = d.clip(lower=0).rolling(14).mean()
    dn_ = (-d.clip(upper=0)).rolling(14).mean()
    rsi = 100 - 100 / (1 + up_ / dn_.replace(0, np.nan))
    macd = c.ewm(span=12).mean() - c.ewm(span=26).mean()
    hist = macd - macd.ewm(span=9).mean()
    long_sig = (rsi > 50) & (hist > 0)
    short_sig = (rsi < 50) & (hist < 0)
    return pd.Series(np.where(long_sig, 1.0, np.where(short_sig, -1.0, 0.0)), index=c.index) \
        .replace(0, np.nan).ffill().fillna(0.0)


def mom_volcombo(c):
    mom = c / c.shift(60) - 1
    vol = c.pct_change().rolling(60).std()
    score = mom / vol.replace(0, np.nan)
    return pd.Series(np.where(score > 0.5, 1.0, np.where(score < -0.5, -1.0, 0.0)),
                     index=c.index).replace(0, np.nan).ffill().fillna(0.0)


def vwap_month_rev(o, c):
    idx = c.index
    vwap = c.groupby([idx.year, idx.month]).transform(lambda s: s.expanding().mean())
    dev = c / vwap - 1
    return pd.Series(np.where(dev < -0.02, 1.0, np.where(dev > 0.02, -1.0, 0.0)), index=c.index) \
        .replace(0, np.nan).ffill().fillna(0.0)


def squeeze_daily(c):
    sqz = (c.pct_change().rolling(10).std() / c.pct_change().rolling(50).std() < 0.7)
    sig = sqz.astype(float) * np.sign(c / c.shift(30) - 1)
    return sig


SYSTEMS = {
    "supertrend_10_3": lambda o, h, l, c, v: supertrend(h, l, c),
    "ichimoku_92652": lambda o, h, l, c, v: ichimoku(h, l, c),
    "keltner_20_2": lambda o, h, l, c, v: keltner(c),
    "aroon_25": lambda o, h, l, c, v: aroon(h, l),
    "adx_dmi_14": lambda o, h, l, c, v: adx_dmi(h, l, c),
    "ema_ribbon_82155": lambda o, h, l, c, v: ema_ribbon(c),
    "macd_hist_flip": lambda o, h, l, c, v: macd_hist_flip(c),
    "psar_flip": lambda o, h, l, c, v: psar_flip(h, l, c),
    "boll_rsi_combo": lambda o, h, l, c, v: boll_rsi(c),
    "stochrsi_1433": lambda o, h, l, c, v: stochrsi(c),
    "cci_20": lambda o, h, l, c, v: cci(h, l, c),
    "willr_14": lambda o, h, l, c, v: willr(h, l, c),
    "zscore_rev_20": lambda o, h, l, c, v: zscore_rev(c),
    "obv_trend_20": lambda o, h, l, c, v: obv_trend(c, v),
    "heikin_trend": lambda o, h, l, c, v: heikin_trend(o, h, l, c),
    "turtle_20_55": lambda o, h, l, c, v: turtle(h, l, c),
    "rsi_macd_double": lambda o, h, l, c, v: rsi_macd_double(c),
    "mom_volcombo": lambda o, h, l, c, v: mom_volcombo(c),
    "vwap_month_rev": lambda o, h, l, c, v: vwap_month_rev(o, c),
    "squeeze_daily": lambda o, h, l, c, v: squeeze_daily(c),
}


def main():
    px = ft.load_all_5y()
    rh.MENU = rh.menu_builders()
    import strategy_hunt5 as sh5
    O, H, L, V = sh5._O, sh5._H, sh5._L, sh5._V
    idx, cols = px.index, px.columns
    assets = {"BTC": ["BTC"], "ETH": ["ETH"], "EQ": ["BTC", "ETH"]}

    nodes = {}
    for sname, fn in SYSTEMS.items():
        for an, acols in assets.items():
            w = pd.DataFrame(0.0, index=idx, columns=cols)
            for c_ in acols:
                sig = fn(O[c_], H[c_], L[c_], px[c_], V[c_])
                w[c_] = sig / len(acols)
            nodes[f"{sname}_{an}"] = w

    print("=" * 118)
    print(f"EXP-046b: {len(nodes)} adopted-strategy nodes (20 systems x BTC/ETH/EQ), 10bp/side")
    print("=" * 118)
    rows = {}
    for name, w in nodes.items():
        m = metrics_from_pnl(pnl_from_weights(w, px, FEE))
        if m is None:
            continue
        rows[name] = m
    ok = [(k, v) for k, v in rows.items()
          if v["dd"] <= 40 and v["min_year"] is not None and v["min_year"] >= -1.5]
    ok.sort(key=lambda kv: kv[1]["monthly"], reverse=True)
    print("\nTOP-15 adopted strategies (ROI %/mo, DD<=40, minYr>=-1.5):")
    for k, v in ok[:15]:
        ys = " ".join(f"{y[2:]}:{x:+5.1f}" for y, x in v["yearly"].items())
        print(f"  {k:<26} {v['monthly']:+6.2f}%/mo SR {v['sharpe']:+5.2f} DD {v['dd']:5.1f} "
              f"minYr {v['min_year']:+5.2f} | {ys}")
    if not ok:
        print("  (none)")
    best = ok[0] if ok else max(rows.items(), key=lambda kv: kv[1]["monthly"])

    # placebos on top-3
    print("\nNULLS (30 block-shuffle draws):")
    rng = np.random.default_rng(606)
    null_res = {}
    for name, _ in ok[:3]:
        w = nodes[name]
        nb = int(np.ceil(len(w) / 30))
        draws = []
        for _ in range(30):
            perm = rng.permutation(nb)
            w2 = pd.concat([w.iloc[b * 30:(b + 1) * 30] for b in perm], axis=0)
            w2.index = w.index[:len(w2)]
            w2 = w2.reindex(w.index).fillna(0.0)
            draws.append(metrics_from_pnl(pnl_from_weights(w2, px, FEE))["monthly"])
        dr = np.array(draws)
        p90 = float(np.quantile(dr, 0.9))
        null_res[name] = {"p90": round(p90, 2), "pass": rows[name]["monthly"] >= p90}
        print(f"  {name:<26} real {rows[name]['monthly']:+6.2f} vs null p90 {p90:+6.2f} "
              f"-> {'PASS' if rows[name]['monthly'] >= p90 else 'FAIL'}")

    # blend into R2
    print("\nBLEND top-3 into book R2:")
    ws_b, _ = rx.build_full(px)
    gate = (px["BTC"] > px["BTC"].rolling(100).mean()).astype(float)
    from nuclear_edges import cs_weights as _csw
    w_mom = _csw((px / px.shift(14) - 1), 5, px, gate=gate)
    base_w = 0.75 * (0.5 * ws_b["ABS_GROT"] + 0.5 * ws_b["FVG_SHORT"]).reindex(idx).fillna(0.0) \
        + 0.25 * w_mom
    fund = pd.read_csv(os.path.join(BASE_DIR, "data", "derivatives", "funding_all.csv"))
    fund["date"] = pd.to_datetime(fund["timestamp_ms"], unit="ms").dt.normalize()
    fpiv = fund.pivot_table(index="date", columns="symbol", values="funding_rate", aggfunc="sum")
    fpiv.columns = [c.replace("USDT", "") for c in fpiv.columns]
    fpiv = fpiv.reindex(idx).fillna(0.0)[px.columns]
    w_fund = _csw(fpiv.rolling(7).mean(), 5, px, invert=True)
    fund_pnl = pnl_from_weights(w_fund, px) - (w_fund.fillna(0.0) * fpiv).sum(axis=1)
    r2 = 0.75 * pnl_from_weights(base_w, px) + 0.25 * fund_pnl
    mb = metrics_from_pnl(r2)
    print(f"  R2 base: SR {mb['sharpe']:+.2f} {mb['monthly']:+.2f}%/mo DD {mb['dd']} "
          f"minYr {mb['min_year']:+.2f}")
    blend_rows = {}
    for name, _ in ok[:3]:
        pn = pnl_from_weights(nodes[name], px, FEE)
        for share in (0.10, 0.25):
            m = metrics_from_pnl((1 - share) * r2 + share * pn)
            blend_rows[f"{name}_x{int(share*100)}"] = m
            flag = " <--+" if m["sharpe"] > mb["sharpe"] and m["min_year"] >= mb["min_year"] - 0.1 else ""
            print(f"  +{name:<24} {int(share*100):>2}% -> SR {m['sharpe']:+5.2f} "
                  f"{m['monthly']:+5.2f}%/mo DD {m['dd']:5.1f} minYr {m['min_year']:+5.2f}{flag}")

    board = json.load(open(BOARD))
    board["exp046b_adopted"] = {
        "date": "2026-10-30",
        "question": "adoptable strategies from GitHub mine - tested on 5y with costs",
        "all_nodes": rows,
        "top15": {k: rows[k] for k, v in ok[:15]},
        "placebos": null_res,
        "blends": blend_rows,
        "champion": {"name": best[0], **best[1]},
    }
    json.dump(board, open(BOARD, "w"), indent=2)
    print("\nsaved exp046b_adopted")


if __name__ == "__main__":
    main()
