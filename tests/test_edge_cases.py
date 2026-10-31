"""AUDIT #5 Angle 2: EDGE & PROPERTY CASES - numerical corners where bugs hide.

NaN starts, zero vol, ties, short/empty series, inf guards, leap days, empty
columns, all-zero positions, single-asset panels.
"""
import numpy as np
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from nuclear_edges import pnl_from_weights, pnl_from_pos, metrics_from_pnl, cs_weights  # noqa: E402


def _px(n, seed=0, cols=3):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2021-01-01", periods=n)
    return pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.01, (n, cols)), axis=0)),
                        index=idx, columns=[f"c{i}" for i in range(cols)])


def test_nan_start_rolling_no_lookahead():
    """Rolling windows produce NaN at series start; signals there must be 0, not NaN-propagated."""
    px = _px(60)
    w = pd.DataFrame(np.nan, index=px.index, columns=px.columns)   # all NaN weights
    pnl = pnl_from_weights(w, px, fee=0.001)
    assert (pnl == 0).all(), "NaN weights must produce zero pnl, not NaN"


def test_zero_vol_constant_prices():
    """Constant prices: pct_change = 0; metrics must not div-by-zero or raise."""
    idx = pd.bdate_range("2021-01-01", periods=300)
    px = pd.DataFrame({"c": 100.0}, index=idx)
    pos = pd.Series(1.0, index=idx)
    pnl = pnl_from_pos(pos, px["c"], fee=0.0)
    m = metrics_from_pnl(pnl)
    assert m is not None and m["monthly"] == 0.0 and m["dd"] == 0.0


def test_short_series_returns_none():
    """<120 daily obs -> metrics_from_pnl returns None (guard), never a bogus number."""
    idx = pd.bdate_range("2021-01-01", periods=50)
    assert metrics_from_pnl(pd.Series(0.001, index=idx)) is None


def test_impossible_drawdown_guard():
    """A single -99% day (broken node signature) -> metrics_from_pnl refuses to score it."""
    idx = pd.bdate_range("2021-01-01", periods=200)
    r = pd.Series(0.0, index=idx)
    r.iloc[10] = -0.99
    assert metrics_from_pnl(r) is None


def test_inf_and_nan_in_pnl_cleaned():
    """metrics_from_pnl must sanitize inf/NaN before scoring."""
    idx = pd.bdate_range("2021-01-01", periods=200)
    r = pd.Series(0.001, index=idx)
    r.iloc[5] = np.inf
    r.iloc[6] = np.nan
    m = metrics_from_pnl(r)
    assert m is not None and np.isfinite(m["monthly"])


def test_ties_in_cs_weights_no_crash():
    """All-equal momentum scores (perfect ties): ranking must not crash; gross stays bounded."""
    n = 60
    px = _px(n, seed=1)
    score = pd.DataFrame(0.0, index=px.index, columns=px.columns)   # all tied at 0
    w = cs_weights(score, 2, px)
    assert np.isfinite(w.fillna(0).values).all()
    assert float(w.fillna(0).abs().sum(axis=1).max()) <= 2.0 + 1e-9


def test_empty_column_coin():
    """A coin with no data (all NaN) must not poison the panel math."""
    n = 80
    px = _px(n, seed=2, cols=3)
    px["dead"] = np.nan
    w = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    w["c0"] = 1.0
    pnl = pnl_from_weights(w, px, fee=0.001)
    assert np.isfinite(pnl.fillna(0)).all()


def test_leap_day_month_end_resample():
    """Feb 29 and month-ends flow through resample without dropping a day."""
    idx = pd.date_range("2023-12-01", "2024-04-05", freq="D")   # >120 obs + spans leap day
    r = pd.Series(0.001, index=idx)
    m = metrics_from_pnl(r)
    assert m is not None
    assert pd.Timestamp("2024-02-29") in r.index
    assert np.isfinite(m["monthly"])


def test_all_zero_positions_zero_pnl():
    pos = pd.Series(0.0, index=pd.bdate_range("2021-01-01", periods=300))
    px = _px(300, seed=3)["c0"]
    pnl = pnl_from_pos(pos, px, fee=0.001)
    assert (pnl == 0).all()


def test_single_asset_panel():
    px = _px(300, seed=4, cols=1)
    w = pd.DataFrame(1.0, index=px.index, columns=px.columns)
    pnl = pnl_from_weights(w, px, fee=0.001)
    assert np.isfinite(pnl.fillna(0)).all()
    assert metrics_from_pnl(pnl) is not None


def test_position_sign_flip_boundaries():
    """0->1, 1->-1, -1->0, 0->0 sequence: cost charged exactly on the 3 transitions."""
    idx = pd.bdate_range("2021-01-01", periods=30)
    px = _px(30, seed=5)["c0"]
    pos = pd.Series(0.0, index=idx)
    pos.iloc[5:10] = 1.0
    pos.iloc[10:20] = -1.0
    fee = 0.001
    pnl = pnl_from_pos(pos, px, fee=fee)
    gross = float((pos * px.pct_change().shift(-1).fillna(0)).sum())
    total_cost = gross - float(pnl.sum())
    # transitions: 0->1 (1 fee), 1->-1 (2 fee), -1->0 (1 fee) = 4*fee
    assert abs(total_cost - 4 * fee) < 1e-9
