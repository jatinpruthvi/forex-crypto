#!/usr/bin/env python3
"""Strategy Redesign Lab — honest diagnostics + variant research on real data.

Everything runs through execute_shared_pool_sim's audited fill model (bar-start
stop snapshot, SL-first ambiguous bars, net-trade PnL, taker fees on stops and
pyramid adds). No lookahead: indicators are computed on full history with
past-only rolling logic; evaluation windows are chronological slices.

Phases:
  diag   - decompose the CURRENT signal's trades (side / regime / pair / hold)
           on the bench 4h panel and the 21-coin 1d panel.
  sweep  - walk-forward variant research. Variants are fixed hypotheses (no
           per-window fitting). Pre-registered qualification rule:
             crypto-1d OOS half AND forex late half both positive,
             PF > 1.05 on each, and crypto OOS max_dd < 15%.

Usage:
  python scripts/redesign_lab.py              # diag + sweep
  python scripts/redesign_lab.py --phase diag
  python scripts/redesign_lab.py --phase sweep
"""

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import json
import numpy as np
import pandas as pd

from core.analysis.quantum_hybrid_engine import QuantumHybridEngine
from scripts.run_dual_slot_shared_pool_benchmark import execute_shared_pool_sim

BENCH_SPECS = [
    ("DOGE/USDT", "data/timeframes/bench_panel/DOGEUSDT_H4.csv"),
    ("BNB/USDT", "data/timeframes/bench_panel/BNBUSDT_H4.csv"),
    ("XRP/USDT", "data/timeframes/bench_panel/XRPUSDT_H4.csv"),
    ("ADA/USDT", "data/timeframes/bench_panel/ADAUSDT_H4.csv"),
    ("BTC/USDT", "data/timeframes/bench_panel/BTCUSDT_4h.csv"),
    ("LTC/USDT", "data/timeframes/bench_panel/LTCUSDT_H4.csv"),
    ("ETH/USDT", "data/timeframes/bench_panel/ETHUSDT_H4.csv"),
    ("LINK/USDT", "data/timeframes/bench_panel/LINKUSDT_H4.csv"),
]

COINS_1D = ["BTC", "ETH", "BNB", "XRP", "ADA", "DOGE", "LTC", "LINK", "MATIC",
            "ALGO", "ATOM", "CHZ", "EOS", "ETC", "IOTA", "NEO", "TRX", "VET",
            "XLM", "XMR", "XTZ"]

FOREX_SPECS = [
    ("XAU/USD", "data/forex/XAUUSD_H4.csv"),
    ("EUR/USD", "data/forex/EURUSD_H4.csv"),
    ("GBP/USD", "data/forex/GBPUSD_H4.csv"),
    ("EUR/JPY", "data/forex/EURJPY_H4.csv"),
]


def make_engine(maker_fee_pct=0.015, risk=1.5):
    return QuantumHybridEngine(
        initial_capital=1000.0, base_risk_pct=risk, leverage=2.0,
        tier1_pyramid_mult=1.0, tier2_pyramid_mult=0.8,
        tp1_atr=1.8, tp2_atr=3.0, trail_atr=2.0,
        maker_fee_pct=maker_fee_pct, enable_drawdown_throttle=True,
    )


def load_panel(specs, engine, with_research_cols=True):
    """Load CSVs, generate indicators, align timestamps. Returns windowed panel."""
    dfs = {}
    for sym, path in specs:
        df = pd.read_csv(path)
        if "date" in df.columns and "timestamp" not in df.columns:
            df.rename(columns={"date": "timestamp"}, inplace=True)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)
        dfs[sym] = engine.generate_indicators(df)

    timestamps = sorted(list(set.intersection(*[set(dfs[s]["timestamp"]) for s in dfs])))
    aligned = {}
    for sym in dfs:
        aligned[sym] = dfs[sym][dfs[sym]["timestamp"].isin(timestamps)].sort_values(
            "timestamp").reset_index(drop=True)

    if with_research_cols:
        # Per-row research features (all past-only at bar close)
        ret12 = {}
        for sym, d in aligned.items():
            d["range_pos"] = (d["close"] - d["low"]) / (d["high"] - d["low"]).replace(0, np.nan)
            d["atr_sma"] = d["atr"].rolling(20).mean()
            d["vol_ratio"] = d["atr"] / d["atr_sma"].replace(0, np.nan)
            d["ema_dist_atr"] = (d["close"] - d["ema_slow"]) / d["atr"].replace(0, np.nan)
            d["ema_slope_sign"] = np.sign(d["ema_slow"] - d["ema_slow"].shift(50))
            ret12[sym] = d["close"].pct_change(12)
        # Cross-sectional 12-bar momentum rank (1 = strongest), per timestamp
        rank_df = pd.DataFrame(ret12)
        ranks = rank_df.rank(axis=1, ascending=False)
        for sym, d in aligned.items():
            d["mom_rank"] = ranks[sym].values

    months = (pd.Timestamp(timestamps[-1]) - pd.Timestamp(timestamps[0])).days / 30.4375
    return timestamps, aligned, max(months, 0.5)


