#!/usr/bin/env python3
"""Strategy Hunt: genuinely different strategy ARCHETYPES, judged by ROI:drawdown.

The old breakout/slot family is retired (peak DD ~10x monthly ROI). This lab
tests portfolio-level mechanics on the same honest data:

  A XSEC_MOM   cross-sectional momentum rotation (long top-K coins, weekly)
  B TSMOM_VOL  CTA-style per-coin trend, volatility-targeted sizing
  C XSEC_TREND momentum rotation + per-coin trend filter (no falling knives)
  D XSEC_LS    long top-K / short bottom-K (dollar-neutral)
  E MR_RSI2    Connors-style RSI(2) pullback buys in uptrend
  F XSEC_REV   short-term reversal (buy the 5-day losers)
  G DIP_TREND  buy dips (RSI(3)<20) above the long MA, exit on bounce
  H BTC_TSMOM  single-asset BTC trend + vol target (sanity anchor)

Accounting: target weights computed at close t from data through t only;
returns realized t->t+1; turnover charged taker fees; gross exposure capped.
Judge: max_dd / monthly_roi ratio (user criterion), Calmar (ann/max_dd),
% positive months, worst month. 3 chronological folds + full period.

  python scripts/strategy_hunt.py                 # full hunt
  python scripts/strategy_hunt.py --refine        # + refinement grid of top archetypes
"""

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import json
import numpy as np
import pandas as pd

COINS = ["BTC", "ETH", "BNB", "XRP", "ADA", "DOGE", "LTC", "LINK", "MATIC",
         "ALGO", "ATOM", "CHZ", "EOS", "ETC", "IOTA", "NEO", "TRX", "VET",
         "XLM", "XMR", "XTZ"]

FEE = 0.0010          # 10 bps per side of turnover (taker + slippage, crypto)
FEE_FX = 0.0005       # 5 bps forex spread proxy


def load_closes_1d():
    frames = {}
    for c in COINS:
        df = pd.read_csv(f"data/timeframes/1d_panel/{c}USDT_1d.csv")
        df["date"] = pd.to_datetime(df["date"])
        frames[c] = df.set_index("date")["close"]
    px = pd.DataFrame(frames).sort_index().dropna(how="any")
    return px


def load_forex_daily():
    frames = {}
    for name, path in [("XAU", "data/forex/XAUUSD_H4.csv"), ("EUR", "data/forex/EURUSD_H4.csv"),
                       ("GBP", "data/forex/GBPUSD_H4.csv"), ("EURJPY", "data/forex/EURJPY_H4.csv")]:
        df = pd.read_csv(path)
        tcol = "timestamp" if "timestamp" in df.columns else df.columns[0]
        df[tcol] = pd.to_datetime(df[tcol])
        s = df.set_index(tcol)["close"].resample("1D").last().dropna()
        frames[name] = s
    px = pd.DataFrame(frames).sort_index().dropna(how="any")
    return px


def portfolio_sim(weights: pd.DataFrame, px: pd.DataFrame, fee=FEE,
                  lev_cap=2.0, initial=1000.0):
    """weights[t] = target gross weights (dates x symbols), set at close t.
    Realized return t->t+1. Turnover charged `fee` on |delta weight|."""
    w = weights.fillna(0.0).reindex(px.index).fillna(0.0)
    gross = w.abs().sum(axis=1)
    scale = np.where(gross > lev_cap, lev_cap / gross.replace(0, np.nan), 1.0)
    w = w.mul(pd.Series(scale, index=w.index), axis=0)

    ret = px.pct_change().shift(-1)          # return realized AFTER weight is set
    port_ret = (w * ret).sum(axis=1) - w.diff().abs().sum(axis=1) * fee
    port_ret = port_ret.fillna(0.0).replace([np.inf, -np.inf], 0.0)

    equity = initial * (1.0 + port_ret).cumprod()
    return equity, port_ret


