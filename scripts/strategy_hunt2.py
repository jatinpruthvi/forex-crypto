"""EXP-024 — Round-4 strategy hunt: beat the Round-3 champion (BLEND ma150, Calmar 3.92).

New mechanics not tried in rounds 2-3: portfolio vol-targeting, crash filters (5d BTC
breakdown -> flat), per-asset absolute momentum filters, Donchian state systems,
ensemble voting, weekly/golden-cross regime gates, dip v3 with vol filter.

Every variant is appended to reports/strategy_leaderboard.json (cumulative across
rounds) so the best strategy can be selected later. Selection rule (pre-registered):
maximize worst-fold monthly subject to full DD/Mo <= 10, Calmar >= 1.2, maxDD <= 35%;
declared "better than champion" only if Calmar > 3.92.

Run:  SKIP_LEDGER=1 /tmp/venv/bin/python -W ignore scripts/strategy_hunt2.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strategy_hunt as sh  # noqa: E402  (shared harness: portfolio_sim/metrics/builders)
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

_os = os


# ---------------------------------------------------------------- overlays ---
def crash_filter(w, px, thresh=-0.12, hold=5):
    """Flatten everything for `hold` bars after BTC's trailing 5d return < thresh."""
    btc = px["BTC"] if "BTC" in px.columns else px.iloc[:, 0]
    flag = btc.pct_change(5) < thresh
    state, mult = 0, []
    for f in flag.fillna(False):
        if f:
            state = hold
        mult.append(0.0 if state > 0 else 1.0)
        if state > 0:
            state -= 1
    return w.mul(pd.Series(mult, index=w.index, dtype=float), axis=0)


def vol_target(w, px, target=0.30, win=20, cap=(0.2, 1.5)):
    """Scale weights by target/base realized vol (trailing, shifted -> no lookahead)."""
    _, r = sh.portfolio_sim(w, px)
    sig = r.rolling(win).std() * np.sqrt(365.0)
    f = (target / sig).clip(*cap).shift(1).fillna(1.0)
    return w.mul(f, axis=0)


def abs_mom_filter(w, px, lb=60):
    """Only hold coins whose trailing lb-day return is positive (absolute momentum)."""
    return w.where(px.pct_change(lb) > 0, 0.0)


# ---------------------------------------------------------------- builders ---
def w_donchian(px, entry=20, exit_=10):
    """Classic Donchian state machine per asset: long above entry-high, out below exit-low."""
    hi = px.rolling(entry).max().shift(1)
    lo = px.rolling(exit_).min().shift(1)
    in_pos = pd.DataFrame(False, index=px.index, columns=px.columns)
    state = {c: False for c in px.columns}
    vals, his, los = px.values, hi.values, lo.values
    cols = list(px.columns)
    for i in range(len(px)):
        for j, c in enumerate(cols):
            p, h, l = vals[i, j], his[i, j], los[i, j]
            if np.isnan(h) or np.isnan(l):
                continue
            if not state[c] and p > h:
                state[c] = True
            elif state[c] and p < l:
                state[c] = False
            in_pos.iat[i, j] = state[c]
    vol = px.pct_change().rolling(20).std()
    iv = (1.0 / vol).where(in_pos, 0.0)
    w = iv.div(iv.sum(axis=1).replace(0.0, np.nan), axis=0).fillna(0.0)
    return w


def w_ensemble(px, K=5, gate_ma=150):
    """Per-asset vote: momentum rank + long-trend rank - vol rank, gated."""
    mom = px.pct_change(60)
    trend = px / px.rolling(200).mean() - 1.0
    vol = px.pct_change().rolling(20).std()
    score = mom.rank(axis=1) + trend.rank(axis=1) - vol.rank(axis=1)
    sel = score.apply(lambda row: row.nlargest(K).index, axis=1)
    vol20 = px.pct_change().rolling(20).std()
    w = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    for t in px.index:
        chosen = sel.loc[t]
        if len(chosen):
            iv = (1.0 / vol20.loc[t, chosen]).clip(upper=1e6)
            w.loc[t, chosen] = (iv / iv.sum()).values
    gate = (px["BTC"] > px["BTC"].rolling(gate_ma).mean()).astype(float)
    return w.mul(gate, axis=0).fillna(0.0)