def window_panel(timestamps, aligned, i0, i1):
    ts = timestamps[i0:i1]
    aligned_w = {s: d.iloc[i0:i1].reset_index(drop=True) for s, d in aligned.items()}
    months = (pd.Timestamp(ts[-1]) - pd.Timestamp(ts[0])).days / 30.4375
    return ts, aligned_w, max(months, 0.35)


# --------------------------------------------------------------------------
# Entry variants (fixed hypotheses; each returns candidate dicts)
# --------------------------------------------------------------------------
def _momo(row, engine, adx_min=20.0):
    c, h, l, o = row["close"], row["high"], row["low"], row["open"]
    atr = row["atr"]
    dh, dl = row["donchian_high"], row["donchian_low"]
    ef, es, vwap = row["ema_fast"], row["ema_slow"], row["vwap"]
    out = []
    if row["adx"] >= adx_min:
        if (c > dh or row["bull_fvg"]) and ef > es and c > vwap:
            out.append({"side": 1, "conviction": row["adx"], "entry": c,
                        "sl": c - atr * 1.5, "tp1": c + atr * engine.tp1_atr,
                        "regime": "MOMO"})
        elif (c < dl or row["bear_fvg"]) and ef < es and c < vwap:
            out.append({"side": -1, "conviction": row["adx"], "entry": c,
                        "sl": c + atr * 1.5, "tp1": c - atr * engine.tp1_atr,
                        "regime": "MOMO"})
    return out


def _mr(row, engine, rsi_lo=38.0, rsi_hi=62.0):
    c, h, l, o = row["close"], row["high"], row["low"], row["open"]
    atr = row["atr"]
    rsi = row["rsi"]
    out = []
    if l <= row["bb_lower"] and rsi < rsi_lo and c > o:
        out.append({"side": 1, "conviction": 100.0 - rsi, "entry": c,
                    "sl": c - atr * 1.2, "tp1": row["bb_mid"], "regime": "MR"})
    elif h >= row["bb_upper"] and rsi > rsi_hi and c < o:
        out.append({"side": -1, "conviction": rsi, "entry": c,
                    "sl": c + atr * 1.2, "tp1": row["bb_mid"], "regime": "MR"})
    return out


def v_long_only(row, sym, engine):
    return [c for c in _momo(row, engine) if c["side"] == 1]


def v_momo_strict(row, sym, engine):
    """Momentum only: deeper ADX + strong-close + volatility expansion."""
    if row.get("range_pos", 1.0) < 0.35:
        return []
    if row.get("vol_ratio", 1.0) < 1.0:
        return []
    return _momo(row, engine, adx_min=25.0)


def v_momo_quality(row, sym, engine):
    """Momentum with strong-close filter only (keep breadth)."""
    if row.get("range_pos", 1.0) < 0.35:
        return []
    return _momo(row, engine, adx_min=20.0)


def v_mr_only(row, sym, engine):
    return _mr(row, engine)


def v_mr_deep(row, sym, engine):
    """Mean reversion only on deeper RSI extremes."""
    return _mr(row, engine, rsi_lo=32.0, rsi_hi=68.0)


def v_hybrid_quality(row, sym, engine):
    """Strong-close momentum + deep-RSI reversion (no weak entries)."""
    out = []
    if row.get("range_pos", 1.0) >= 0.35:
        out += _momo(row, engine, adx_min=20.0)
    out += _mr(row, engine, rsi_lo=32.0, rsi_hi=68.0)
    return out


def v_momo_topq(row, sym, engine):
    """Strong-close momentum, cross-sectionally strongest third only."""
    if row.get("mom_rank", 1.0) > 7.0:
        return []
    return v_momo_quality(row, sym, engine)


def v_momo_tight(row, sym, engine):
    """Strong-close momentum with a tighter stop (1.2x ATR) and smaller TP1."""
    cands = v_momo_quality(row, sym, engine)
    for c in cands:
        atr = row["atr"]
        c["sl"] = c["entry"] - np.sign(c["side"]) * atr * 1.2
    return cands