def metrics(equity: pd.Series, port_ret: pd.Series):
    n_days = max(1, (equity.index[-1] - equity.index[0]).days)
    years = n_days / 365.25
    final = float(equity.iloc[-1])
    ann = (final / float(equity.iloc[0])) ** (1.0 / max(years, 0.2)) - 1.0
    run_max = equity.cummax()
    dd = (equity / run_max - 1.0)
    max_dd = float(-dd.min()) * 100.0

    monthly = equity.resample("ME").last()
    mret = monthly.pct_change().dropna()
    monthly_roi = ((final / float(equity.iloc[0])) ** (1.0 / max(years * 12.0, 1.0)) - 1.0) * 100.0
    pos_m = float((mret > 0).mean()) * 100.0 if len(mret) else 0.0
    worst_m = float(mret.min()) * 100.0 if len(mret) else 0.0
    calmar = (ann * 100.0) / max_dd if max_dd > 0 else float("inf")
    dd_monthly = max_dd / abs(monthly_roi) if abs(monthly_roi) > 0.1 else float("inf")
    return {
        "monthly_roi": round(monthly_roi, 2),
        "ann_roi": round(ann * 100.0, 1),
        "max_dd": round(max_dd, 1),
        "calmar": round(calmar, 2),
        "dd_monthly": round(dd_monthly, 1),
        "pos_months": round(pos_m, 0),
        "worst_month": round(worst_m, 1),
    }


def fold_metrics(build_weights, px, fee=FEE, lev_cap=2.0):
    n = len(px)
    bounds = [(0, int(n * 0.38)), (int(n * 0.34), int(n * 0.70)), (int(n * 0.66), n)]
    out = {}
    for k, (a, b) in enumerate(bounds):
        w = build_weights(px.iloc[max(0, a - 250):b])       # lookback context pre-window
        w = w.iloc[a - max(0, a - 250):]
        sub_px = px.iloc[a:b]
        w = w.reindex(sub_px.index).fillna(0.0)
        eq, r = portfolio_sim(w, sub_px, fee=fee, lev_cap=lev_cap)
        out[f"fold{k+1}"] = metrics(eq, r)
    w = build_weights(px)
    eq, r = portfolio_sim(w, px, fee=fee, lev_cap=lev_cap)
    out["full"] = metrics(eq, r)
    return out


# --------------------------------------------------------------------------
# Signal builders (each: px -> weights DataFrame, data through t only)
#
# NOTE (found by first hunt run): weight matrices must write EXPLICIT zeros for
# dropped assets on rebalance bars. A `.replace(0, nan).ffill()` carries stale
# weights forever ("zombie positions") and produces absurd drawdowns. Builders
# below write full rows (selected + explicit zeros) on rebalance bars with NaN
# elsewhere, then ffill the holding period only.
# --------------------------------------------------------------------------
def _held(rows_map, px):
    """rows_map: {integer position: pd.Series full weights}. Hold via ffill."""
    w = pd.DataFrame(np.nan, index=px.index, columns=px.columns)
    for i, row in rows_map.items():
        w.iloc[i] = row
    return w.ffill().fillna(0.0)


def w_xsec_mom(px, K=5, lb=60, skip=5, rb=5):
    mom = px.shift(skip) / px.shift(skip + lb) - 1.0
    rows = {}
    for i in range(lb + skip + 1, len(px), rb):
        row = mom.iloc[i].dropna()
        if len(row) == 0:
            continue
        k = min(K, len(row))
        sel = row.nlargest(k).index
        wrow = pd.Series(0.0, index=px.columns)     # explicit zeros for dropped
        wrow[sel] = 1.0 / k
        rows[i] = wrow
    return _held(rows, px)


def w_tsmom_vol(px, lb=100, ann_vol=0.25, rb=5):
    ret = px.pct_change()
    mom = px.shift(3) / px.shift(3 + lb) - 1.0
    vol = ret.rolling(20).std() * np.sqrt(365.0)
    sig = np.sign(mom)
    size = (ann_vol / vol.replace(0, np.nan)).clip(upper=4.0)
    w_raw = (sig * size).where(vol.notna() & mom.notna(), 0.0).fillna(0.0)
    rows = {i: w_raw.iloc[i] for i in range(0, len(px), rb)}
    return _held(rows, px)


def w_xsec_trend(px, K=5, lb=60, rb=5, ma=50):
    mom = px.shift(5) / px.shift(5 + lb) - 1.0
    above = px > px.rolling(ma).mean()
    rows = {}
    for i in range(lb + 6, len(px), rb):
        row = mom.iloc[i].dropna()
        ok = above.iloc[i].reindex(row.index).fillna(False)
        row = row[ok]
        wrow = pd.Series(0.0, index=px.columns)
        if len(row) > 0:
            k = min(K, len(row))
            wrow[row.nlargest(k).index] = 1.0 / k
        rows[i] = wrow
    return _held(rows, px)


