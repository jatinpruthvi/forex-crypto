"""AUDIT #5 Angle 3+4: DIFFERENTIAL PARITY & DETERMINISM.

Angle 3: two independent code paths must produce identical P&L on 100 random inputs.
Angle 4: same input twice -> byte-identical output (no hidden state, fixed seeds).
"""
import hashlib
import numpy as np
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from nuclear_edges import pnl_from_weights, pnl_from_pos, metrics_from_pnl, cs_weights  # noqa: E402


def test_parity_validator_pattern_vs_engine_100_random():
    """Validator hold-loop pattern == engine pnl_from_pos on 100 random position series."""
    rng = np.random.default_rng(101)
    for k in range(100):
        n = int(rng.integers(30, 400))
        idx = pd.bdate_range("2021-01-01", periods=n)
        close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=idx)
        pos = np.round(rng.uniform(-1, 1, n))
        pos_s = np.concatenate([[0.0], pos[:-1]])
        ret = close.pct_change().fillna(0)
        pnl_validator = pd.Series(pos_s * ret.values, index=idx)
        pnl_engine = pnl_from_pos(pd.Series(pos, index=idx), close, fee=0.0)
        assert abs(pnl_validator.sum() - pnl_engine.sum()) < 1e-9, f"parity break at trial {k}"
        assert np.allclose(pnl_validator.values[1:], pnl_engine.fillna(0).values[:-1], atol=1e-12)


def test_parity_manual_vs_pnl_from_weights_100_random():
    """Manual forward-return formula == pnl_from_weights on 100 random weight matrices."""
    rng = np.random.default_rng(202)
    for k in range(100):
        n, m = int(rng.integers(30, 300)), int(rng.integers(1, 6))
        idx = pd.bdate_range("2021-01-01", periods=n)
        px = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.01, (n, m)), axis=0)),
                          index=idx, columns=[f"c{j}" for j in range(m)])
        w = pd.DataFrame(rng.uniform(-1, 1, (n, m)), index=idx, columns=px.columns)
        fee = 0.001
        manual = (w * px.pct_change().shift(-1)).sum(axis=1) - w.diff().abs().sum(axis=1) * fee
        engine = pnl_from_weights(w, px, fee=fee)
        assert np.allclose(manual.fillna(0).values, engine.fillna(0).values, atol=1e-12), f"parity break at {k}"


def test_parity_metrics_vs_manual_compound():
    """metrics_from_pnl monthly == manual geometric compounding on 50 random series."""
    rng = np.random.default_rng(303)
    for k in range(50):
        n = int(rng.integers(150, 500))
        idx = pd.bdate_range("2021-01-01", periods=n)
        r = pd.Series(rng.normal(0.0005, 0.01, n), index=idx)
        m = metrics_from_pnl(r)
        eq = (1 + r).cumprod()
        months = max((idx[-1] - idx[0]).days / 30.44, 1)
        manual = (eq.iloc[-1] ** (1 / months) - 1) * 100
        assert abs(m["monthly"] - manual) < 0.01, f"metrics parity break at {k}"


def test_cs_weights_vs_manual_ranking():
    """cs_weights output == hand-built long-top-K/short-bottom-K on random scores."""
    rng = np.random.default_rng(404)
    for k in range(50):
        n, m = 120, 8
        idx = pd.bdate_range("2021-01-01", periods=n)
        px = pd.DataFrame(100.0, index=idx, columns=[f"c{j}" for j in range(m)])
        score = pd.DataFrame(rng.normal(0, 1, (n, m)), index=idx, columns=px.columns)
        w = cs_weights(score, 3, px, rebal=5)
        # spot-check one rebalance row
        i = 49
        row = score.iloc[i]
        top3 = set(row.nlargest(3).index)
        bot3 = set(row.nsmallest(3).index)
        for c in px.columns:
            got = float(w.iloc[i][c])
            if c in top3:
                assert abs(got - 1 / 3) < 1e-9, f"top-K mismatch at {k}/{c}"
            elif c in bot3:
                assert abs(got + 1 / 3) < 1e-9, f"bot-K mismatch at {k}/{c}"


def test_determinism_metrics_double_run():
    """Same series -> identical metrics dict on repeated runs (no hidden state)."""
    idx = pd.bdate_range("2021-01-01", periods=400)
    r = pd.Series(np.sin(np.arange(400) / 7) * 0.01, index=idx)
    assert metrics_from_pnl(r) == metrics_from_pnl(r)


def test_determinism_placebo_fixed_seeds():
    """Placebo with fixed seeds -> identical percentile on double run."""
    rng_master = np.random.default_rng(7)
    idx = pd.bdate_range("2021-01-01", periods=500)
    ret = pd.Series(rng_master.normal(0, 0.01, 500), index=idx)
    pos = pd.Series(0.0, index=idx)
    pos[rng_master.random(500) < 0.2] = 1.0

    def placebo_pct():
        rng = np.random.default_rng(7)
        srs = []
        for _ in range(30):
            blocks = np.array_split(np.arange(500), 25)
            perm = np.concatenate([blocks[j] for j in rng.permutation(25)])
            pq = pos.iloc[perm].copy(); pq.index = pos.index
            bp = pq.shift(1).fillna(0) * ret
            srs.append(metrics_from_pnl(bp)["sharpe"])
        real = metrics_from_pnl(pos.shift(1).fillna(0) * ret)["sharpe"]
        return float((np.array(srs) < real).mean() * 100)

    assert placebo_pct() == placebo_pct()


def test_determinism_cs_weights_hash():
    """cs_weights output frame hashes identically across runs."""
    idx = pd.bdate_range("2021-01-01", periods=100)
    px = pd.DataFrame(100.0, index=idx, columns=list("abcd"))
    score = pd.DataFrame(np.outer(np.arange(100), np.arange(4)) * 0.01, index=idx, columns=list("abcd"))
    def h():
        w = cs_weights(score, 1, px)
        return hashlib.sha256(np.ascontiguousarray(w.fillna(0).values)).hexdigest()
    assert h() == h()


def test_row0_semantics_consistent_across_engine():
    """REGRESSION (bug #5, audit#5): pnl_from_pos and pnl_from_weights must agree at row 0:
    keep the row-0 forward return, skip the row-0 entry cost. (Previously pnl_from_pos
    silently zeroed all row-0 P&L when pos[0] != 0.)"""
    idx = pd.bdate_range("2021-01-01", periods=20)
    close = pd.Series(np.linspace(100, 120, 20), index=idx)
    px = close.to_frame("c")
    pos = pd.Series(0.0, index=idx)
    pos.iloc[0] = 1.0                       # open at row 0
    w = pd.DataFrame({"c": pos.values}, index=idx)
    pnl_pos = pnl_from_pos(pos, close, fee=0.001)
    pnl_w = pnl_from_weights(w, px, fee=0.001)
    assert abs(pnl_pos.iloc[0] - pnl_w.iloc[0]) < 1e-12, "row-0 return handling differs"
    assert abs(pnl_pos.iloc[0] - close.pct_change().shift(-1).iloc[0]) < 1e-12, "row-0 return must be kept"
    assert abs(pnl_pos.sum() - pnl_w.sum()) < 1e-12, "totals must agree"