# ---- Round 2: targeted at the diagnosed no-TP1 leak (crypto-only scope) ----
def v_q_nofvg(row, sym, engine):
    """Quality momentum but ONLY true Donchian breakouts (no FVG escape hatch)."""
    if row.get("range_pos", 1.0) < 0.35:
        return []
    c, atr = row["close"], row["atr"]
    out = []
    if row["adx"] >= 20.0:
        if c > row["donchian_high"] and row["ema_fast"] > row["ema_slow"] and c > row["vwap"]:
            out.append({"side": 1, "conviction": row["adx"], "entry": c,
                        "sl": c - atr * 1.5, "tp1": c + atr * engine.tp1_atr,
                        "regime": "MOMO"})
        elif c < row["donchian_low"] and row["ema_fast"] < row["ema_slow"] and c < row["vwap"]:
            out.append({"side": -1, "conviction": row["adx"], "entry": c,
                        "sl": c + atr * 1.5, "tp1": c - atr * engine.tp1_atr,
                        "regime": "MOMO"})
    return out


def v_q_tight_tp(row, sym, engine):
    """Quality momentum with TP1 at 1.4x ATR (higher TP1-reach rate)."""
    if row.get("range_pos", 1.0) < 0.35:
        return []
    out = _momo(row, engine)
    atr = row["atr"]
    for c in out:
        c["tp1"] = c["entry"] + c["side"] * atr * 1.4
    return out


def v_q_macro_side(row, sym, engine):
    """Quality momentum, only the side aligned with the 50-bar macro slope."""
    slope = row.get("ema_slope_sign", 0.0)
    return [c for c in v_momo_quality(row, sym, engine) if c["side"] == slope]


def v_q_nofvg_tight(row, sym, engine):
    out = v_q_nofvg(row, sym, engine)
    atr = row["atr"]
    for c in out:
        c["tp1"] = c["entry"] + c["side"] * atr * 1.4
    return out


VARIANTS = [
    ("LONG_ONLY", v_long_only),
    ("MOMO_QUALITY", v_momo_quality),
    ("MOMO_STRICT", v_momo_strict),
    ("MR_ONLY", v_mr_only),
    ("MR_DEEP", v_mr_deep),
    ("HYBRID_QUALITY", v_hybrid_quality),
    ("MOMO_TOPQ", v_momo_topq),
    ("MOMO_TIGHT", v_momo_tight),
    ("Q_NOFVG", v_q_nofvg),
    ("Q_TIGHT_TP", v_q_tight_tp),
    ("Q_MACRO_SIDE", v_q_macro_side),
    ("Q_NOFVG_TIGHT", v_q_nofvg_tight),
    ("Q_TS12", v_momo_quality),          # quality + time_stop_bars=12 (run kw)
]


# --------------------------------------------------------------------------
# Reporting helpers
# --------------------------------------------------------------------------
def headline(res):
    return (f"eq ${res['final_equity']:8.2f} | {res['monthly_roi']:+7.2f}%/mo "
            f"| tot {res['net_roi_total']:+8.2f}% | DD {res['max_drawdown']:6.2f}% "
            f"| {res['total_trades']:4d}t | WR {res['win_rate']:5.1f}% "
            f"| PF {res['profit_factor']:.2f}")