def w_xsec_ls(px, K=4, lb=60, rb=5):
    mom = px.shift(5) / px.shift(5 + lb) - 1.0
    rows = {}
    for i in range(lb + 6, len(px), rb):
        row = mom.iloc[i].dropna()
        wrow = pd.Series(0.0, index=px.columns)
        if len(row) >= 2 * K:
            wrow[row.nlargest(K).index] = 0.5 / K
            wrow[row.nsmallest(K).index] = -0.5 / K
        rows[i] = wrow
    return _held(rows, px)


def w_mr_rsi2(px, ma=200):
    w = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    for col in px.columns:
        s = px[col]
        delta = s.diff()
        gain = delta.clip(lower=0).rolling(2).mean()
        loss = (-delta.clip(upper=0)).rolling(2).mean().replace(0, np.nan)
        rsi2 = 100.0 - 100.0 / (1.0 + gain / loss)
        up = s > s.rolling(ma).mean()
        entry = (rsi2 < 10.0) & up
        pos = 0.0
        hold = 0
        for i in range(len(s)):
            if pos > 0:
                hold += 1
                if hold >= 3 or (not np.isnan(rsi2.iloc[i]) and rsi2.iloc[i] > 60.0):
                    pos = 0.0
                    hold = 0
            elif bool(entry.iloc[i]):
                pos = 1.0
                hold = 0
            w.iloc[i, w.columns.get_loc(col)] = pos / len(px.columns)
    return w


def w_xsec_rev(px, look=5, K=3, hold=2):
    mom = px / px.shift(look) - 1.0
    w = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    i = look + 1
    while i < len(px):
        row = mom.iloc[i].dropna()
        if len(row) > K:
            bot = row.nsmallest(K).index
            end = min(i + hold, len(px) - 1)
            w.loc[px.index[i]:px.index[end], bot] = 1.0 / K   # window = position
        i += hold
    return w


def w_dip_trend(px, ma=100):
    w = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    for col in px.columns:
        s = px[col]
        delta = s.diff()
        gain = delta.clip(lower=0).rolling(3).mean()
        loss = (-delta.clip(upper=0)).rolling(3).mean().replace(0, np.nan)
        rsi3 = 100.0 - 100.0 / (1.0 + gain / loss)
        up = s > s.rolling(ma).mean()
        entry = (rsi3 < 20.0) & up
        rmax5 = s.rolling(5).max()
        pos, hold = 0.0, 0
        for i in range(len(s)):
            if pos > 0:
                hold += 1
                exit_now = hold >= 5
                if not exit_now and i > 0:
                    exit_now = s.iloc[i] >= rmax5.iloc[i - 1]
                if exit_now:
                    pos = 0.0
                    hold = 0
            elif bool(entry.iloc[i]):
                pos = 1.0
                hold = 0
            w.iloc[i, w.columns.get_loc(col)] = pos / len(px.columns)
    return w


def w_btc_tsmom(px, lb=100, ann_vol=0.25):
    col = "BTC" if "BTC" in px.columns else px.columns[0]
    ret = px[col].pct_change()
    mom = np.sign(px[col].shift(3) / px[col].shift(3 + lb) - 1.0)
    vol = (ret.rolling(20).std() * np.sqrt(365.0)).replace(0, np.nan)
    w = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    w[col] = (mom * (ann_vol / vol)).clip(-1.0, 1.0).fillna(0.0)
    return w


def w_xsec_gated(px, K=5, lb=60, skip=5, rb=5, gate_ma=200):
    """Cross-sectional momentum, long-only while BTC is above its gate MA.
    (Risk-off kills the bear-market bleed - the main DD source.)"""
    base = w_xsec_mom(px, K=K, lb=lb, skip=skip, rb=rb)
    btc = px["BTC"] if "BTC" in px.columns else px.iloc[:, 0]
    gate = (btc > btc.rolling(gate_ma).mean()).astype(float)
    return base.mul(gate, axis=0).fillna(0.0)


