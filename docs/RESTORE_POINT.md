# RESTORE POINT — 2026-10-30 (post EXP-044, commit `a1efb81`+)

## If the workspace was wiped, recover in this order:
1. **Code/history**: `git fetch origin && git reset --hard origin/arena/b657ea09-forex-crypto`
   (all experiments are pushed; branch = `arena/b657ea09-forex-crypto`, PR open).
2. **Data**: `python scripts/restore_data.py` (needs `gh` auth). Rebuilds:
   - `data/timeframes/1d_panel_5y/` — 15 majors daily 2021-01→2026-07 (olaxbt)
   - `data/intraday/` — BTC/ETH/XRP 5m+15m, BTC 1h+4h 2019-09→2025-06 (quantinaut)
   - `data/derivatives/funding_all.csv` — real 8h perp funding 2021→2026 (olaxbt)
   - `data/macro/defillama_liquidity_daily.csv`
   (CSVs are gitignored by repo convention — this script is the source of truth.)
3. **Python env**: `python3 -m venv /tmp/venv && /tmp/venv/bin/pip install -r requirements.txt`
   + `pip install "plotly<6.0.0" vectorbt scipy pyarrow nautilus_trader`.
4. **Results of record** (tracked in git): `reports/strategy_leaderboard.json`,
   `reports/roi_progress_ledger.json` (53 experiments), `docs/STRATEGY_REDESIGN.md` §5–§12.14.

## Current best validated book (all numbers post commission+spread 10bp/side):
**Book R2**: 75%×(0.5·ABS_GROT + 0.5·FVG_SHORT) + 25%·cs_mom14_K5_vg (14d cross-sectional
momentum, K=5, BTC>MA100 gate), with a 25% sleeve of fund_ls7_K5 (funding carry:
short highest-funding / long lowest-funding coins, 7d window, K=5).
- Unlevered: +2.44%/mo, SR 1.52, DD 18.2, worst-year −0.40
- ×1.5: +3.55%/mo, DD 26.3
- **×2: +4.59%/mo, DD 33.7, worst-year −1.00** (21:+13.5 22:+0.1 23:−1.0 24:+6.8 25:+2.0 26:−0.8)
- Placebo-certified: cs_mom14 blend (93rd pct), funding add-on (1.66 vs null p90 1.62).

## Hard-won negative knowledge (do not re-test):
- 5m/15m scalping & intraday: dead at ANY cost (0/280 nodes even at 3bp maker).
- TSMOM, FVG_LONG: 2021-miracle landmines — never in combos.
- State-driven LOYO switching: fails selection null; ungating MA-gate hurts; brain refresh
  hurts on 5y panel; leverage ceiling of a book ≈ μ²/2σ²-fit (~+4.3%/mo for old book).
- Options premium: untestable (no reachable IV data).
- Small-cap universe +6.6%/mo was 2021 mania (ex-2021: +1.11).

## Experiment index: EXP-022..044 in `reports/roi_progress_ledger.json`; leaderboard keys
exp022..exp044 in `reports/strategy_leaderboard.json`.