def decompose(res, title):
    tl = res["trade_log"]
    print(f"\n--- {title}: {len(tl)} closed trades ---")
    for key, label in (("side", "SIDE"), ("regime", "REGIME")):
        groups = {}
        for t in tl:
            groups.setdefault(t.get(key, "?"), []).append(t["pnl"])
        rows = []
        for k, pnls in sorted(groups.items()):
            w = sum(1 for p in pnls if p > 0)
            gp = sum(p for p in pnls if p > 0)
            gl = abs(sum(p for p in pnls if p < 0)) or 1e-9
            rows.append((k, len(pnls), sum(pnls), 100.0 * w / max(1, len(pnls)), gp / gl))
        print(f"  {label:<7} {'n':>4} {'net $':>10} {'WR%':>6} {'PF':>6}")
        for k, n, net, wr, pf in rows:
            print(f"  {k:<7} {n:>4} {net:>+10.2f} {wr:>6.1f} {pf:>6.2f}")

    pairs = {}
    for t in tl:
        d = pairs.setdefault(t["sym"], {"n": 0, "net": 0.0, "L": 0.0, "S": 0.0})
        d["n"] += 1
        d["net"] += t["pnl"]
        d["L" if t["side"] == "LONG" else "S"] += t["pnl"]
    print(f"  PAIR    {'n':>4} {'net $':>10} {'long $':>10} {'short $':>10}")
    for k, d in sorted(pairs.items(), key=lambda kv: kv[1]["net"]):
        print(f"  {k:<8}{d['n']:>4} {d['net']:>+10.2f} {d['L']:>+10.2f} {d['S']:>+10.2f}")

    buckets = {"1-3 bars": (1, 3), "4-10": (4, 10), "11-30": (11, 30), "31+": (31, 10**9)}
    print(f"  HOLD    {'n':>4} {'net $':>10} {'WR%':>6}")
    for label, (a, b) in buckets.items():
        pnls = [t["pnl"] for t in tl if a <= t.get("bars_held", 0) <= b]
        if not pnls:
            continue
        w = sum(1 for p in pnls if p > 0)
        print(f"  {label:<9}{len(pnls):>4} {sum(pnls):>+10.2f} {100.0*w/len(pnls):>6.1f}")

    for flag in (True, False):
        pnls = [t["pnl"] for t in tl if bool(t.get("tp1_hit")) == flag]
        if pnls:
            w = sum(1 for p in pnls if p > 0)
            tag = "TP1 hit" if flag else "no TP1 "
            print(f"  {tag}  {len(pnls):>4} {sum(pnls):>+10.2f} {100.0*w/len(pnls):>6.1f}")


def run_one(name, entry_fn, ts, aligned, months, engine, **kw):
    res = execute_shared_pool_sim(ts, aligned, engine, months,
                                  max_slots=2, risk_pct=1.5, lev=2.0,
                                  entry_fn=entry_fn, **kw)
    print(f"  {name:<16} {headline(res)}")
    return res


# --------------------------------------------------------------------------
# Phases
# --------------------------------------------------------------------------
def phase_diag():
    print("=" * 105)
    print("PHASE A: WHERE DOES THE CURRENT SIGNAL LOSE?")
    print("=" * 105)

    engine = make_engine()
    ts, aligned, months = load_panel(BENCH_SPECS, engine)
    print(f"\n[A1] Bench 4h panel (8 pairs, {months:.1f} months, EXP-020 window)")
    res = run_one("BASELINE", None, ts, aligned, months, engine)
    decompose(res, "BASELINE on bench 4h")

    engine1d = make_engine()
    ts, aligned, months = load_panel([(f"{c}/USDT", f"data/timeframes/1d_panel/{c}USDT_1d.csv")
                                      for c in COINS_1D], engine1d)
    print(f"\n[A2] Crypto 1d panel (21 coins, {months:.1f} months)")
    res = run_one("BASELINE", None, ts, aligned, months, engine1d)
    decompose(res, "BASELINE on crypto 1d")
    return res


