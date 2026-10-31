"""Independent recomputation of champion book R3.1 (separate inline P&L math).

Copies signal formulas from improve_wave1.py verbatim; computes pnl with fresh
forward-return math (not pnl_from_weights). Compares to reports/adopted_book_r3.json.
"""
import json
import numpy as np
import pandas as pd
import sys

sys.path.insert(0, "scripts")
import five_year_test as ft
import regime_expansion as rx
from nuclear_edges import cs_weights, metrics_from_pnl  # cs_weights for construction; metrics_from_pnl only to compare conventions

px = ft.load_all_5y()
idx, cols = px.index, px.columns
C = 0.0010
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
    """Fresh math: weight at close t earns t->t+1; fee on |dw| at change."""
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

refl = {"monthly": 2.46, "sr": 1.77, "dd": 14.5}   # recorded (ledger EXP-048 / memory R3.1 x1)
days = (book.index[-1] - book.index[0]).days
mo1 = float(book.sum() / (days / 30.4375)) * 100
sr1 = float(book.mean() / max(book.std(), 1e-12) * np.sqrt(365))
eq = (1 + book).cumprod()
dd1 = float((eq / eq.cummax() - 1).min() * 100)
print(f"recomputed x1: {mo1:+.2f}%/mo  SR {sr1:.2f}  DD {dd1:.1f}")
print(f"recorded   x1: {refl['monthly']:+.2f}%/mo  SR {refl['sr']:.2f}  DD {refl['dd']:.1f}")
dmo, dsr, ddd = abs(mo1 - refl["monthly"]), abs(sr1 - refl["sr"]), abs(dd1 - refl["dd"])
print(f"delta (my conventions): {dmo:.4f}pp / {dsr:.4f} / {ddd:.3f}pp (dd sign conv)")
mh = metrics_from_pnl(book)
print(f"fresh pnl via HOUSE metrics_from_pnl: {mh['monthly']:+.2f}%/mo  SR {mh['sharpe']:.2f}  DD {mh['dd']:.1f}")
dmo2, dsr2, ddd2 = abs(mh['monthly'] - refl['monthly']), abs(mh['sharpe'] - refl['sr']), abs(abs(mh['dd']) - refl['dd'])
print(f"delta (house conventions): {dmo2:.4f}pp / {dsr2:.4f} / {ddd2:.3f}pp")
ok = dmo2 < 0.15 and dsr2 < 0.15 and ddd2 < 1.5
print("RECOMPUTE", "MATCHES recorded book (within convention noise)" if ok else "MISMATCH - INVESTIGATE")
json.dump({"recomputed_x1": {"monthly": round(mo1, 2), "sr": round(sr1, 2), "dd": round(dd1, 1)},
           "recorded_x1": refl, "delta": {"monthly_pp": round(dmo, 4), "sr": round(dsr, 4), "dd_pp": round(ddd, 3)},
           "match": bool(ok)}, open("reports/book_recompute_check.json", "w"), indent=1)