def w_dip_v2(px, ma=100, rsi_thr=15.0, max_hold=8):
    """Dip-buyer v2: panel-fair sizing, tighter entry, hard time exit."""
    w = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    n = len(px.columns)
    for col in px.columns:
        s_ = px[col]
        delta = s_.diff()
        gain = delta.clip(lower=0).rolling(3).mean()
        loss = (-delta.clip(upper=0)).rolling(3).mean().replace(0, np.nan)
        rsi3 = 100.0 - 100.0 / (1.0 + gain / loss)
        up = s_ > s_.rolling(ma).mean()
        entry = (rsi3 < rsi_thr) & up
        rmax5 = s_.rolling(5).max()
        pos, hold = 0.0, 0
        for i in range(len(s_)):
            if pos > 0:
                hold += 1
                exit_now = hold >= max_hold
                if not exit_now and i > 0:
                    exit_now = s_.iloc[i] >= rmax5.iloc[i - 1]
                if exit_now:
                    pos = 0.0
                    hold = 0
            elif bool(entry.iloc[i]):
                pos = 1.0
                hold = 0
            w.iloc[i, w.columns.get_loc(col)] = pos / n
    return w


def w_dual_mom(px, lb=90, rb=21):
    """Dual momentum on majors: hold the stronger of BTC/ETH only if its
    absolute momentum is positive, else cash; vol-scaled to 25% ann."""
    cols = [c for c in ("BTC", "ETH") if c in px.columns] or list(px.columns[:2])
    sub = px[cols]
    mom = sub / sub.shift(lb) - 1.0
    ret = sub.pct_change()
    vol = (ret.rolling(20).std() * np.sqrt(365.0)).replace(0, np.nan)
    rows = {}
    for i in range(lb + 1, len(px), rb):
        wrow = pd.Series(0.0, index=px.columns)
        m = mom.iloc[i].dropna()
        if len(m) == 0:
            rows[i] = wrow
            continue
        pick = m.idxmax()
        if m[pick] > 0:
            wrow[pick] = min(1.0, 0.25 / vol[pick].iloc[i]) if vol[pick].iloc[i] > 0 else 1.0
        rows[i] = wrow
    return _held(rows, px)


def w_gated_rot(px, K=5, lb=60, rb=5, gate_ma=200):
    """Gated rotation with inverse-vol weights among the top-K (risk parity)."""
    mom = px.shift(5) / px.shift(5 + lb) - 1.0
    btc = px["BTC"] if "BTC" in px.columns else px.iloc[:, 0]
    gate = btc > btc.rolling(gate_ma).mean()
    vol = px.pct_change().rolling(20).std().replace(0, np.nan)
    rows = {}
    for i in range(lb + 6, len(px), rb):
        wrow = pd.Series(0.0, index=px.columns)
        if bool(gate.iloc[i]):
            row = mom.iloc[i].dropna()
            if len(row) > 0:
                k = min(K, len(row))
                sel = row.nlargest(k).index
                inv = (1.0 / vol[sel].iloc[i]).fillna(0.0)
                if inv.sum() > 0:
                    wrow[sel] = inv / inv.sum()
        rows[i] = wrow
    return _held(rows, px)


def w_blend(px):
    """50/50 gated-rotation + dip-buyer (two different return sources)."""
    a = w_gated_rot(px)
    b = w_dip_v2(px)
    return 0.5 * a + 0.5 * b


ARCHETYPES = [
    ("A XSEC_MOM", lambda px: w_xsec_mom(px)),
    ("B TSMOM_VOL", lambda px: w_tsmom_vol(px)),
    ("C XSEC_TREND", lambda px: w_xsec_trend(px)),
    ("D XSEC_LS", lambda px: w_xsec_ls(px)),
    ("E MR_RSI2", lambda px: w_mr_rsi2(px)),
    ("F XSEC_REV", lambda px: w_xsec_rev(px)),
    ("G DIP_TREND", lambda px: w_dip_trend(px)),
    ("H BTC_TSMOM", lambda px: w_btc_tsmom(px)),
    ("I BLEND_60_40", lambda px: w_blend(px)),
    ("J XSEC_GATED", lambda px: w_xsec_gated(px)),
    ("K DIP_V2", lambda px: w_dip_v2(px)),
    ("L DUAL_MOM", lambda px: w_dual_mom(px)),
    ("M GATED_ROT", lambda px: w_gated_rot(px)),
]