def w_weekly_gate(px, builder, wlen=10):
    """Regime gate on BTC weekly close > weekly MA(wlen) (~50 trading days)."""
    w = builder(px)
    btc = px["BTC"] if "BTC" in px.columns else px.iloc[:, 0]
    n = len(btc)
    wk_idx = np.arange(n)[4::5]                      # positional weekly closes
    wk_ma = pd.Series(btc.values[4::5]).rolling(wlen).mean().values
    full = np.full(n, np.nan)
    full[wk_idx] = wk_ma
    daily = pd.Series(full, index=btc.index).ffill()  # map back to daily bars
    gate = (btc > daily).astype(float)
    return w.mul(gate, axis=0).fillna(0.0)


def w_golden_gate(px, builder):
    """Regime gate: BTC MA50 > MA200 (golden-cross state) instead of price>MA."""
    w = builder(px)
    btc = px["BTC"] if "BTC" in px.columns else px.iloc[:, 0]
    gate = (btc.rolling(50).mean() > btc.rolling(200).mean()).astype(float)
    return w.mul(gate, axis=0).fillna(0.0)


def w_dip_v3(px):
    """Dip-buy v3: RSI3<15 above MA100, but skip when BTC<MA150 or BTC vol20 > 90%."""
    w = sh.w_dip_v2(px)
    btc = px["BTC"] if "BTC" in px.columns else px.iloc[:, 0]
    bvol = btc.pct_change().rolling(20).std() * np.sqrt(365.0)
    gate = ((btc > btc.rolling(150).mean()) & (bvol < 0.90)).astype(float)
    return w.mul(gate, axis=0).fillna(0.0)


def _rot(px):
    return sh.w_gated_rot(px, K=5, lb=90, gate_ma=150)


def _blend(px):
    return 0.5 * sh.w_gated_rot(px, gate_ma=150) + 0.5 * sh.w_dip_v2(px)


# ---------------------------------------------------------------- lab --------
def run_round4(px):
    print("=" * 104)
    print("ROUND 4: new mechanics vs champion BLEND ma150 rot50/dip50 (Calmar 3.92)")
    print("pre-registered: max worst-fold monthly s.t. full DD/Mo<=10, Calmar>=1.2, maxDD<=35%")
    print("=" * 104)
    configs = [
        ("P0 CHAMPION BLEND ma150", _blend),
        ("P1 CHAMPION GROT ma150 K5lb90", _rot),
        ("N1 VOL_BLEND 30%", lambda px: vol_target(_blend(px), px, 0.30)),
        ("N2 VOL_BLEND 40%", lambda px: vol_target(_blend(px), px, 0.40)),
        ("N3 VOL_GROT 30%", lambda px: vol_target(_rot(px), px, 0.30)),
        ("N4 CRASH_BLEND", lambda px: crash_filter(_blend(px), px)),
        ("N5 CRASH_GROT", lambda px: crash_filter(_rot(px), px)),
        ("N6 ABS_BLEND", lambda px: abs_mom_filter(_blend(px), px)),
        ("N7 ABS_GROT", lambda px: abs_mom_filter(_rot(px), px)),
        ("N8 SUPER_BLEND", lambda px: vol_target(crash_filter(abs_mom_filter(_blend(px), px), px), px, 0.30)),
        ("N9 DONCHIAN20/10", lambda px: w_donchian(px, 20, 10)),
        ("N10 DONCHIAN55/20", lambda px: w_donchian(px, 55, 20)),
        ("N11 ENSEMBLE_VOTE", lambda px: w_ensemble(px)),
        ("N12 WEEKLY_GATE_BLEND", lambda px: w_weekly_gate(px, _blend)),
        ("N13 GOLDEN_X_BLEND", lambda px: w_golden_gate(px, _blend)),
        ("N14 DIP_V3", lambda px: w_dip_v3(px)),
        ("N15 VOL_SUPER20", lambda px: vol_target(crash_filter(abs_mom_filter(_blend(px), px), px), px, 0.20)),
        ("N16 VOL_BLEND25", lambda px: vol_target(_blend(px), px, 0.25)),
    ]
    rows = []
    for name, builder in configs:
        fm = sh.fold_metrics(builder, px)
        f = fm["full"]
        folds = [fm[f"fold{k}"]["monthly_roi"] for k in (1, 2, 3)]
        worst_fold = min(folds)
        ok = (f["dd_monthly"] <= 10.0 and f["calmar"] >= 1.2 and f["max_dd"] <= 35.0)
        beats = f["calmar"] > 3.92
        rows.append((f["calmar"], name, f, folds, worst_fold, ok, beats))

    rows.sort(reverse=True)
    print(f"  {'config':<32} {'full%':>7} {'DD%':>6} {'Calmar':>7} {'DD/Mo':>6} "
          f"{'folds':>22} {'worstF':>7} QUAL BEATS")
    for cal, name, f, folds, wf, ok, beats in rows:
        print(f"  {name:<32} {f['monthly_roi']:>7.2f} {f['max_dd']:>6.1f} {f['calmar']:>7.2f} "
              f"{f['dd_monthly']:>6.1f} {folds[0]:>+7.2f}/{folds[1]:>+6.2f}/{folds[2]:>+6.2f} "
              f"{wf:>+7.2f} {'YES' if ok else 'no ':>4} {'YES' if beats else 'no'}")
    return rows