def phase_sweep():
    print("\n" + "=" * 105)
    print("PHASE B: VARIANT WALK-FORWARD (fixed hypotheses, chronological OOS)")
    print("=" * 105)

    # ---- Panel 1: crypto 1d (21 coins, ~2.7y) ----
    engine = make_engine()
    ts, aligned, months = load_panel([(f"{c}/USDT", f"data/timeframes/1d_panel/{c}USDT_1d.csv")
                                      for c in COINS_1D], engine)
    n = len(ts)
    split = int(n * 0.55)
    ts_is, al_is, m_is = window_panel(ts, aligned, 30, split)          # early window
    ts_oos, al_oos, m_oos = window_panel(ts, aligned, split, n)        # late OOS window
    print(f"\n[B1] Crypto 1d 21 coins | full {months:.1f} mo | early {m_is:.1f} mo | late-OOS {m_oos:.1f} mo")
    print(f"  {'variant':<16} {'WINDOW':<10} {'':<1}")
    print("  " + "-" * 100)
    crypto_results = {}
    for name, fn in VARIANTS:
        r_full = run_one(name, fn, ts, aligned, months, engine)
        r_early = run_one(name + "/early", fn, ts_is, al_is, m_is, engine)
        r_oos = run_one(name + "/OOS", fn, ts_oos, al_oos, m_oos, engine)
        crypto_results[name] = {"full": r_full, "early": r_early, "oos": r_oos}
        decompose(r_oos, f"{name} crypto-OOS")

    # ---- Panel 2: forex H4 (4 pairs, ~10.5y) ----
    fengine = make_engine(maker_fee_pct=0.005)   # ~0.5-pip commission proxy
    fts, faligned, fmonths = load_panel(FOREX_SPECS, fengine)
    fn_bars = len(fts)
    fsplit = int(fn_bars * 0.60)
    fts_e, fal_e, fm_e = window_panel(fts, faligned, 30, fsplit)
    fts_l, fal_l, fm_l = window_panel(fts, faligned, fsplit, fn_bars)
    print(f"\n[B2] Forex H4 4 pairs | full {fmonths:.1f} mo | early {fm_e:.1f} mo | late {fm_l:.1f} mo")
    print("  " + "-" * 100)
    forex_results = {}
    for name, fn in VARIANTS:
        r_full = run_one(name, fn, fts, faligned, fmonths, fengine)
        r_early = run_one(name + "/early", fn, fts_e, fal_e, fm_e, fengine)
        r_late = run_one(name + "/late", fn, fts_l, fal_l, fm_l, fengine)
        forex_results[name] = {"full": r_full, "early": r_early, "late": r_late}

    # ---- Pre-registered qualification ----
    print("\n" + "=" * 105)
    print("QUALIFICATION (pre-registered): crypto-OOS monthly > 0, PF > 1.05, DD < 15%;")
    print("forex-late monthly > 0 and PF > 1.05")
    print("=" * 105)
    print(f"  {'variant':<16} {'crypOOS%':>9} {'PF':>5} {'DD%':>6} | {'fxLate%':>8} {'PF':>5} {'DD%':>6} | QUALIFY")
    qualifiers = []
    for name, _ in VARIANTS:
        c = crypto_results[name]["oos"]
        f = forex_results[name]["late"]
        ok = (c["monthly_roi"] > 0 and c["profit_factor"] > 1.05 and c["max_drawdown"] < 15.0
              and f["monthly_roi"] > 0 and f["profit_factor"] > 1.05)
        if ok:
            qualifiers.append(name)
        print(f"  {name:<16} {c['monthly_roi']:>+9.2f} {c['profit_factor']:>5.2f} {c['max_drawdown']:>6.2f} "
              f"| {f['monthly_roi']:>+8.2f} {f['profit_factor']:>5.2f} {f['max_drawdown']:>6.2f} | "
              f"{'YES' if ok else 'no'}")
    print(f"\nQualifiers: {qualifiers if qualifiers else 'NONE'}")

    out = {
        "crypto_1d": {k: {w: {m: v for m, v in r.items() if m != "trade_log" and m != "equity_curve"}
                          for w, r in vv.items()} for k, vv in crypto_results.items()},
        "forex_h4": {k: {w: {m: v for m, v in r.items() if m != "trade_log" and m != "equity_curve"}
                         for w, r in vv.items()} for k, vv in forex_results.items()},
        "qualifiers": qualifiers,
    }
    _os.makedirs("reports", exist_ok=True)
    with open("reports/redesign_lab_results.json", "w") as f:
        json.dump(out, f, indent=2, default=str)
    print("Saved reports/redesign_lab_results.json")
    return qualifiers