def print_table(rows):
    print(f"  {'strategy':<14} {'scope':<6} {'monthly%':>9} {'ann%':>7} {'maxDD%':>7} "
          f"{'Calmar':>7} {'DD/Mo':>6} {'posM%':>5} {'worstM%':>7}")
    print("  " + "-" * 84)
    for name, scope, m in rows:
        print(f"  {name:<14} {scope:<6} {m['monthly_roi']:>9.2f} {m['ann_roi']:>7.1f} "
              f"{m['max_dd']:>7.1f} {m['calmar']:>7.2f} {m['dd_monthly']:>6.1f} "
              f"{m['pos_months']:>5.0f} {m['worst_month']:>7.1f}")


def run_hunt(px, fee, label):
    print(f"\n=== {label}: {px.shape[1]} assets, {px.index[0].date()} .. {px.index[-1].date()} ===")
    rows = []
    results = {}
    for name, builder in ARCHETYPES:
        fm = fold_metrics(builder, px, fee=fee)
        results[name] = fm
        for scope in ("fold1", "fold2", "fold3", "full"):
            rows.append((name, scope, fm[scope]))
    print_table(rows)
    return results


def w_gated_equal(px, gate_ma=200):
    """Passive baseline: equal-weight ALL coins while BTC > gate MA, cash otherwise."""
    btc = px["BTC"] if "BTC" in px.columns else px.iloc[:, 0]
    gate = (btc > btc.rolling(gate_ma).mean()).astype(float)
    w = pd.DataFrame(1.0 / len(px.columns), index=px.index, columns=px.columns)
    return w.mul(gate, axis=0).fillna(0.0)


def run_refine(px):
    print("\n" + "=" * 100)
    print("REFINE: blend / gate / rotation grid  (pre-registered: max WORST-fold monthly,")
    print("        s.t. full DD/Mo <= 10, Calmar >= 1.2, full maxDD <= 35%)")
    print("=" * 100)
    configs = []
    for gate_ma in (150, 200, 250):
        for K in (4, 5, 7):
            for lb in (40, 60, 90):
                configs.append((f"GATED_ROT ma{gate_ma} K{K} lb{lb}",
                                lambda px, g=gate_ma, k=K, l=lb: w_gated_rot(px, K=k, lb=l, gate_ma=g)))
    for gate_ma in (150, 200):
        for mix in (0.4, 0.5, 0.6):
            configs.append((f"BLEND ma{gate_ma} rot{int(mix*100)}/dip{int((1-mix)*100)}",
                            lambda px, g=gate_ma, m=mix: m * w_gated_rot(px, gate_ma=g) + (1 - m) * w_dip_v2(px)))
    configs.append(("PASSIVE_GATED ma200", lambda px: w_gated_equal(px)))
    configs.append(("PASSIVE_GATED ma150", lambda px: w_gated_equal(px, gate_ma=150)))
    configs.append(("BLEND+L rot45/dip35/dual20",
                    lambda px: 0.45 * w_gated_rot(px) + 0.35 * w_dip_v2(px) + 0.20 * w_dual_mom(px)))

    rows = []
    for name, builder in configs:
        fm = fold_metrics(builder, px)
        f = fm["full"]
        folds = [fm[f"fold{k}"]["monthly_roi"] for k in (1, 2, 3)]
        worst_fold = min(folds)
        ok = (f["dd_monthly"] <= 10.0 and f["calmar"] >= 1.2 and f["max_dd"] <= 35.0)
        rows.append((worst_fold, name, f, folds, ok))

    rows.sort(reverse=True)
    print(f"  {'config':<34} {'worstFold':>9} {'fold1':>7} {'fold2':>7} {'fold3':>7} "
          f"{'full%':>7} {'DD%':>6} {'Calmar':>7} {'DD/Mo':>6} QUAL")
    for wf, name, f, folds, ok in rows:
        print(f"  {name:<34} {wf:>+9.2f} {folds[0]:>+7.2f} {folds[1]:>+7.2f} {folds[2]:>+7.2f} "
              f"{f['monthly_roi']:>7.2f} {f['max_dd']:>6.1f} {f['calmar']:>7.2f} {f['dd_monthly']:>6.1f} "
              f"{'YES' if ok else 'no'}")
    winners = [(n, f, fl) for wf, n, f, fl, ok in rows if ok]
    return winners