def run_lofo4(px):
    print("\n" + "=" * 104)
    print("ROUND-4 LOFO: select on 2 folds -> measure held-out (anti-curve-fit)")
    print("=" * 104)
    configs = [
        ("BLEND ma150", _blend),
        ("VOL_BLEND 30%", lambda px: vol_target(_blend(px), px, 0.30)),
        ("CRASH_BLEND", lambda px: crash_filter(_blend(px), px)),
        ("ABS_BLEND", lambda px: abs_mom_filter(_blend(px), px)),
        ("SUPER_BLEND", lambda px: vol_target(crash_filter(abs_mom_filter(_blend(px), px), px), px, 0.30)),
        ("GROT ma150 K5lb90", _rot),
        ("VOL_GROT 30%", lambda px: vol_target(_rot(px), px, 0.30)),
        ("CRASH_GROT", lambda px: crash_filter(_rot(px), px)),
        ("DIP_V3", lambda px: w_dip_v3(px)),
    ]
    n = len(px)
    bounds = [(0, int(n * 0.38)), (int(n * 0.34), int(n * 0.70)), (int(n * 0.66), n)]
    out = []
    for held in (1, 2, 3):
        train = [k for k in (1, 2, 3) if k != held]
        cands = []
        for name, builder in configs:
            fm = sh.fold_metrics(builder, px)
            tr = [fm[f"fold{k}"] for k in train]
            if all(t["monthly_roi"] > -1.5 for t in tr) and min(t["calmar"] for t in tr) > -0.5:
                cands.append((min(t["monthly_roi"] for t in tr), name, builder))
        cands.sort(reverse=True)
        if not cands:
            print(f"  fold{held}: no candidate qualified on training folds")
            continue
        _, name, builder = cands[0]
        a, b = bounds[held - 1]
        w = builder(px.iloc[max(0, a - 250):b]).reindex(px.iloc[a:b].index).fillna(0.0)
        eq, r = sh.portfolio_sim(w, px.iloc[a:b])
        m = sh.metrics(eq, r)
        out.append((name, held, m))
        print(f"  selected {name:<22} -> HELD-OUT fold{held}: {m['monthly_roi']:+7.2f}%/mo "
              f"| DD {m['max_dd']:5.1f}% | Calmar {m['calmar']:6.2f} | worstM {m['worst_month']:+6.1f}")
    return out


