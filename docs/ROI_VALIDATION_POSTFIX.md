# Post-Bugfix ROI Validation — Real Historical Data, Strictly Out-of-Sample

> ## ⚠️ CORRECTION (2026-10-29) — SUPERSEDED BY EXP-020
>
> The walk-forward harness re-run after fixing the **pyramid-accounting bug** (adds
> booked at original entry, no add fee → phantom +1.8/+3 ATR per add unit) reports:
> **crypto22 OOS −8.25%/mo** (worst DD 26.1%, BREACH), **crypto24 +1.5%/mo** (0 trades),
> **forex OOS −3.14%/mo** (worst DD 56.2%, BREACH). The +25.8%/+6.4%/mo numbers below
> are pyramid-accounting-optimistic artifacts. Honest verdict: **no positive edge at
> the audited fill model** — strategy redesign required. See `EXP-020` in
> `reports/roi_progress_ledger.json` and the correction banner in
> `docs/CRYPTO_ROI_DEEP_VALIDATION.md`.

**Date:** 2026-10-29 · **Commit basis:** `fda3325` + walk-forward harness ·
**Ledger entries:** `EXP-018A-WALKFORWARD-CRYPTO22-OOS`, `EXP-018B-WALKFORWARD-CRYPTO24-OOS`,
`EXP-018C-WALKFORWARD-FOREX-OOS` · **Reproduce:** `PYTHONPATH=. python scripts/validate_roi_postfix.py [--record]`

## Why this validation exists

Historical ROI claims in this repo were previously inflated by two audit findings:

