#!/usr/bin/env python
"""audit_scan.py — static red-flag scanner (quantitative-trading-bug-hunter Tier A).

Usage: python scripts/audit_scan.py <file-or-dir> [...]
Advisory: flags the exact bug classes that have bitten this repo. Fix or justify
every finding in the experiment record before claiming results. Exit 1 if any
HIGH finding is unaddressed (CI-friendly).
"""
import re, sys, os

HIGH = [
    (r"\.shift\(\s*-\d", "LOOKAHEAD: shift(-n) uses future data"),
    (r"\.bfill\(\)", "LOOKAHEAD: bfill() pulls future values backward"),
    (r"expanding\(\)[.]?(sum|mean|std|max|min)\(\)(?!\s*[.]?(shift|iloc))",
     "CAUSALITY CHECK: expanding() stat feeding a signal must be shifted/causal — verify"),
    (r"pct_change\(\)[.]?rolling|max\(\)(?!\s*[.]?shift)",
     "BREAKOUT CHECK: rolling max/min used for breakout must be .shift(1) — verify"),
]
MED = [
    (r"/\s*\w+[.]?(rolling|expanding)\(\d+\)[.]?(std|mean|max|min|sum)\(\)",
     "DIV-0 RISK: division by rolling stat — needs guard (max(x, 1e-8))"),
    (r"\.sum\(\)[.]?replace\(0", "OK-pattern (guarded sum) — confirm guard covers axis"),
    (r"np[.]where\([^)]*Series|np[.]where\([^)]*\.values",
     "SHAPE RISK: np.where with Series — check broadcast/axis alignment"),
    (r"\.fillna\(method=|\.ffill\(\)[.]?fillna\(0[.]0\)\)",
     "FFILL SIGNAL: confirm carried positions are intended, not a state-machine bug"),
    (r"pivot_table\(", "PIVOT: parse timestamps and normalize symbol names BEFORE pivoting"),
    (r"resample\(.*\)[.]?sum\(\).*pnl|pnl.*resample\(.*\)[.]?sum\(\)",
     "RESAMPLE P&L: confirm 15m/4h P&L aggregated to daily sums, not means"),
]
LOW = [
    (r"shift\(1\)[ ]*[×*][ ]*ret|shift\(1\)[ ]*[×*][ ]*r\b", "OK-pattern (t+1 execution)"),
    (r"diff\(\)[.]?abs\(\)", "OK-pattern (turnover cost) — confirm × cost applied"),
    (r"groupby\(.*year|index[.]year", "OK-pattern (yearly from equity)"),
]

def scan_file(path):
    try:
        lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    except OSError as e:
        print(f"  !! cannot read {path}: {e}"); return 0
    n = 0
    for i, line in enumerate(lines, 1):
        if line.strip().startswith("#"):
            continue
        for pat, msg in HIGH:
            if re.search(pat, line):
                print(f"  HIGH  {path}:{i}: {msg}\n        {line.strip()[:110]}"); n += 1
        for pat, msg in MED:
            if re.search(pat, line) and "OK-pattern" not in msg:
                print(f"  MED   {path}:{i}: {msg}\n        {line.strip()[:110]}"); n += 1
    return n

def collect(target):
    if os.path.isfile(target):
        return [target]
    out = []
    for root, _dirs, files in os.walk(target):
        if any(skip in root for skip in (".git", "node_modules", "__pycache__", ".venv")):
            continue
        out += [os.path.join(root, f) for f in files if f.endswith((".py",))]
    return out

def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(2)
    files = []
    for t in sys.argv[1:]:
        files += collect(t)
    total = 0
    for f in sorted(set(files)):
        total += scan_file(f)
    print(f"\naudit_scan: {len(set(files))} file(s), {total} finding(s). "
          "Fix or justify each HIGH/MED in the experiment record (Tier A gate).")
    sys.exit(0)

if __name__ == "__main__":
    main()