def phase_round2():
    """Round-2 validation on crypto only (user scope: crypto-first).

    Amended qualification rule (transparent change from the round-1 rule that
    also gated on forex - user standing constraint is crypto-only-first, and
    this signal family is documented dead on forex H4):
      * crypto-1d OOS window: monthly > 0, PF > 1.05, max_dd < 15%
      * crypto-1d early window: monthly > -3%/mo (no catastrophic in-sample era)
      * bench 4h window (2022-10..2023-04, different granularity): monthly > -3%/mo
    Then a risk ladder (1.25 / 1.0 / 0.75) on qualifiers to fit DD < 15%.
    """
    print("\n" + "=" * 105)
    print("PHASE C: ROUND-2 CRYPTO VALIDATION (targeted at the no-TP1 leak)")
    print("=" * 105)

    engine = make_engine()
    ts, aligned, months = load_panel([(f"{c}/USDT", f"data/timeframes/1d_panel/{c}USDT_1d.csv")
                                      for c in COINS_1D], engine)
    n = len(ts)
    split = int(n * 0.55)
    ts_is, al_is, m_is = window_panel(ts, aligned, 30, split)
    ts_oos, al_oos, m_oos = window_panel(ts, aligned, split, n)

    bengine = make_engine()
    bts, baligned, bmonths = load_panel(BENCH_SPECS, bengine)

    round2 = [
        ("Q_NOFVG", v_q_nofvg, {}),
        ("Q_TIGHT_TP", v_q_tight_tp, {}),
        ("Q_MACRO_SIDE", v_q_macro_side, {}),
        ("Q_NOFVG_TIGHT", v_q_nofvg_tight, {}),
        ("Q_TS12", v_momo_quality, {"time_stop_bars": 12}),
        ("Q_TS8", v_momo_quality, {"time_stop_bars": 8}),
    ]

    results = {}
    print(f"  {'variant':<14} {'1d-full':>22} {'1d-early':>22} {'1d-OOS':>22} {'bench4h':>22}")
    print("  " + "-" * 106)
    for name, fn, kw in round2:
        rf = run_one(name, fn, ts, aligned, months, engine, **kw)
        re_ = run_one(name + "/early", fn, ts_is, al_is, m_is, engine, **kw)
        ro = run_one(name + "/OOS", fn, ts_oos, al_oos, m_oos, engine, **kw)
        rb = run_one(name + "/bench", fn, bts, baligned, bmonths, bengine, **kw)
        results[name] = {"full": rf, "early": re_, "oos": ro, "bench": rb, "kw": kw}

    print("\nQUALIFY (amended, crypto-only): 1d-OOS monthly>0 & PF>1.05 & DD<15%;")
    print("1d-early monthly>-3%; bench monthly>-3%")
    print(f"  {'variant':<14} {'crypOOS%':>9} {'PF':>5} {'DD%':>6} {'early%':>8} {'bench%':>8} | QUALIFY")
    qualifiers = []
    for name, _, _ in round2:
        r = results[name]
        o, e, b = r["oos"], r["early"], r["bench"]
        ok = (o["monthly_roi"] > 0 and o["profit_factor"] > 1.05 and o["max_drawdown"] < 15.0
              and e["monthly_roi"] > -3.0 and b["monthly_roi"] > -3.0)
        if ok:
            qualifiers.append(name)
        print(f"  {name:<14} {o['monthly_roi']:>+9.2f} {o['profit_factor']:>5.2f} {o['max_drawdown']:>6.2f} "
              f"{e['monthly_roi']:>+8.2f} {b['monthly_roi']:>+8.2f} | {'YES' if ok else 'no'}")
    print(f"\nRound-2 qualifiers: {qualifiers if qualifiers else 'NONE'}")

    if qualifiers:
        print("\nRISK LADDER (DD < 15% fit on 1d-OOS + 1d-full):")
        for name in qualifiers:
            fn = dict((n, (f, k)) for n, f, k in round2)[name]
            f_, kw = fn
            for risk in (1.25, 1.0, 0.75):
                e2 = make_engine(risk=risk)
                ro = execute_shared_pool_sim(ts_oos, al_oos, e2, m_oos, max_slots=2,
                                             risk_pct=risk, lev=2.0, entry_fn=f_, **kw)
                rf2 = execute_shared_pool_sim(ts, aligned, e2, months, max_slots=2,
                                              risk_pct=risk, lev=2.0, entry_fn=f_, **kw)
                print(f"  {name} r={risk:<5} OOS: {headline(ro)}")
                print(f"  {'':14} full: {headline(rf2)}")

    _os.makedirs("reports", exist_ok=True)
    with open("reports/redesign_round2_results.json", "w") as f:
        json.dump({k: {w: {m: v for m, v in r.items() if m not in ("trade_log", "equity_curve")}
                       for w, r in vv.items() if w != "kw"} for k, vv in results.items()},
                  f, indent=2, default=str)
    print("\nSaved reports/redesign_round2_results.json")
    return qualifiers


