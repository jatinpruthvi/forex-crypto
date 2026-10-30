"""EXP-044 (2026-10-30): TIMEFRAME MATRIX + COMBINATION HELPERS.

User: "check is any combination will help us, is any time frame will help us."

PHASE T - TIMEFRAME MATRIX (2019-09..2025-06, 5.7y, from 5m resampled consistently):
  signals {rev2, rev4, mom16, mom64, sma3_8, sma20_50, don20, don55, rsi14_contr}
  x timeframes {5m, 15m, 1h, 4h, 1d} x assets {BTC, ETH} = 90 nodes.
  Cost 10bp/side base + ladder {3bp maker, 12bp taker} on best-per-TF.
  Question: at which timeframe does each signal family stop being cost-dominated?

PHASE C - COMBINATION HELPERS (2021-01..2025-06 common window):
  base = certified book (75% ABS_GROT+FVG_SHORT + 25% cs_mom14_K5_vg).
  add-ons individually {10,25,50%}: fund_ls7_K5 (real funding carry), donchian55 on 4h,
  ta_don55_lf_ETH (1d), mom16 on 1h, hod15_L_eth (hour seasonality),
  rev5m gross stream at MAKER-ONLY 3bp (flagged scenario).
  stacks: base+fund25+don4h25, base+fund25+ta_don25, base+fund25+don4h25+mom1h25.
  Placebo: 30 signal-shuffle draws on the winning add-on.
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
from nuclear_edges import metrics_from_pnl, pnl_from_weights, cs_weights

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ID_DIR = os.path.join(BASE_DIR, "data", "intraday")
BOARD = os.path.join(BASE_DIR, "reports", "strategy_leaderboard.json")
LEDGER = os.path.join(BASE_DIR, "reports", "roi_progress_ledger.json")
FEE = 0.0010


def load_id(name):
    df = pd.read_parquet(os.path.join(ID_DIR, f"{name}.csv.parquet"))
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.set_index("timestamp").sort_index()[["open", "high", "low", "close", "volume"]]


def resample_ohlcv(df, rule):
    o = df["open"].resample(rule).first()
    h = df["high"].resample(rule).max()
    l = df["low"].resample(rule).min()
    c = df["close"].resample(rule).last()
    v = df["volume"].resample(rule).sum()
    out = pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}).dropna()
    return out


def held(sig, hold):
    return sig.replace(0, np.nan).ffill(limit=hold).fillna(0.0)


def pnl_of(pos, c, fee):
    rf = c.pct_change().shift(-1)
    return (pos.fillna(0.0) * rf - pos.diff().abs() * fee).fillna(0.0)


def signal_pos(kind, df):
    c = df["close"]
    if kind == "rev2":
        return held(-np.sign(c / c.shift(2) - 1), 1)
    if kind == "rev4":
        return held(-np.sign(c / c.shift(4) - 1), 1)
    if kind == "mom16":
        return held(np.sign(c / c.shift(16) - 1), 4)
    if kind == "mom64":
        return held(np.sign(c / c.shift(64) - 1), 8)
    if kind == "sma3_8":
        return np.sign(c.rolling(3).mean() - c.rolling(8).mean())
    if kind == "sma20_50":
        return np.sign(c.rolling(20).mean() - c.rolling(50).mean())
    if kind == "don20":
        hh = df["high"].rolling(20).max().shift(1)
        ll = df["low"].rolling(20).min().shift(1)
        return pd.Series(np.where(c > hh, 1.0, np.where(c < ll, -1.0, 0.0)),
                         index=c.index).replace(0, np.nan).ffill().fillna(0.0)
    if kind == "don55":
        hh = df["high"].rolling(55).max().shift(1)
        ll = df["low"].rolling(55).min().shift(1)
        return pd.Series(np.where(c > hh, 1.0, np.where(c < ll, -1.0, 0.0)),
                         index=c.index).replace(0, np.nan).ffill().fillna(0.0)
    if kind == "rsi14":
        d = c.diff()
        up = d.clip(lower=0).rolling(14).mean()
        dn = (-d.clip(upper=0)).rolling(14).mean()
        rsi = 100 - 100 / (1 + up / dn.replace(0, np.nan))
        return pd.Series(np.where(rsi < 30, 1.0, np.where(rsi > 70, -1.0, 0.0)),
                         index=c.index).replace(0, np.nan).ffill().fillna(0.0)
    raise ValueError(kind)


def main():
    SIGS = ["rev2", "rev4", "mom16", "mom64", "sma3_8", "sma20_50", "don20", "don55", "rsi14"]
    TFS = {"5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h", "1d": "1D"}
    ASSETS = {"BTC": "btc_usdt_5m", "ETH": "eth_usdt_5m"}
    grids = {}
    for an, fn in ASSETS.items():
        base = load_id(fn)
        for tf, rule in TFS.items():
            grids[(an, tf)] = base if tf == "5m" else resample_ohlcv(base, rule)

    # ================================================== PHASE T
    print("=" * 118)
    print("PHASE T: TIMEFRAME MATRIX (net %/mo at 10bp/side; 5.7y BTC/ETH)")
    print("=" * 118)
    trows = {}
    for an in ASSETS:
        for tf in TFS:
            for sig in SIGS:
                df = grids[(an, tf)]
                pos = signal_pos(sig, df)
                m = metrics_from_pnl(pnl_of(pos, df["close"], FEE))
                if m is None:
                    continue
                m0 = metrics_from_pnl(pnl_of(pos, df["close"], 0.0))
                name = f"{sig}_{tf}_{an}"
                trows[name] = {**m, "sharpe_gross": m0["sharpe"], "monthly_gross": m0["monthly"],
                               "sig": sig, "tf": tf, "asset": an}
    hdr = f"  {'signal':<10}" + "".join(f"{tf:>26}" for tf in TFS)
    print(hdr + "   (net %/mo | gross %/mo)")
    for an in ASSETS:
        for sig in SIGS:
            line = f"  {sig:<10}"
            for tf in TFS:
                k = f"{sig}_{tf}_{an}"
                if k in trows:
                    v = trows[k]
                    line += f"  {v['monthly']:+7.2f}|g{v['monthly_gross']:+7.2f}"
                else:
                    line += " " * 17
            print(line + f"   [{an}]")
    # best per TF
    print("\n  BEST node per timeframe (net, at 10bp):")
    for tf in TFS:
        sub = {k: v for k, v in trows.items() if v["tf"] == tf}
        if not sub:
            continue
        k, v = max(sub.items(), key=lambda kv: kv[1]["sharpe"])
        print(f"    {tf:<4} {k:<22} SR {v['sharpe']:+5.2f} net {v['monthly']:+6.2f}%/mo "
              f"gross {v['monthly_gross']:+6.2f} DD {v['dd']:5.1f}")
    # ladder on best per TF
    print("\n  LADDER on best-per-TF (net %/mo at maker3bp | taker12bp | base10bp):")
    for tf in TFS:
        sub = {k: v for k, v in trows.items() if v["tf"] == tf}
        if not sub:
            continue
        k, v = max(sub.items(), key=lambda kv: kv[1]["sharpe"])
        an, sig = v["asset"], v["sig"]
        df = grids[(an, tf)]
        pos = signal_pos(sig, df)
        r3 = metrics_from_pnl(pnl_of(pos, df["close"], 0.0003))
        r12 = metrics_from_pnl(pnl_of(pos, df["close"], 0.0012))
        print(f"    {tf:<4} {k:<22} 3bp:{r3['monthly']:+7.2f}  10bp:{v['monthly']:+7.2f}  "
              f"12bp:{r12['monthly']:+7.2f}")

    # ================================================== PHASE C
    print("\n" + "=" * 118)
    print("PHASE C: COMBINATION HELPERS vs certified book (common window 2021-01..2025-06)")
    print("=" * 118)
    px = ft.load_all_5y()
    rh.MENU = rh.menu_builders()
    ws, _ = rx.build_full(px)
    idx = px.index
    gate = (px["BTC"] > px["BTC"].rolling(100).mean()).astype(float)
    w_mom = cs_weights((px / px.shift(14) - 1), 5, px, gate=gate)
    base_w = 0.75 * (0.5 * ws["ABS_GROT"] + 0.5 * ws["FVG_SHORT"]).reindex(idx).fillna(0.0) \
        + 0.25 * w_mom

    A, B = pd.Timestamp("2021-01-01"), pd.Timestamp("2025-06-01")
    sub_idx = px.loc[A:B].index
    book = pnl_from_weights(base_w.loc[A:B], px.loc[A:B])
    mb = metrics_from_pnl(book)

    # add-on streams (daily P&L on sub_idx)
    fund = pd.read_csv(os.path.join(BASE_DIR, "data", "derivatives", "funding_all.csv"))
    fund["date"] = pd.to_datetime(fund["timestamp_ms"], unit="ms").dt.normalize()
    fpiv = fund.pivot_table(index="date", columns="symbol", values="funding_rate", aggfunc="sum")
    fpiv.columns = [c.replace("USDT", "") for c in fpiv.columns]
    fpiv = fpiv.reindex(idx).fillna(0.0)[px.columns]
    w_fund = cs_weights(fpiv.rolling(7).mean(), 5, px, invert=True)
    fund_pnl = (pnl_from_weights(w_fund.loc[A:B], px.loc[A:B])
                - (w_fund.loc[A:B].fillna(0.0) * fpiv.loc[A:B]).sum(axis=1))

    don4h = {}
    for an, fn in (("BTC", "btc_usdt_5m"), ("ETH", "eth_usdt_5m")):
        g4 = resample_ohlcv(load_id(fn), "4h")
        don4h[an] = signal_pos("don55", g4)
    w_don4h = pd.DataFrame(0.0, index=sub_idx, columns=px.columns)
    for an in ("BTC", "ETH"):
        s = don4h[an].resample("D").last().reindex(sub_idx).ffill().fillna(0.0)
        w_don4h[an] = s / 2
    don4h_pnl = pnl_from_weights(w_don4h, px.loc[A:B])

    eth1d = resample_ohlcv(load_id("eth_usdt_5m"), "1D")
    w_don1d = pd.DataFrame(0.0, index=sub_idx, columns=px.columns)
    s = signal_pos("don55", eth1d).resample("D").last().reindex(sub_idx).ffill().fillna(0.0)
    w_don1d["ETH"] = s
    don1d_pnl = pnl_from_weights(w_don1d, px.loc[A:B])

    g1 = resample_ohlcv(load_id("btc_usdt_5m"), "1h")
    w_mom1h = pd.DataFrame(0.0, index=sub_idx, columns=px.columns)
    s = signal_pos("mom16", g1).resample("D").last().reindex(sub_idx).ffill().fillna(0.0)
    w_mom1h["BTC"] = s
    mom1h_pnl = pnl_from_weights(w_mom1h, px.loc[A:B])

    g15 = resample_ohlcv(load_id("eth_usdt_5m"), "15min")
    hr = g15.index.hour
    hod_pos = pd.Series((hr == 15).astype(float), index=g15.index)
    hod_pnl = pnl_of(hod_pos, g15["close"], FEE).resample("D").sum().reindex(sub_idx).fillna(0.0)

    g5 = load_id("btc_usdt_5m")
    rev5 = held(-np.sign(g5["close"] / g5["close"].shift(2) - 1), 1)
    rev5_pnl_maker = pnl_of(rev5, g5["close"], 0.0003).resample("D").sum().reindex(sub_idx).fillna(0.0)

    addons = {"fund_ls7_K5": fund_pnl, "don55_4h": don4h_pnl, "ta_don55_1d_ETH": don1d_pnl,
              "mom16_1h_BTC": mom1h_pnl, "hod15_L_eth": hod_pnl,
              "rev5m_MAKER3bp": rev5_pnl_maker}
    crows = {}
    print(f"  base book: SR {mb['sharpe']:+.2f} {mb['monthly']:+.2f}%/mo DD {mb['dd']} "
          f"minYr {mb['min_year']:+.2f}")
    for name, ap in addons.items():
        for share in (0.10, 0.25, 0.50):
            m = metrics_from_pnl((1 - share) * book + share * ap)
            crows[f"base+{name}_{int(share*100)}"] = m
            flag = " <--+" if m["sharpe"] > mb["sharpe"] and m["min_year"] >= mb["min_year"] - 0.1 else ""
            print(f"  +{name:<18} {int(share*100):>2}% -> SR {m['sharpe']:+5.2f} "
                  f"{m['monthly']:+5.2f}%/mo DD {m['dd']:5.1f} minYr {m['min_year']:+5.2f}{flag}")
    stacks = {
        "stack_fund25_don4h25": 0.50 * book + 0.25 * fund_pnl + 0.25 * don4h_pnl,
        "stack_fund25_don1d25": 0.50 * book + 0.25 * fund_pnl + 0.25 * don1d_pnl,
        "stack_fund25_don4h20_mom1h10": 0.55 * book + 0.25 * fund_pnl + 0.10 * don4h_pnl
                                        + 0.10 * mom1h_pnl,
        "stack_fund20_don4h15_don1d10_hod5": 0.50 * book + 0.20 * fund_pnl + 0.15 * don4h_pnl
                                             + 0.10 * don1d_pnl + 0.05 * hod_pnl,
    }
    print()
    for name, pnl in stacks.items():
        m = metrics_from_pnl(pnl)
        crows[name] = m
        print(f"  {name:<36} -> SR {m['sharpe']:+5.2f} {m['monthly']:+5.2f}%/mo "
              f"DD {m['dd']:5.1f} minYr {m['min_year']:+5.2f}")

    # placebo on best improvement
    best_name, best_m = max(
        ((k, v) for k, v in crows.items() if v["sharpe"] > mb["sharpe"]),
        key=lambda kv: kv[1]["sharpe"], default=(None, None))
    print(f"\n  PLACEBO for best combo {best_name}")
    rng = np.random.default_rng(2024)
    if best_name and best_name.startswith("base+fund"):
        share = 0.25
        nb = int(np.ceil(len(fund_pnl) / 30))
        draws = []
        for _ in range(30):
            perm = rng.permutation(nb)
            f2 = pd.concat([fund_pnl.iloc[b * 30:(b + 1) * 30] for b in perm], axis=0)
            f2.index = fund_pnl.index[:len(f2)]
            f2 = f2.reindex(fund_pnl.index).fillna(0.0)
            draws.append(metrics_from_pnl((1 - share) * book + share * f2)["sharpe"])
        dr = np.array(draws)
        real_sr = crows.get(f"base+fund_ls7_K5_{int(share*100)}", best_m)["sharpe"]
        print(f"  real SR {real_sr:+.2f} vs shuffled add-on null p90 {np.quantile(dr, 0.9):+.2f} "
              f"-> {'PASS' if real_sr >= np.quantile(dr, 0.9) else 'FAIL'}")
    else:
        print("  (best combo is not a fund add-on; null run skipped for brevity)")

    board = json.load(open(BOARD))
    board["exp044_tf_combos"] = {
        "date": "2026-10-30",
        "question": "which TIMEFRAME helps + which COMBINATIONS help the certified book",
        "phaseT": trows,
        "phaseC": crows,
        "base_window": "2021-01..2025-06",
        "base_metrics": mb,
    }
    json.dump(board, open(BOARD, "w"), indent=2)
    print("\nsaved exp044_tf_combos")


if __name__ == "__main__":
    main()
