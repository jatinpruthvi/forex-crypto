"""AUDIT #5 Angle 1: MUTATION TESTING - do our tests actually catch bugs?

For each of the 6 bug classes found (or plausible), we inject the mutant into a
scratch copy of the code and run the corresponding test. A test PASSES this audit
only if the mutant makes it FAIL (exit != 0). A mutant that survives = a test gap.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = Path("/tmp/mutant_scratch")

MUTANTS = [
    {
        "id": "M1-lookahead",
        "file": "scripts/nuclear_edges.py",
        "old": "ret_fwd = px.pct_change().shift(-1)",
        "new": "ret_fwd = px.pct_change()",           # entry-day lookahead (bug class #1)
        "tests": ["tests/test_validation_harness.py::test_timing_signal_earns_next_day_only",
                  "tests/test_validation_harness.py::test_validator_hold_pattern_matches_engine"],
    },
    {
        "id": "M2-units-annual",
        "file": "scripts/nuclear_edges.py",
        "old": '"min_year": round(min(ym.values()), 2) if ym else None,',
        "new": '"min_year": round(min(ym.values()) * 12, 2) if ym else None,',  # %/yr vs %/mo (bug #2)
        "tests": ["tests/test_validation_harness.py::test_house_metric_units",
                  "tests/test_validation_harness.py::test_gate_threshold_units_match"],
    },
    {
        "id": "M3-costs-halved",
        "file": "scripts/nuclear_edges.py",
        "old": "return (pos * ret_fwd - pos.diff().abs() * fee).fillna(0.0)",
        "new": "return (pos * ret_fwd - pos.diff().abs() * fee * 0.5).fillna(0.0)",
        "tests": ["tests/test_validation_harness.py::test_costs_entry_exit_exact",
                  "tests/test_validation_harness.py::test_flip_costs_two_sides"],
    },
    {
        "id": "M4-nwog-stale",
        "file": "tests/test_validation_harness.py",
        "old": "prev = pd.Series(open_.index.to_period(\"W-SUN\"), index=open_.index).map(wk_first.shift(1))",
        "new": "prev = pd.Series(open_.index.to_period(\"W-SUN\"), index=open_.index).map(wk_first.shift(2))",  # bug #4 family
        "tests": ["tests/test_validation_harness.py::test_nwog_prev_week_open_reference"],
    },
    {
        "id": "M5-placebo-degenerate",
        "file": "tests/test_validation_harness.py",
        "old": "pq = pos.iloc[perm].copy(); pq.index = pos.index",
        "new": "pq = pos.copy()",                       # placebo that permutes nothing = degenerate (bug #3 family)
        "tests": ["tests/test_validation_harness.py::test_placebo_design_not_degenerate"],
    },
    {
        "id": "M6-metrics-order-free-null",
        "file": "tests/test_validation_harness.py",
        "old": "bp_good = pq.shift(1).fillna(0) * ret                          # valid",
        "new": "bp_good = pd.Series(pnl.values[perm], index=pnl.index)        # mutated: same degenerate as bad",
        "tests": ["tests/test_validation_harness.py::test_placebo_design_not_degenerate"],
    },
]


def run_pytest(workdir, tests):
    r = subprocess.run([sys.executable, "-m", "pytest", *tests, "-q", "--no-header", "-x"],
                       cwd=workdir, capture_output=True, text=True, timeout=600)
    return r.returncode, (r.stdout or "")[-300:]


def main():
    results = {}
    for mu in MUTANTS:
        if SCRATCH.exists():
            shutil.rmtree(SCRATCH)
        SCRATCH.mkdir(parents=True)
        shutil.copytree(ROOT / "scripts", SCRATCH / "scripts",
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "tests", SCRATCH / "tests",
                        ignore=shutil.ignore_patterns("__pycache__"))
        (SCRATCH / "data").mkdir()
        target = SCRATCH / mu["file"]
        s = target.read_text()
        assert mu["old"] in s, f"pattern not found for {mu['id']}"
        target.write_text(s.replace(mu["old"], mu["new"], 1))
        # baseline: unmutated must PASS
        base = SCRATCH / mu["file"]
        s2 = base.read_text().replace(mu["new"], mu["old"], 1)
        base.write_text(s2)
        code0, _ = run_pytest(SCRATCH, mu["tests"])
        base.write_text(s2.replace(mu["old"], mu["new"], 1))
        code1, tail = run_pytest(SCRATCH, mu["tests"])
        caught = (code0 == 0 and code1 != 0)
        results[mu["id"]] = {"baseline_pass": code0 == 0, "mutant_fails_tests": code1 != 0,
                             "caught": bool(caught), "tests": mu["tests"]}
        print(f"  {mu['id']:26s} baseline_pass={code0 == 0!s:5s} mutant_caught={caught!s:5s} {tail.splitlines()[-1] if tail else ''}")
    all_caught = all(v["caught"] for v in results.values())
    print(f"\nMUTATION AUDIT: {'ALL MUTANTS CAUGHT' if all_caught else 'GAPS FOUND'} "
          f"({sum(v['caught'] for v in results.values())}/{len(results)})")
    Path("reports").mkdir(exist_ok=True)
    json.dump({"date": "2026-10-31", "angle": "1-mutation-testing", "mutants": results,
               "all_caught": bool(all_caught)},
              open("reports/mutation_audit.json", "w"), indent=1)


if __name__ == "__main__":
    main()