def update_leaderboard(rows, lofo):
    """Cumulative leaderboard across rounds — the user wants saved results for later selection."""
    path = "reports/strategy_leaderboard.json"
    lb = {"description": "Cumulative strategy performance leaderboard (all hunt rounds). "
                         "Select best strategy later from here. Monthly = compound/month; "
                         "dd_monthly = maxDD / monthly (user criterion: <=~10); "
                         "folds = 3 chronological OOS blocks.",
          "updated": "2026-10-28",
          "entries": []}
    if _os.path.exists(path):
        lb = json.load(open(path))
        lb["entries"] = [e for e in lb["entries"] if e.get("round") != 4]  # idempotent re-run

    # seed round-2 A-M results if present
    if _os.path.exists("reports/strategy_hunt_results.json") and not any(
            e.get("round") == 2 for e in lb["entries"]):
        r2 = json.load(open("reports/strategy_hunt_results.json"))["crypto"]
        for name, scopes in r2.items():
            m = scopes["full"] if isinstance(scopes, dict) and "full" in scopes else scopes
            lb["entries"].append({
                "round": 2, "name": name, "scope": "crypto_1d_21c_2020-07..2023-04",
                "monthly_roi": m["monthly_roi"], "ann_roi": m["ann_roi"], "max_dd": m["max_dd"],
                "calmar": m["calmar"], "dd_monthly": m["dd_monthly"], "worst_month": m["worst_month"],
                "sharpe": m.get("sharpe"), "profit_factor": m.get("profit_factor")})

    for cal, name, f, folds, wf, ok, beats in rows:
        lb["entries"].append({
            "round": 4, "name": name, "scope": "crypto_1d_21c_2020-07..2023-04",
            "monthly_roi": f["monthly_roi"], "ann_roi": f["ann_roi"], "max_dd": f["max_dd"],
            "calmar": f["calmar"], "dd_monthly": f["dd_monthly"], "worst_month": f["worst_month"],
            "sharpe": f.get("sharpe"), "profit_factor": f.get("profit_factor"),
            "folds": folds, "worst_fold": wf, "qualifies": ok, "beats_champion": beats})
    for name, held, m in lofo:
        lb["entries"].append({
            "round": 4, "name": f"LOFO heldout fold{held}: {name}", "scope": "held-out fold",
            "monthly_roi": m["monthly_roi"], "ann_roi": m["ann_roi"], "max_dd": m["max_dd"],
            "calmar": m["calmar"], "dd_monthly": m["dd_monthly"], "worst_month": m["worst_month"],
            "sharpe": m.get("sharpe"), "profit_factor": m.get("profit_factor")})

    rankable = [e for e in lb["entries"] if e.get("folds") or e.get("round") == 2]
    rankable.sort(key=lambda e: e.get("calmar", -99), reverse=True)
    lb["selection_guide"] = {
        "best_calmar": rankable[0]["name"] if rankable else None,
        "top5": [{"name": e["name"], "calmar": e["calmar"], "monthly_roi": e["monthly_roi"],
                  "max_dd": e["max_dd"], "dd_monthly": e["dd_monthly"]} for e in rankable[:5]],
        "user_criterion": "dd_monthly <= 10 and calmar >= 1.2 and max_dd <= 35",
    }
    json.dump(lb, open(path, "w"), indent=2)
    n = len(lb["entries"])
    print(f"\nLeaderboard saved: {path} ({n} entries)")
    print("TOP 8 by Calmar:")
    for e in rankable[:8]:
        print(f"  {e['name']:<34} {e['monthly_roi']:+7.2f}%/mo DD {e['max_dd']:5.1f}% "
              f"Calmar {e['calmar']:6.2f} DD/Mo {e['dd_monthly']:5.1f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-lofo", action="store_true")
    args = ap.parse_args()

    px = sh.load_closes_1d()
    rows = run_round4(px)
    lofo = [] if args.no_lofo else run_lofo4(px)
    update_leaderboard(rows, lofo)