def run_lofo(px):
    """Leave-one-fold-out: select config on two folds (pre-registered rule),
    measure on the held-out fold. The honest out-of-sample estimate."""
    print("\n" + "=" * 100)
    print("LOFO VALIDATION: select on 2 folds -> measure on held-out fold (anti-curve-fit)")
    print("=" * 100)
    configs = []
    for gate_ma in (150, 200):
        for K in (4, 5, 7):
            for lb in (40, 60, 90):
                configs.append((f"GATED_ROT ma{gate_ma} K{K} lb{lb}",
                                lambda px, g=gate_ma, k=K, l=lb: w_gated_rot(px, K=k, lb=l, gate_ma=g)))
        for mix in (0.4, 0.5, 0.6):
            configs.append((f"BLEND ma{gate_ma} rot{int(mix*100)}/dip{int((1-mix)*100)}",
                            lambda px, g=gate_ma, m=mix: m * w_gated_rot(px, gate_ma=g) + (1 - m) * w_dip_v2(px)))
    configs.append(("DIP_V2", lambda px: w_dip_v2(px)))

    n = len(px)
    bounds = [(0, int(n * 0.38)), (int(n * 0.34), int(n * 0.70)), (int(n * 0.66), n)]
    heldout_rows = []
    for held in (1, 2, 3):
        train_folds = [k for k in (1, 2, 3) if k != held]
        cands = []
        for name, builder in configs:
            fm = fold_metrics(builder, px)
            tr = [fm[f"fold{k}"] for k in train_folds]
            f_full_ok = all(t["monthly_roi"] > -1.0 for t in tr)
            worst = min(t["monthly_roi"] for t in tr)
            cal = min(t["calmar"] for t in tr)
            if f_full_ok and cal > 0:
                cands.append((worst, cal, name, builder))
        cands.sort(reverse=True)
        if not cands:
            print(f"  fold{held}: no candidate qualified on training folds")
            continue
        worst, cal, name, builder = cands[0]
        a, b = bounds[held - 1]
        w = builder(px.iloc[max(0, a - 250):b])
        w = w.reindex(px.iloc[a:b].index).fillna(0.0)
        eq, r = portfolio_sim(w, px.iloc[a:b])
        m = metrics(eq, r)
        heldout_rows.append((name, held, m))
        print(f"  selected on folds {[f for f in train_folds]}: {name:<26} "
              f"(train worst {worst:+.2f}%/mo)")
        print(f"  -> HELD-OUT fold{held}: {m['monthly_roi']:+7.2f}%/mo | DD {m['max_dd']:5.1f}% "
              f"| Calmar {m['calmar']:6.2f} | DD/Mo {m['dd_monthly']:5.1f} | worstM {m['worst_month']:+6.1f}")
    return heldout_rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--refine", action="store_true")
    args = ap.parse_args()

    px = load_closes_1d()
    crypto = run_hunt(px, FEE, "CRYPTO 1D (21 coins, honest fees 10bp)")

    fpx = load_forex_daily()
    forex = run_hunt(fpx, FEE_FX, "FOREX DAILY (4 pairs, 5bp spread proxy)")

    # headline ranking by full-period Calmar with dd_monthly <= 10
    print("\n=== RANKING (full period, Calmar, requiring DD/Mo <= 10) ===")
    allr = []
    for src, res in (("crypto", crypto), ("forex", forex)):
        for name, fm in res.items():
            f = fm["full"]
            allr.append((f["calmar"], src, name, f))
    allr.sort(reverse=True)
    for cal, src, name, f in allr:
        flag = "OK" if f["dd_monthly"] <= 10 and f["calmar"] >= 0.5 else "  "
        print(f"  [{flag}] {src:<7} {name:<14} Calmar {cal:>5.2f} | {f['monthly_roi']:+.2f}%/mo "
              f"| DD {f['max_dd']:.1f}% | DD/Mo {f['dd_monthly']:.1f} | pos {f['pos_months']:.0f}%")

    winners = []
    if args.refine:
        winners = run_refine(px)
        lofo = run_lofo(px)
    else:
        lofo = []

    _os.makedirs("reports", exist_ok=True)
    with open("reports/strategy_hunt_results.json", "w") as f:
        json.dump({"crypto": crypto, "forex": forex,
                   "refine_winners": [(n, f) for n, f, _ in winners],
                   "lofo": [(n, k, m) for n, k, m in lofo]}, f, indent=2)
    print("\nSaved reports/strategy_hunt_results.json")