1. **In-sample contamination** (BUG_AUDIT_TOP50 #1–5): ML scripts fitted on ~65% of the
   series and then traded the *full* series — most reported trades were in-sample.
2. **Optimistic fill model** (#6–13): stops filled at maker fees with no slippage and
   TP-before-SL ordering on ambiguous bars.

This validation uses only the **corrected** engine and **held-out** data. Nothing reported
below as ROI contains a single in-sample trade.

## Method (no assumptions)

| Element | Choice |
|---|---|
| Data | 3 real historical datasets shipped in `data/` (see provenance below). No synthetic candles, no generated ticks. |
| Engine | `execute_shared_pool_sim` from `scripts/run_dual_slot_shared_pool_benchmark.py` — the audited corrected fill model (bar-start stop snapshot, stop fills **first** on ambiguous bars with taker fee + 0.05% slippage, net-trade win counting). Single source of truth; **pinned against EXP-016 to the cent** before use ($22,996.87 / +77.39% / 20.07% / 138 trades reproduced exactly). |
| Walk-forward | Expanding-window folds. Config grid `{risk 0.5–1.5%} × {1,2 slots}` scored on **TRAIN only**. |
| Selection rule (fixed in code, not by hand) | Highest train monthly ROI among configs with **train max-DD ≤ 15%** (crypto-futures prop limit). Tie-break lower DD. If no config passes, min-DD config. |
| Reporting | The selected config is run **once** on the untouched TEST window. Only TEST numbers are called ROI. |
| Determinism | Fixed grid order, no RNG. Full run ≈ 85 s. |

### Data provenance

| id | pairs | window | source |
|---|---|---|---|
| crypto22 | BTC, ETH, BNB, XRP, ADA, DOGE, LTC, LINK (8) | 2022-10-30 → 2023-04-15 (1000 synced H4 bars, 5.47 mo) | `data/timeframes/bench_panel/` (StephanAkkerman/crypto-forecasting-benchmark) |
| crypto24 | BTC, SOL, BNB, LINK (4) | 2024-01-01 → 2024-03-24 (500 synced H4 bars, 2.73 mo) | `data/timeframes/*.csv` (repo demo-window dataset) |
| forex | GBPJPY, XAUUSD, EURJPY, GBPUSD, AUDUSD, USDJPY (6) | 2012-11 → 2022-03 (**14,268 synced H4 bars, 111.2 months**) | `data/forex/` (ejtraderLabs/historical-data; EURJPY source is H1, aggregated to H4 OHLC) |

Crypto runs include the MEXC lot/min-notional viability gate (live-parity sizing);
forex runs use pure risk-budget sizing (OTC — no exchange lot constraints).

## Results — strictly out-of-sample

### Summary (the numbers to budget with)

| dataset | unseen months | **OOS ROI / month** | worst fold DD | OOS trades | DD ≤ 15%? |
|---|---|---|---|---|---|
| crypto22 (2022-23, bear-rally) | 2.73 | **+25.80%** | 13.79% | 75 | ✅ PASS |
| crypto24 (2024, bull, thin signals) | 1.36 | **+5.12%** | 1.84% | 0 closed (1 open, MTM) | ✅ PASS |
| forex (2012–2022, 4 folds) | 73.66 | **+6.37%** | 13.26% | 732 | ✅ PASS (all 4 folds) |
| **transfer**: crypto22-selected → full crypto24 | 2.73 | **+2.83%** | 4.15% | 3 (2 open at end) | ✅ PASS |

### crypto22 — fold 1 (train 2.73 mo → test 2.73 mo)

Train grid (used for selection only — **not** ROI claims):

| config | train %/mo | train DD | trades | selected |
|---|---|---|---|---|
| risk 0.50% / 1 slot | +9.60% | 6.27% | 23 | |
| risk 0.50% / 2 slots | +28.76% | 9.53% | 57 | |
| risk 0.75% / 1 slot | +14.71% | 8.63% | 23 | |
| risk 0.75% / 2 slots | +46.98% | 12.35% | 57 | |
| **risk 1.00% / 2 slots** | **+65.60%** | **14.11%** | **57** | ✅ (highest ROI with DD ≤ 15%) |
| risk 1.25% / 2 slots | +84.71% | 17.16% | 57 | ❌ DD breach |
| risk 1.50% / 2 slots | +104.65% | 20.07% | 57 | ❌ DD breach |

**OOS (2023-01-22 → 2023-04-15, unseen):** +25.80%/mo · DD 13.79% · 75 trades ·
WR 34.7% · PF 1.79 · $1,000 → $1,872.23 · **DD check PASS**

### crypto24 — fold 1 + cross-dataset transfer

Train on 2024-01-01 → 2024-02-11 produced only **1 trade across the whole grid**
(these 4 pairs rarely trigger the signal in this window — an honest property of the
data, not a filter). Selection by rule: risk 1.5% / 1 slot.

**OOS (2024-02-11 → 2024-03-24, unseen):** +5.12%/mo · DD 1.84% · 0 closed trades
(1 position still open at window end, marked to market) · **DD check PASS**

**Transfer test** (zero window overlap — crypto22-selected risk 1.0%/2 slots applied to
the full 2024 window): +2.83%/mo · DD 4.15% · 3 trades (2 open at end) · PF 0.82 ·
**DD check PASS**. Positive but weak edge in this regime; treat as corroboration, not proof.

### forex — 4 expanding folds (2012–2022)

Every fold's rule-selected config was **risk 0.50% / 1 slot** — the only grid point whose
train DD stayed under 15% (14.27%). The prop-firm constraint is the binding factor, as
intended. Train grids and per-fold OOS:

| fold | train → test | OOS %/mo | OOS DD | trades | WR | PF |
|---|---|---|---|---|---|---|
| 1 | 2012-11→2016-01 ⇒ 2016-01→2017-08 | **+7.74%** | 11.92% | 187 | 40.6% | 1.87 |
| 2 | 2012-11→2017-08 ⇒ 2017-08→2019-02 | **+5.91%** | 10.60% | 179 | 40.2% | 1.64 |
| 3 | 2012-11→2019-02 ⇒ 2019-02→2020-09 | **+8.07%** | 11.50% | 180 | 42.2% | 2.14 |
| 4 | 2012-11→2020-09 ⇒ 2020-09→2022-03 | **+3.66%** | 13.26% | 186 | 30.6% | 1.39 |

**Aggregate (73.66 unseen months, 732 trades): +6.37%/mo compounded · worst DD 13.26% ·
all four folds individually PASS the 15% DD limit.** Fold 4 (2020-09→2022-03, choppy
post-COVID FX) is the weakest at +3.66%/mo — the honest floor of expectation.

## Honest interpretation

1. **The defensible long-run rate is ~5–8%/month, not 25–77%.** The 9.3-year FX
   walk-forward — the largest sample with 73+ truly unseen months — compounds at
   **+6.4%/mo OOS** with every fold prop-compliant. The crypto22 **+25.8%/mo** draw is
   a single 2.73-month held-out window (75 trades): strong evidence the goal is
   *achievable in good regimes*, but one draw is not a long-run rate.
2. **Full-window backtests overstate.** EXP-016's +77%/mo on the full 5.47-month panel
   is a compounding + fill-model artifact (verified reproducible, and the pre-fix model
   reproduces EXP-013's $3,391 exactly — the gap is model sensitivity, not data error).
   Use the OOS rows above for budgeting; use full-window runs only for configuration
   comparison.
3. **Prop-firm constraint binds and is respected.** The selection rule refuses >15% DD
   configs (crypto22 would have picked risk 1.25%/2 slots (+84.7%/mo train) if not).
   All reported OOS runs sit under 15% DD. For prop-account reality (max daily 4%,
   total 8–10%) operate at the **low end of the grid: 0.5–0.75% risk, 1–2 slots** —
   forex evidence says that is where the constraint-feasible edge lives.
4. **Capacity caveat.** Train rows at high risk compound into billions — these backtests
   carry no capital-capacity or market-impact model. Compare runs by **monthly rate and
   DD**, never by terminal dollars. Live expectancy must also absorb spread, funding,
   and execution latency beyond the modeled taker fee + 0.05% stop slippage.
5. **2024 bull-window signals are thin** (3 trades in 2.73 months). The strategy is a
   breakout/reversion hybrid that sits quiet in calm regimes; expect uneven trade flow.
6. **Prior "20–25%/mo" ML-script claims were not revalidated here** — they came from the
   contaminated templates (#1–5) and their honest OOS remains a separate task
   (the scripts now simulate post-split only).

## Conclusion

After the Tier A–D bug fixes, validated on real historical candles with strict
walk-forward discipline:

- **Expected blended OOS ROI: ~5–8%/month** at prop-compliant risk (0.5% risk, 1 slot,
  DD-throttled), with regime upside to ~25%/month as seen in the 2023 crypto test window.
- **Drawdown:** every unseen fold ≤ 13.8%, inside the 15% crypto-futures limit at the
  rule-selected configs; tighter prop limits (8–10%) require the 0.5%/1-slot corner.
- The ~25%/month target is reachable in favorable regimes but is **not** a safe planning
  figure; planning at 6–8%/month with 25% as upside variance matches the evidence.

> **Superseded for the crypto-only scope** (user decision, 2026-10-29): the 5–8%/mo
> figure above is forex-derived. The deep crypto-only follow-up
> (`docs/CRYPTO_ROI_DEEP_VALIDATION.md`, EXP-019A/B) shows the 2023 crypto OOS folds
> ran +11.7%…+81.2%/mo (the +25.8% blend is the conservative end, robust to 6×
> fill-cost stress, LOPO-stable), and characterizes the real regime risk as
> **dormant months with no signal** (2024 H1: 1 closed trade in 3.55 unseen months).
> Crypto-only planning: ~25%/mo active-regime expectation, 10–25%/mo blended,
> 0.75%/2-slots or 1.0%/1-slot for DD margin.

_Re-run any time: `PYTHONPATH=. python scripts/validate_roi_postfix.py --record` appends
fresh EXP-018 entries; the harness is deterministic and reproduces every number above._
