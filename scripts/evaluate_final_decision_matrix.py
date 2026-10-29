import pandas as pd
import numpy as np

# Compare 3 candidates:
# Candidate 1: Pure 12-Bar Donchian Breakout (Modern High-Beta Momentum)
# Candidate 2: Adaptive Regime Hybrid (ADX + Donchian + Bollinger Pin Bar)
# Candidate 3: Core-Satellite Allocation (75% Donchian Breakout / 25% Regime Mean-Reversion)

print("=" * 148)
print("!!! CORRECTION (EXP-020): the figures below were produced under the OLD PHANTOM-PYRAMID")
print("!!! ACCOUNTING and are SUPERSEDED. Under corrected accounting the strategy has NO")
print("!!! positive edge (see reports/roi_progress_ledger.json EXP-020). Do NOT use these")
print("!!! numbers for decisions; this table is retained only as a historical artifact.")
print("=" * 148)
print("=== FINAL DECISION MATRIX: WHICH STRATEGY SHOULD WE PICK? (SUPERSEDED - SEE EXP-020) ===")
print("Strategy Model                     | Active Market Monthly ROI (2023) | Bear Market Annual ROI (2022) | Max Historical Drawdown | All-Weather Consistency")
print("----------------------------------------------------------------------------------------------------------------------------------------------------")
print("1. Pure Donchian 12-Bar Breakout    |       +23.0% to +24.8% / month   |            +19.08% / year     |          8.59%          | High in bull/trending cycles; lower frequency in deep chop")
print("2. Pure Mean-Reversion (RSI/BB)     |       -0.48% / month (Negative)  |            -0.81% / year      |          8.92%          | Fails in strong trends; generates false bottom signals")
print("3. Adaptive Regime Hybrid (ADX-Gate)|       +4.93% / month             |            +62.39% / year     |          8.05%          | Most consistent across 7 years; trades chop & trend")
print("4. Focused Alpha (12-Bar BTC + SOL) |       +18.5% to +24.0% / month   |            +25.40% / year     |          8.15%          | Optimal balance of high monthly compounding and resilience")
print("=" * 148)
