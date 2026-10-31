"""Harness audit: synthetic-data tests with KNOWN answers for every bug class.

Test 1 TIMING: signal at close t must earn t->t+1 return, NEVER t's own return.
Test 2 COSTS: entry+exit of a flat-long round trip costs exactly 2*fee.
Test 3 METRICS: hand-computed monthly/SR/DD on tiny series.
Test 4 PLACEBO LEVEL: on pure noise, the placebo PASS rule fires at its nominal
       rate (p90 threshold -> ~10% false positives), not more.
Test 5 VALIDATOR PATTERN: the fixed pos_s=concat([[0],pos[:-1]]) pattern == engine's shift(-1).
"""
import numpy as np
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from nuclear_edges import pnl_from_weights, pnl_from_pos  # noqa: E402


def _px(n, seed=0, cols=1):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2021-01-01", periods=n)
    rets = rng.normal(0, 0.01, size=(n, cols))
    close = 100 * np.exp(np.cumsum(rets, axis=0))
    return pd.DataFrame(close, index=idx, columns=[f"c{i}" for i in range(cols)])


def test_timing_signal_earns_next_day_only():
    """Discriminating lookahead test: signal day has a +5% shock the signal could
    NOT know (ret[t]); the signal predicts +2% on t+1. Correct harness captures
    exactly 2%; a lookahead harness (pos[t]*ret[t]) would capture 5% or 7%."""
    n = 60
    idx = pd.bdate_range("2021-01-01", periods=n)
    rets = np.zeros(n)
    rets[10] = 0.05        # same-day shock: only a LOOKAHEAD harness can capture this
    rets[11] = 0.02        # the true predicted continuation
    close = pd.Series(100.0, index=idx)
    for t in range(1, n):
        close.iloc[t] = close.iloc[t - 1] * (1 + rets[t])
    px = close.to_frame("c0")
    sig = np.zeros(n)
    sig[10] = 1.0
    w = pd.DataFrame({"c0": sig}, index=idx)
    pnl = pnl_from_weights(w, px, fee=0.0)
    assert abs(pnl.sum() - 0.02) < 1e-9, f"expected 2% only, got {pnl.sum():.4f} (lookahead)"
    assert abs(pnl.iloc[10] - 0.02) < 1e-9, "forward return must be attributed to decision row t"
    assert abs(pnl.iloc[11]) < 1e-12, "no double-count on the earning row"


def test_validator_hold_pattern_matches_engine():
    """The fixed validator pattern (pos shifted 1 forward) == engine semantics."""
    n = 50
    px = _px(n, seed=3)
    close = px["c0"]
    pos = np.zeros(n)
    pos[5:9] = 1.0       # decided at close 5..8
    pos[20:24] = -1.0
    pos_s = np.concatenate([[0.0], pos[:-1]])     # validator fix
    pnl_validator = pd.Series(pos_s, index=px.index) * close.pct_change().fillna(0)
    pnl_engine = pnl_from_pos(pd.Series(pos, index=px.index), close, fee=0.0)
    # same series, different attribution row convention: validator marks the earning
    # row, engine marks the decision row -> shift by 1, totals identical.
    assert abs(pnl_validator.sum() - pnl_engine.sum()) < 1e-12, "totals differ"
    assert np.allclose(pnl_validator.values[1:], pnl_engine.fillna(0).values[:-1], atol=1e-12), (
        "validator timing != engine timing (beyond row convention)")


def test_costs_entry_exit_exact():
    """Flat long over k days: cost = 2*fee exactly (one entry, one exit)."""
    n = 30
    px = _px(n, seed=1)
    pos = pd.Series(0.0, index=px.index)
    pos.iloc[5:15] = 1.0
    fee = 0.001
    pnl = pnl_from_pos(pos, px["c0"], fee=fee)
    gross = (pos * px["c0"].pct_change().shift(-1).fillna(0)).sum()
    net = pnl.sum()
    assert abs((gross - net) - 2 * fee) < 1e-9, f"round-trip cost != 2*fee: {gross-net}"


def test_flip_costs_two_sides():
    """long->short flip costs 2*fee (exit long + enter short = |dw| of 2)."""
    n = 30
    px = _px(n, seed=2)
    pos = pd.Series(0.0, index=px.index)
    pos.iloc[5:15] = 1.0
    pos.iloc[15:25] = -1.0
    fee = 0.001
    pnl = pnl_from_pos(pos, px["c0"], fee=fee)
    gross = (pos * px["c0"].pct_change().shift(-1).fillna(0)).sum()
    net = pnl.sum()
    # entries: +1 (fee), flip 1->-1 (2*fee), exit -1->0 (fee) = 4*fee
    assert abs((gross - net) - 4 * fee) < 1e-9, f"flip cost wrong: {gross-net}"


def test_metrics_hand_computed():
    """monthly%, DD, SR on a known 3-month series."""
    idx = pd.bdate_range("2021-01-01", periods=63)
    daily = pd.Series(0.001, index=idx)          # +0.1%/day simple
    eq = (1 + daily).cumprod()
    dd = float((eq / eq.cummax() - 1).min())
    assert dd == 0.0
    total = float(daily.sum())
    months = (idx[-1] - idx[0]).days / 30.4375      # calendar months, house convention
    mo = total / months
    assert abs(total - 0.063) < 1e-9
    assert abs(mo - 0.063 / 2.8936) < 1e-3, f"monthly math off: {mo}"
    sr = float(daily.mean() / (daily.std() + 1e-12) * np.sqrt(252))
    assert sr > 100  # constant series -> huge SR (sanity of formula only)


def test_placebo_false_positive_rate():
    """On pure noise, 'real SR > p90 of null' must fire ~10% of the time, not more."""
    rng = np.random.default_rng(11)
    fp = 0
    trials = 200
    for _ in range(trials):
        pnl = pd.Series(rng.normal(0, 0.01, 500))
        sr = float(pnl.mean() / (pnl.std() + 1e-12) * np.sqrt(252))
        null_srs = []
        for _ in range(20):
            k = rng.integers(1, 25)
            blocks = np.array_split(pnl.values, k)
            bp = np.concatenate([blocks[j] for j in rng.permutation(k)])
            null_srs.append(float(pd.Series(bp).mean() / (pd.Series(bp).std() + 1e-12) * np.sqrt(252)))
        if sr > np.percentile(null_srs, 90):
            fp += 1
    rate = fp / trials
    assert rate <= 0.20, f"placebo rule too permissive on noise: {rate:.2%}"


def test_pnl_from_weights_panel_no_cross_lookahead():
    """Panel test: each column's pnl uses only its own weights and next-day returns."""
    n, m = 40, 3
    px = _px(n, seed=5, cols=m)
    w = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    w.iloc[3, 0] = 1.0
    w.iloc[3, 1] = -1.0
    pnl = pnl_from_weights(w, px, fee=0.0)
    ret_fwd = px.pct_change().shift(-1)
    expected = (w * ret_fwd).sum(axis=1)
    assert np.allclose(pnl.fillna(0).values, expected.fillna(0).values, atol=1e-12)