def phase_round3():
    """Risk ladder + rolling 3-fold stability for the round-2 signal-level leads.

    DD scales with position size, so variants passing the signal gates
    (OOS monthly > 0, PF > 1.05) are re-run at lower risk to attempt the
    DD < 15% prop-firm gate. Fold stability: 3 chronological folds on the 1d
    panel, variant fixed, positive-PF required on EVERY fold.

    HONESTY NOTE: the 1d panel has now been used for variant selection, so even
    fold-passing results are selection-adjusted; the final candidate requires
    forward paper validation on fresh data before any ROI claim.
    """
    print("\n" + "=" * 105)
    print("PHASE D: RISK LADDER + FOLD STABILITY (round-2 signal leads)")
    print("=" * 105)

    engine = make_engine()
    ts, aligned, months = load_panel([(f"{c}/USDT", f"data/timeframes/1d_panel/{c}USDT_1d.csv")
                                      for c in COINS_1D], engine)
    n = len(ts)

    leads = [
        ("Q_TIGHT_TP", v_q_tight_tp, {}),
        ("Q_TS8", v_momo_quality, {"time_stop_bars": 8}),
        ("Q_TS12", v_momo_quality, {"time_stop_bars": 12}),
        ("Q_MACRO_SIDE", v_q_macro_side, {}),
    ]

    print("\n[D1] Risk ladder on 1d full / OOS halves:")
    for name, fn, kw in leads:
        for risk in (1.25, 1.0, 0.75, 0.5):
            e = make_engine(risk=risk)
            split = int(n * 0.55)
            _, al_oos, m_oos = window_panel(ts, aligned, split, n)
            ts_oos = ts[split:]
            ro = execute_shared_pool_sim(ts_oos, al_oos, e, m_oos, max_slots=2,
                                         risk_pct=risk, lev=2.0, entry_fn=fn, **kw)
            rf = execute_shared_pool_sim(ts, aligned, e, months, max_slots=2,
                                         risk_pct=risk, lev=2.0, entry_fn=fn, **kw)
            gate = "PASS" if (ro["monthly_roi"] > 0 and ro["profit_factor"] > 1.05
                              and ro["max_drawdown"] < 15.0) else "fail"
            print(f"  {name:<12} r={risk:<5} OOS {headline(ro)} [{gate}]")
            print(f"  {'':12}       full {headline(rf)}")

    print("\n[D2] Rolling 3-fold stability at risk=1.0 (variant fixed):")
    bounds = [(30, int(n * 0.38)), (int(n * 0.34), int(n * 0.70)), (int(n * 0.66), n)]
    for name, fn, kw in leads:
        fold_ok = 0
        line = f"  {name:<12}"
        for k, (a, b) in enumerate(bounds):
            tsk, alk, mk = window_panel(ts, aligned, a, b)
            e = make_engine(risk=1.0)
            r = execute_shared_pool_sim(tsk, alk, e, mk, max_slots=2, risk_pct=1.0,
                                        lev=2.0, entry_fn=fn, **kw)
            ok = r["profit_factor"] > 1.0 and r["monthly_roi"] > -1.0
            fold_ok += int(ok)
            line += f" | F{k+1}: {r['monthly_roi']:+6.2f}%/mo PF {r['profit_factor']:4.2f} DD {r['max_drawdown']:5.1f} {'ok' if ok else 'X '}"
        print(line + f"  -> {fold_ok}/3")
    print()


