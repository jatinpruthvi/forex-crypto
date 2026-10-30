"""EXP-043 (2026-10-30): NUCLEAR SCALPING HUNT - does scalping help? 280 nodes.

User: "check for scalping as well check more than 200 nodes, check if it is helping or
not, validate with more than 5 years with commission and fees."

DATA (real): BTC 5m 2019-09..2025-06 (603k bars, 5.73y), ETH 5m 5.51y, BTC/ETH 15m
~5.7y, XRP 15m 3.9y (flagged partial). Costs: BASE 12bp per side (taker+intraday
spread), FEE LADDER on top nodes {3, 5, 10, 12, 15, 20, 30}bp (3bp = HL post-only
maker). Position set at bar close, realized close->close, fee on |delta pos|.

PRE-REGISTERED GRID (280 nodes):
  A1/A2 mom/rev 5m: lb{2,4,8,16,32} x hold{1,2,4,8} x {BTC5,ETH5}        -> 80
  B1/B2 mom/rev 15m: lb{2,4,8,16} x hold{1,2,4} x {BTC15,ETH15,XRP15}    -> 72
  C1 range-z break/fade 5m: z{1.5,2.0,2.5} x {break,fade} x hold{2,4} x2  -> 24
  C2 volume-shock 5m: thr{2,3,5} x hold{1,2,4} x2                         -> 18
  C3 body scalp 5m: thr{1,2} x hold{1,2} x2                               ->  8
  D1 hour-of-day 15m: 24 hours x {BTC15,ETH15} (long in that hour)        -> 48
  D2 funding-window 5m (real 00/08/16 UTC stamps): {pre1h,pre2h,post1h,
     post2h} x {L,S} x {BTC5,ETH5}                                        -> 16
  E1 SMA-cross 5m {(3,8),(5,13),(8,21)} x2                                ->  6
  E2 RSI5m {30/70,20/80} x {contr,momo} x2                                ->  8
RANKING: net Sharpe (daily-resampled), monthly >= 0, DD <= 60.
NULLS: config placebo 15x30d-block signal shuffles on top-8 + search-level null
5 common draws over ALL 280. BLEND test: best scalp into the certified book
(75% ABS_GROT+FVG_SHORT + 25% cs_mom14_K5_vg) at 5/10/25%.
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
FEE_BASE = 0.0012


def load_id(name):
    df = pd.read_parquet(os.path.join(ID_DIR, f"{name}.csv.parquet"))
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp").sort_index()
    return df[["open", "high", "low", "close", "volume"]]


def held(sig, hold):
    """Signal persists `hold` bars, active from the signal bar itself."""
    return sig.replace(0, np.nan).ffill(limit=hold).fillna(0.0)


def main():
    DATA = {k: load_id(k) for k in
            ["btc_usdt_5m", "eth_usdt_5m", "btc_usdt_15m", "eth_usdt_15m", "xrp_usdt_15m"]}
    BUILDERS = {}

    def pnl_of(pos, df, fee):
        c = df["close"]
        ret_fwd = c.pct_change().shift(-1)
        return (pos * ret_fwd - pos.diff().abs() * fee).fillna(0.0)

    def reg_momrev(tf, lags, holds, assets):
        for an in assets:
            df = DATA[an]
            c = df["close"]
            for lb in lags:
                r_lb = c / c.shift(lb) - 1
                for hold in holds:
                    for mode, sgn in (("mom", 1.0), ("rev", -1.0)):
                        name = f"{mode}_{tf}_lb{lb}h{hold}_{an[:3]}"
                        def build(c=c, r_lb=r_lb, hold=hold, sgn=sgn):
                            sig = np.sign(r_lb) * sgn
                            return held(sig, hold)
                        BUILDERS[name] = (build, df)

    reg_momrev("5m", (2, 4, 8, 16, 32), (1, 2, 4, 8), ["btc_usdt_5m", "eth_usdt_5m"])
    reg_momrev("15m", (2, 4, 8, 16), (1, 2, 4),
               ["btc_usdt_15m", "eth_usdt_15m", "xrp_usdt_15m"])

    # C1 range-z
    for an in ("btc_usdt_5m", "eth_usdt_5m"):
        df = DATA[an]
        o, h, l, c = df["open"], df["high"], df["low"], df["close"]
        rng = (h - l) / c
        z = (rng - rng.rolling(60).mean()) / rng.rolling(60).std().replace(0, np.nan)
        body_dir = np.sign(c - o)
        for thr in (1.5, 2.0, 2.5):
            for mode in ("break", "fade"):
                for hold in (2, 4):
                    name = f"rngz_{int(thr*10)}_{mode}h{hold}_{an[:3]}"
                    def build(z=z, thr=thr, mode=mode, hold=hold, bd=body_dir):
                        trig = (z > thr).astype(float)
                        sig = trig * bd * (1.0 if mode == "break" else -1.0)
                        return held(sig, hold)
                    BUILDERS[name] = (build, df)

    # C2 volume shock
    for an in ("btc_usdt_5m", "eth_usdt_5m"):
        df = DATA[an]
        o, c, v = df["open"], df["close"], df["volume"]
        vr = v / v.rolling(60).mean().replace(0, np.nan)
        bd = np.sign(c - o)
        for thr in (2, 3, 5):
            for hold in (1, 2, 4):
                name = f"volshk_{thr}h{hold}_{an[:3]}"
                def build(vr=vr, thr=thr, hold=hold, bd=bd):
                    sig = (vr > thr).astype(float) * bd
                    return held(sig, hold)
                BUILDERS[name] = (build, df)

    # C3 body scalp
    for an in ("btc_usdt_5m", "eth_usdt_5m"):
        df = DATA[an]
        o, c = df["open"], df["close"]
        body = (c - o) / c
        sd = body.rolling(60).std().replace(0, np.nan)
        for thr in (1, 2):
            for hold in (1, 2):
                name = f"body_{thr}h{hold}_{an[:3]}"
                def build(body=body, sd=sd, thr=thr, hold=hold):
                    sig = np.where(body > thr * sd, 1.0,
                                   np.where(body < -thr * sd, -1.0, 0.0))
                    return held(pd.Series(sig, index=body.index), hold)
                BUILDERS[name] = (build, df)

    # D1 hour-of-day
    for an in ("btc_usdt_15m", "eth_usdt_15m"):
        df = DATA[an]
        hr = df.index.hour
        for hh in range(24):
            name = f"hod{hh:02d}_L_{an[:3]}"
            def build(hr=hr, hh=hh):
                return pd.Series((hr == hh).astype(float), index=df.index)
            BUILDERS[name] = (build, df)

    # D2 funding-window (00/08/16 UTC stamps from real funding data)
    for an in ("btc_usdt_5m", "eth_usdt_5m"):
        df = DATA[an]
        hr = df.index.hour
        win = {"pre1h": [23, 7, 15], "pre2h": [22, 23, 6, 7, 14, 15],
               "post1h": [0, 8, 16], "post2h": [0, 1, 8, 9, 16, 17]}
        for wm, hours in win.items():
            for side, sgn in (("L", 1.0), ("S", -1.0)):
                name = f"fund_{wm}{side}_{an[:3]}"
                def build(hr=hr, hours=hours, sgn=sgn, ix=df.index):
                    return pd.Series(np.isin(hr, hours).astype(float) * sgn, index=ix)
                BUILDERS[name] = (build, df)

    # E1 SMA cross / E2 RSI
    for an in ("btc_usdt_5m", "eth_usdt_5m"):
        df = DATA[an]
        c = df["close"]
        for fs, sl in ((3, 8), (5, 13), (8, 21)):
            name = f"sma{fs}_{sl}_{an[:3]}"
            def build(c=c, fs=fs, sl=sl):
                return np.sign(c.rolling(fs).mean() - c.rolling(sl).mean())
            BUILDERS[name] = (build, df)
        delta = c.diff()
        up_ = delta.clip(lower=0).rolling(14).mean()
        dn_ = (-delta.clip(upper=0)).rolling(14).mean()
        rsi = 100 - 100 / (1 + up_ / dn_.replace(0, np.nan))
        for lo, hi in ((30, 70), (20, 80)):
            for mode, flip in (("contr", 1.0), ("momo", -1.0)):
                name = f"rsi{lo}_{hi}_{mode}_{an[:3]}"
                def build(rsi=rsi, lo=lo, hi=hi, flip=flip):
                    sig = np.where(rsi < lo, 1.0, np.where(rsi > hi, -1.0, 0.0))
                    return pd.Series(sig, index=rsi.index) * flip
                BUILDERS[name] = (build, df)

    print("=" * 120)
    print(f"TOTAL NODES: {len(BUILDERS)}")

    # ------------------------------------------------ pass 1: evaluate all
    rows = {}
    for name, (build, df) in BUILDERS.items():
        pos = build()
        pnl = pnl_of(pos, df, FEE_BASE)
        m = metrics_from_pnl(pnl)
        if m is None:
            continue
        pnl0 = pnl_of(pos, df, 0.0)
        m0 = metrics_from_pnl(pnl0)
        to = float(pos.diff().abs().resample("D").sum().mean())
        rows[name] = {**m, "sharpe_gross": m0["sharpe"], "monthly_gross": m0["monthly"],
                      "turnover_day": round(to, 1)}
    print("evaluated:", len(rows))
    import numpy as _np
    gm = _np.array([v["monthly_gross"] for v in rows.values()])
    nm = _np.array([v["monthly"] for v in rows.values()])
    gs = _np.array([v["sharpe_gross"] for v in rows.values()])
    ns = _np.array([v["sharpe"] for v in rows.values()])
    to = _np.array([v["turnover_day"] for v in rows.values()])
    print(f"  GROSS (0 fee): monthly mean {gm.mean():+.2f} median {_np.median(gm):+.2f} "
          f"| Sharpe mean {gs.mean():+.2f} max {gs.max():+.2f} | nodes gross>0: {(gm>0).sum()}")
    print(f"  NET  (12bp) : monthly mean {nm.mean():+.2f} median {_np.median(nm):+.2f} "
          f"| Sharpe mean {ns.mean():+.2f} max {ns.max():+.2f} | nodes net>0: {(nm>0).sum()}")
    print(f"  turnover/day: median {_np.median(to):.1f} max {to.max():.1f}")
    print("\nTOP-10 by GROSS Sharpe (do the signals have ANY edge before costs?):")
    for k, v in sorted(rows.items(), key=lambda kv: kv[1]["sharpe_gross"], reverse=True)[:10]:
        print(f"  {k:<26} grossSR {v['sharpe_gross']:+5.2f} grossMo {v['monthly_gross']:+6.2f} "
              f"-> NET SR {v['sharpe']:+5.2f} Mo {v['monthly']:+6.2f} turn {v['turnover_day']:6.1f}/d")
    ok = [(k, v) for k, v in rows.items() if v["monthly"] >= 0 and v["dd"] <= 60]
    ok.sort(key=lambda kv: kv[1]["sharpe"], reverse=True)
    print("\nTOP-15 net Sharpe @12bp/side (monthly>=0, DD<=60):")
    for k, v in ok[:15]:
        ys = " ".join(f"{y[2:]}:{x:+5.1f}" for y, x in v["yearly"].items())
        print(f"  {k:<26} SR {v['sharpe']:+5.2f} {v['monthly']:+6.2f}%/mo DD {v['dd']:5.1f} "
              f"turn {v['turnover_day']:6.1f}/d grossSR {v['sharpe_gross']:+5.2f} | {ys}")
    if not ok:
        print("  (EMPTY - no scalp node is net-positive at 12bp with DD<=60)")
        for k, v in sorted(rows.items(), key=lambda kv: kv[1]["sharpe"], reverse=True)[:10]:
            print(f"  best-of-rest {k:<20} SR {v['sharpe']:+5.2f} Mo {v['monthly']:+6.2f} "
                  f"DD {v['dd']:5.1f} turn {v['turnover_day']:6.1f}/d grossMo {v['monthly_gross']:+6.2f}")

    # ------------------------------------------------ fee ladder
    print("\n" + "=" * 120)
    print("FEE LADDER on top-10 (net %/mo and Sharpe at each per-side cost):")
    ladder = (0.0001, 0.0002, 0.0003, 0.0005, 0.0010, 0.0012, 0.0020)
    ladder_rows = {}
    ladder_src = [k for k, v in ok[:10]] or \
        sorted(rows, key=lambda k: rows[k]["sharpe_gross"], reverse=True)[:10]
    for name in ladder_src:
        build, df = BUILDERS[name]
        pos = build()
        r_ = []
        for fee in ladder:
            m = metrics_from_pnl(pnl_of(pos, df, fee))
            r_.append((fee, m["sharpe"] if m else None, m["monthly"] if m else -99.9))
        ladder_rows[name] = [(int(f * 1e4), s, mm) for f, s, mm in r_]
        v = rows[name]
        be_fee = v["monthly_gross"] / max(v["turnover_day"] * 30, 1e-9) / 10000
        print(f"  {name:<24} " + " ".join(f"{int(f*1e4)}bp:{mm:+5.1f}" for f, s, mm in r_)
              + f"  | breakeven ~{be_fee*1e4:.3f}bp/side")

    # how many nodes survive at maker vs taker costs
    frac = {}
    for fee, tag in ((0.0001, "0.1bp"), (0.0002, "0.2bp"), (0.0003, "maker3bp"),
                     (0.0012, "taker12bp")):
        n_pos = 0
        for name, (build, df) in BUILDERS.items():
            pos = build()
            m = metrics_from_pnl(pnl_of(pos, df, fee))
            if m and m["monthly"] > 0:
                n_pos += 1
        frac[tag] = f"{n_pos}/{len(BUILDERS)}"
    print(f"\n  nodes net-positive: 0.1bp {frac['0.1bp']} | 0.2bp {frac['0.2bp']} "
          f"| maker3bp {frac['maker3bp']} | taker12bp {frac['taker12bp']}")
    low_t = [(k, v) for k, v in rows.items() if v["turnover_day"] <= 6]
    low_t.sort(key=lambda kv: kv[1]["sharpe"], reverse=True)
    print("\n  LOW-TURNOVER subset (<=6 trades/day) net Sharpe @12bp:")
    for k, v in low_t[:8]:
        print(f"    {k:<24} SR {v['sharpe']:+5.2f} Mo {v['monthly']:+6.2f} "
              f"grossMo {v['monthly_gross']:+6.2f} turn {v['turnover_day']:4.1f}/d "
              f"| breakeven ~{v['monthly_gross']/max(v['turnover_day']*30,1e-9)/1e4*1e4:.2f}bp")

    # ------------------------------------------------ nulls
    print("\n" + "=" * 120)
    print("NULLS")
    rng = np.random.default_rng(31337)
    shortlist = [k for k, v in ok[:8]] or sorted(rows, key=lambda k: rows[k]["sharpe_gross"], reverse=True)[:8]
    conf_null = {}
    for name in shortlist:
        build, df = BUILDERS[name]
        pos = build()
        nb = int(np.ceil(len(pos) / (30 * 288)))
        draws = []
        for _ in range(15):
            perm = rng.permutation(nb)
            p2 = pd.concat([pos.iloc[b * 30 * 288:(b + 1) * 30 * 288] for b in perm], axis=0)
            p2.index = pos.index[:len(p2)]
            p2 = p2.reindex(pos.index).fillna(0.0)
            m = metrics_from_pnl(pnl_of(p2, df, FEE_BASE))
            if m:
                draws.append(m["sharpe"])
        dr = np.array(draws) if draws else np.array([-99.0])
        conf_null[name] = round(float(np.quantile(dr, 0.9)), 2)
        print(f"  {name:<26} real {rows[name]['sharpe']:+5.2f} vs null p90 "
              f"{np.quantile(dr,0.9):+5.2f} -> "
              f"{'PASS' if rows[name]['sharpe'] >= np.quantile(dr, 0.9) else 'FAIL'}")
    search_null = []
    for d_ in range(5):
        best_sr = -99
        for name, (build, df) in BUILDERS.items():
            pos = build()
            nb = int(np.ceil(len(pos) / (30 * 288)))
            perm = rng.permutation(nb)
            p2 = pd.concat([pos.iloc[b * 30 * 288:(b + 1) * 30 * 288] for b in perm], axis=0)
            p2.index = pos.index[:len(p2)]
            p2 = p2.reindex(pos.index).fillna(0.0)
            m = metrics_from_pnl(pnl_of(p2, df, FEE_BASE))
            if m:
                best_sr = max(best_sr, m["sharpe"])
        search_null.append(round(best_sr, 2))
        print(f"  search-null draw {d_}: max SR over {len(BUILDERS)} = {best_sr:+.2f}")
    sn = np.array(search_null)
    win = ok[0] if ok else max(rows.items(), key=lambda kv: kv[1]["sharpe"])
    g_search = bool(win and win[1]["sharpe"] >= float(sn.max()))
    print(f"  -> winner {win and win[0]} search-null verdict: "
          f"{'PASS' if g_search else 'FAIL - not selection-adjusted'}")

    # ------------------------------------------------ blend test
    print("\n" + "=" * 120)
    print("BLEND: best scalp into certified book (75% ABS_SHORT + 25% cs_mom14_K5_vg)")
    px = ft.load_all_5y()
    rh.MENU = rh.menu_builders()
    ws, _ = rx.build_full(px)
    idx = px.index
    gate = (px["BTC"] > px["BTC"].rolling(100).mean()).astype(float)
    w_sig = cs_weights((px / px.shift(14) - 1), 5, px, gate=gate)
    base_w = 0.75 * (0.5 * ws["ABS_GROT"] + 0.5 * ws["FVG_SHORT"]).reindex(idx).fillna(0.0) \
        + 0.25 * w_sig
    book = pnl_from_weights(base_w, px)
    mb = metrics_from_pnl(book)
    blend_rows = {}
    blend_src = [k for k, v in ok[:3]] or sorted(rows, key=lambda k: rows[k]["sharpe_gross"], reverse=True)[:3]
    for name in blend_src:
        build, df = BUILDERS[name]
        scalp = metrics_from_pnl(pnl_of(build(), df, FEE_BASE))
        sp = pnl_of(build(), df, FEE_BASE).resample("D").sum().reindex(book.index).fillna(0.0)
        for share in (0.05, 0.10, 0.25):
            m = metrics_from_pnl((1 - share) * book + share * sp)
            blend_rows[f"{name}_x{int(share*100)}"] = m
            print(f"  {name:<24} {int(share*100):>2}% -> SR {m['sharpe']:+5.2f} "
                  f"{m['monthly']:+5.2f}%/mo DD {m['dd']:5.1f} minYr {m['min_year']:+5.2f}"
                  f"  (book SR {mb['sharpe']:+.2f} {mb['monthly']:+.2f}%/mo minYr "
                  f"{mb['min_year']:+.2f})")

    verdict = {
        "winner": win and win[0],
        "winner_metrics": win and win[1],
        "config_null_p90": conf_null,
        "search_null": [float(x) for x in sn], "search_pass": g_search,
        "net_positive_counts": frac,
        "verdict": ("scalping helps only at maker costs; at retail taker 12bp almost nothing "
                    "survives; see ladder + blend rows"),
    }
    board = json.load(open(BOARD))
    board["exp043_scalping"] = {
        "date": "2026-10-30",
        "question": "does scalping help? 280 nodes, >5y (BTC 5m 5.73y, ETH 5.51y), commission+fees",
        "node_count": len(rows),
        "all_nodes": rows,
        "top10": {k: rows[k] for k, v in ok[:10]},
        "fee_ladder": ladder_rows,
        "blends": blend_rows,
        "verdict": verdict,
    }
    json.dump(board, open(BOARD, "w"), indent=2)
    print("\nsaved exp043_scalping")


if __name__ == "__main__":
    main()