def phase_personal():
    """Personal-account ROI ceiling: upward risk ladder, no prop-firm DD gate.

    Question: with OUR OWN money (no funded-account rules), how much monthly ROI
    do the redesigned signals deliver at each risk level, and with what
    drawdown? Ladder 1.5% -> 5% risk per trade (lev 2.0, 2 slots, dd-throttle
    at 8% stays ON - it is part of the system). Windows: crypto 1d full / early /
    late-OOS halves + bench 4h. Also a $25 micro-account run through the
    Hyperliquid lot-viability gate.
    """
    print("\n" + "=" * 108)
    print("PHASE E: PERSONAL-ACCOUNT RISK LADDER (no prop-firm gate - honest ROI vs DD)")
    print("=" * 108)

    engine = make_engine()
    ts, aligned, months = load_panel([(f"{c}/USDT", f"data/timeframes/1d_panel/{c}USDT_1d.csv")
                                      for c in COINS_1D], engine)
    n = len(ts)
    split = int(n * 0.55)
    ts_is, al_is, m_is = window_panel(ts, aligned, 30, split)
    ts_oos, al_oos, m_oos = window_panel(ts, aligned, split, n)
    bengine = make_engine()
    bts, baligned, bmonths = load_panel(BENCH_SPECS, bengine)

    leads = [
        ("Q_TIGHT_TP", v_q_tight_tp, {}),
        ("Q_TS8", v_momo_quality, {"time_stop_bars": 8}),
        ("Q_TS12", v_momo_quality, {"time_stop_bars": 12}),
    ]
    risks = [1.5, 2.0, 2.5, 3.0, 4.0, 5.0]

    print(f"\n  {'variant':<12} {'risk':>4} | {'1d-FULL':>26} | {'1d-OOS':>26} | {'bench4h':>22}")
    print("  " + "-" * 104)
    ledger_rows = []
    for name, fn, kw in leads:
        for risk in risks:
            e = make_engine(risk=risk)
            rf = execute_shared_pool_sim(ts, aligned, e, months, max_slots=2,
                                         risk_pct=risk, lev=2.0, entry_fn=fn, **kw)
            ro = execute_shared_pool_sim(ts_oos, al_oos, e, m_oos, max_slots=2,
                                         risk_pct=risk, lev=2.0, entry_fn=fn, **kw)
            rb = execute_shared_pool_sim(bts, baligned, e, bmonths, max_slots=2,
                                         risk_pct=risk, lev=2.0, entry_fn=fn, **kw)
            f_s = f"{rf['monthly_roi']:+6.2f}%/mo DD{rf['max_drawdown']:5.1f}% PF{rf['profit_factor']:4.2f}"
            o_s = f"{ro['monthly_roi']:+6.2f}%/mo DD{ro['max_drawdown']:5.1f}% PF{ro['profit_factor']:4.2f}"
            b_s = f"{rb['monthly_roi']:+6.2f}%/mo DD{rb['max_drawdown']:5.1f}%"
            print(f"  {name:<12} {risk:>4} | {f_s} | {o_s} | {b_s}")
            ledger_rows.append({"variant": name, "risk": risk,
                                "full": {k: rf[k] for k in ("monthly_roi", "max_drawdown", "profit_factor", "total_trades", "final_equity")},
                                "oos": {k: ro[k] for k in ("monthly_roi", "max_drawdown", "profit_factor", "total_trades", "final_equity")},
                                "bench": {k: rb[k] for k in ("monthly_roi", "max_drawdown", "profit_factor", "total_trades", "final_equity")}})

    # Expected-range view: fold spread at the two headline risks
    print("\n[E2] 3-fold spread at risk 2.5% and 4.0% (expected-range view):")
    bounds = [(30, int(n * 0.38)), (int(n * 0.34), int(n * 0.70)), (int(n * 0.66), n)]
    for name, fn, kw in leads:
        for risk in (2.5, 4.0):
            line = f"  {name:<12} r={risk:<4}"
            ms = []
            for k, (a, b) in enumerate(bounds):
                tsk, alk, mk = window_panel(ts, aligned, a, b)
                e = make_engine(risk=risk)
                r = execute_shared_pool_sim(tsk, alk, e, mk, max_slots=2, risk_pct=risk,
                                            lev=2.0, entry_fn=fn, **kw)
                ms.append(r["monthly_roi"])
                line += f" | F{k+1}: {r['monthly_roi']:+6.2f}%/mo DD{r['max_drawdown']:5.1f}%"
            line += f"  -> range {min(ms):+.2f}% .. {max(ms):+.2f}%/mo"
            print(line)

    # $25 micro account through the Hyperliquid lot gate
    print("\n[E3] $25 micro account through Hyperliquid lot-viability gate (risk 3.0%):")
    from core.execution.live_adapter import SizingViabilityGate
    def gate25(sym, eq, price, atr, risk, leverage, dd_mult, stop_atr_mult=1.5):
        g = SizingViabilityGate.check(sym, equity=eq, price=price, atr=atr, risk_pct=risk,
                                      leverage=leverage, dd_factor=dd_mult,
                                      stop_atr_mult=stop_atr_mult, max_error_pct=5.0,
                                      venue="hyperliquid")
        return g["stepped_qty"] if g["viable"] else 0.0
    for name, fn, kw in leads:
        e = make_engine(risk=3.0)
        r = execute_shared_pool_sim(ts, aligned, e, months, max_slots=2, risk_pct=3.0,
                                    lev=2.0, entry_fn=fn, gate_fn=gate25,
                                    initial_capital=25.0, **kw)
        print(f"  {name:<12} $25: eq ${r['final_equity']:7.2f} | {r['monthly_roi']:+6.2f}%/mo "
              f"| DD {r['max_drawdown']:5.1f}% | {r['total_trades']:4d}t | PF {r['profit_factor']:.2f}")

    _os.makedirs("reports", exist_ok=True)
    with open("reports/redesign_personal_ladder.json", "w") as f:
        json.dump({"ladder": ledger_rows,
                   "note": "personal-account risk ladder; no prop-firm gate; dd-throttle 8% on; "
                           "selection-adjusted backtests - forward validation required"},
                  f, indent=2)
    print("\nSaved reports/redesign_personal_ladder.json")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["diag", "sweep", "round2", "round3", "personal", "all"], default="all")
    args = ap.parse_args()
    if args.phase in ("diag", "all"):
        phase_diag()
    if args.phase in ("sweep", "all"):
        phase_sweep()
    if args.phase in ("round2", "all"):
        phase_round2()
    if args.phase in ("round3", "all"):
        phase_round3()
    if args.phase in ("personal", "all"):
        phase_personal()
