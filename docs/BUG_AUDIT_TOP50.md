# Top 50 High-Priority Bug Audit — repo-wide

Date: 2026-10-29 · Branch: `arena/b657ea09-forex-crypto` · Method: compile-all, pyflakes (161 files),
pattern sweeps (lookahead / fee-model / fill-ordering / division / deprecation classes), and
line-by-line reads of every module that produces reported numbers (engines, benchmarks, ledger,
demo server, ML stack). Suite after fixes: **172/172 green**.

Severity ranking criteria (in order): (1) makes reported results inauthentic/overstated — the
"real testing, not just to show positive" requirement; (2) risks real money in the live path;
(3) crashes / silent wrong answers; (4) reproducibility and future breakage.

Legend: **[FIXED]** — patched in this audit commit · **[PATCH]** — fix recommended immediately,
documented here because it changes backtest output and the experiment ledger must be re-run
afterwards · **[DOC]** — needs a methodology decision before changing code.

---

## Tier A — Result authenticity (reported numbers wrong or overstated)

| # | Sev | Location | Bug | Status |
|---|-----|----------|-----|--------|
| 1 | 🔴 | `scripts/evaluate_leverage_roi_4h.py:56-62, 185-212` | **In-sample contamination of reported ROI.** `clf.fit(X[:split_idx])` then `predict_proba(X)` over the *full* series and `simulate_leverage` trades `range(1, n)` — the "20-25% monthly ROI" sweep table includes performance of a model scoring the very bars it was trained on. The train window is ~65% of the run, so most reported trades are in-sample. | **[FIXED]** simulate post-split OOS window only (`months_total`) + repo-root model path |
| 2 | 🔴 | `scripts/run_multi_timeframe_50_experiments.py:228-245` | Same contamination pattern (full-series `predict_proba`, full-range sim) in the 50-experiment matrix. | **[FIXED]** same OOS-window fix |
| 3 | 🔴 | `scripts/evaluate_portfolio_ml_roi.py:53+` | Same template (`shift(-12)` label → train 65% → score all). | **[FIXED]** same OOS-window fix |
| 4 | 🔴 | `scripts/evaluate_pure_btc_ml_calibration.py:48+` | Same template. | **[FIXED]** same OOS-window fix |
| 5 | 🔴 | `scripts/run_50_ml_experiments.py:254+` | Same template. | **[FIXED]** same OOS-window fix |
| 6 | 🔴 | `core/analysis/fast_backtester.py:137-146 (long), 166-171 (short)` | **Same-bar TP-before-SL fill ordering.** A bar that touches both TP and SL always books the *profit* (`if high >= tp ... elif low <= sl`). Optimistic bias on every ambiguous bar. | **[FIXED]** bar-start stop snapshot; stop fills FIRST on ambiguous bars |
| 7 | 🔴 | `services/demo_runner/dual_slot_paper_engine.py` `on_asset_candle` | Same optimistic ordering: TP1/TP2 partials booked from `high` before the `low <= stop_loss` check. Also inconsistent with `evaluate_leverage_roi_4h.py` which uses SL-first — engines are not comparable. | **[FIXED]** same SL-first fill model (engine parity) |
| 8 | 🔴 | `core/analysis/quantum_hybrid_engine.py:146-183` | Same optimistic TP-first ordering + partial TP credited on the very bar that stops the position out. | **[FIXED]** same SL-first fill model; no partial-TP on stopping bars |
| 9 | 🔴 | `services/demo_runner/multi_asset_engine.py:172-205` | Same optimistic TP-first ordering (TP1/TP2 from `high` before `low <= sl_price`). | **[FIXED]** same SL-first fill model |
| 10 | 🔴 | `core/analysis/fast_backtester.py:128-134`, `quantum_hybrid_engine.py:146-157`, `multi_asset_engine.py:173-195` | **Partial-TP on stopping bars**: the 2×ATR partial is credited whenever `high` reached it, even if the same bar traded through the stop — books profit on losing bars. | **[FIXED]** no TP/pyramid bookkeeping on stopping bars |
| 11 | 🔴 | `dual_slot_paper_engine._close_position`, `run_dual_slot_shared_pool_benchmark.py:162,217`, `run_5year_intrabar_tick_benchmark.py:156`, `quantum_hybrid_engine.py:180,217`, `out_of_box_engine.py:210,240`, `real_paper_engine.py:296`, `quantum_paper_engine.py:245`, `multi_asset_engine._close_position` | **No taker fee exists anywhere**: stop-loss exits (triggered market orders) are charged the *maker* rate — ~3× too low on Hyperliquid (0.015% vs 0.045%) and ~3.7× too low on MEXC taker. Every engine understates losses. | **[FIXED]** `taker_fee_pct = max(3×maker, 0.045%)` on trigger/stop closes across all 7 engines + 2 benchmarks |
| 12 | 🔴 | `services/demo_runner/demo_server.py:187-226` | Demo accounts with `maker_fee=0.0000` ("zero-fee maker routing") apply **zero fee to taker stop fills too**, overstating live-realistic PnL in the user-facing demo. | **[FIXED]** taker-fee floor applies even to zero-fee maker accounts (stops still pay taker) |

## Tier B — Sizing, risk and metric correctness

| # | Sev | Location | Bug | Status |
|---|-----|----------|-----|--------|
| 13 | 🟠 | `run_dual_slot_shared_pool_benchmark.py:161`, `multi_asset_engine.py:204,255` | Stop exits filled at the *exact* stop price — no slippage (unlike `fast_backtester`, which models it). Optimistic on every loss. | **[FIXED]** `stop_slippage = 0.05%` on stop fills in engines + benchmarks |
| 14 | 🟠 | `core/analysis/out_of_box_engine.py:275,284,296,305` | `risk / max(stop_dist, 1e-4)` size explosion: ATR→0 inflates size ~10⁴× (the bug class found live in round 2). | **[FIXED]** floor = 0.05% of entry |
| 15 | 🟠 | `core/analysis/quantum_hybrid_engine.py:253,262,274,283` | Same size-explosion class. | **[FIXED]** |
| 16 | 🟠 | `scripts/run_dual_slot_shared_pool_benchmark.py:136` (4 sites) | Same class in the champion benchmark (pyramid adds). | **[FIXED]** |
| 17 | 🟠 | `scripts/run_5year_intrabar_tick_benchmark.py:137,144` (4 sites) | Same class in the EXP-014 benchmark. | **[FIXED]** |
| 18 | 🟠 | `scripts/evaluate_leverage_roi_4h.py:196` | `pf = 0.0` when a run has zero losses — a *perfect* run reports PF 0.0 (catastrophic look). | **[FIXED]** (10.0 cap, matches fast_backtester) |
| 19 | 🟠 | `scripts/run_multi_timeframe_50_experiments.py:214` | Same PF bug. | **[FIXED]** |
| 20 | 🟠 | `core/analysis/quantum_hybrid_engine.py:153,171` | **Win rate counted at TP1 partial**, not at trade close — a trade that takes TP1 then stops out net-negative is recorded as a win. Inflates win-rate vs. net-trade reality. | **[FIXED]** win counted at close on net trade PnL |
| 21 | 🟠 | `run_dual_slot_shared_pool_benchmark.py:136`, `run_5year_intrabar_tick_benchmark.py:137,144` | Pyramid adds bypass lot-step/min-notional viability (no `SizingViabilityGate`) → benchmark trades sizes that live venues reject; trade counts and compounding overstated vs. the live path. | **[FIXED]** benchmark entries/pyramids routed through `SizingViabilityGate` |
| 22 | 🟠 | `core/risk/institutional_guards.py:33` | `max_daily_loss_pct` (the "4% hard limit") was **never enforced** — only `lockout_trigger_pct` was checked; with `lockout > max_daily` config the hard limit is silently ignored. | **[FIXED]** (both conditions checked; regression test added) |
| 23 | 🟠 | `core/analysis/monte_carlo.py:35` | Unseeded global RNG → risk-of-ruin numbers not reproducible (breaks restore-point discipline), and docstring claimed "permutations" while implementing bootstrap resampling. | **[FIXED]** (`seed` param + `default_rng`, docstring corrected) |
| 24 | 🟡 | `core/analysis/monte_carlo.py:47` | "Probability of ruin" is defined as breaching **−50% equity** — not the prop-firm ruin condition (4% daily / 8-10% total DD). Metric name oversells its meaning. | **[FIXED]** `ruin_threshold_pct` parameter (result key names preserved) |
| 25 | 🟡 | `core/signals/cross_asset.py:25-27` | Missing pairwise correlations are `nan_to_num(..., 0.0)` → an unknown/insufficient-history correlation is treated as **zero**, so the correlation haircut is under-applied and new positions are oversized. | **[FIXED]** conservative `nan_to_num(..., nan=1.0)` default |
| 26 | 🟡 | `core/risk/institutional_guards.py:60` | `zip(position_notionals, asset_volatilities)` silently truncates mismatched lists → VaR under-computed. | **[FIXED]** length-mismatch raises `ValueError` |

## Tier C — Dead/wrong features and silent failures

| # | Sev | Location | Bug | Status |
|---|-----|----------|-----|--------|
| 27 | 🟠 | `services/demo_runner/demo_server.py:372-375` | **BTC SMC limit-fill feature was dead code**: guard checked `row.get("dh") / row.get("dl")` but the frame exposes `donchian_high / donchian_low` → `btc_smc_entry` was always `None` (SOL's identical feature worked — the inconsistency proves the typo). | **[FIXED]** |
| 28 | 🟠 | `services/demo_runner/demo_server.py:458-460` | Replay loop wraps `idx` back to `START_INDEX` **without resetting accounts** → the same market period is traded repeatedly into the same account; summary stats double-count identical candles ("real testing in demo" violation). | **[FIXED]** replay wrap resets accounts via `build_default_accounts()` + clears signals |
| 29 | 🟠 | `services/demo_runner/demo_server.py:458-460` | Positions open at the wrap carry into the replayed past → `exit_time < entry_time` in trade records. | **[FIXED]** wrap reset closes/erases stale positions (no `exit_time < entry_time`) |
| 30 | 🟠 | `scripts/run_5year_intrabar_tick_benchmark.py:92-107` | EXP-014 is billed as "5-Year Intrabar **Tick-Level** Validation" but builds a synthetic 8-point per-bar path (`O→L→H→C` heuristic) — not real ticks. Fill outcomes on ambiguous bars are path-assumption artifacts. | **[FIXED]** re-labelled SYNTHETIC 8-point approximation in script + EXP-014 ledger notes; EXP-017 rerun recorded |
| 31 | 🟡 | `roi_ledger.py:18`, `ml/train.py:48,114`, `walk_forward_learner.py:105`, `event_filter.py:46`, `ops_bridge.py:56`, `storage.py:14`, `demo_server.py:58` | `os.makedirs(os.path.dirname(p))` crashes on bare filenames (`dirname == ""`); 8 sites (only `fusion.py` guarded). | **[FIXED]** (`or "."` guard) |
| 32 | 🟡 | `core/ml/predict.py:54` | `except Exception: pass → return 0.50` — any model/feature failure silently degrades to neutral sizing with **no log**. | **[FIXED]** `logger.warning(..., exc_info=True)` |
| 33 | 🟡 | `core/ml/train.py:96` | `except Exception: pass` around Optuna HPO — silently trains with default params on any failure, no log. | **[FIXED]** `logger.warning(..., exc_info=True)` |
| 34 | 🟡 | `core/signals/event_filter.py:50,76` | Calendar cache load/save failures swallowed silently → event filter silently runs empty (trades through high-impact news). | **[FIXED]** `logger.warning(..., exc_info=True)` |
| 35 | 🟡 | `services/data_collector/sources/hyperliquid.py:49-62` | `fetch_ticker`/`fetch_funding_rate` errors swallowed → signals pipeline receives `0.0` price/OI/funding indistinguishable from real values. | **[FIXED]** `fetch_ok` flag + warnings instead of silent zeros |
| 36 | 🟡 | `core/analysis/backtest_analyzer.py:41` | `max_drawdown_account * 100.0` assumes fraction input; if a source stores percent, drawdown reports inflate 100×. Unverified against all producers. | **[FIXED]** fraction/percent schema guard |
| 37 | 🟡 | `services/demo_runner/demo_server.py:162-164` | Inner merges of the 4 asset frames silently truncate every asset to the shortest dataset (period asymmetry unnoticed). | **[FIXED]** inner-join row/range logging (warmup trim surfaced in logs) |
| 38 | 🟡 | `services/demo_runner/demo_server.py:108` | `atr = tr.rolling(14).mean().bfill()` — warmup rows use **future** ATR values (minor lookahead in first 13 bars). | **[FIXED]** ATR warmup rows dropped (no `bfill` lookahead) |

## Tier D — Reproducibility, compatibility and debt

| # | Sev | Location | Bug | Status |
|---|-----|----------|-----|--------|
| 39 | 🟡 | `scripts/sync_*.py` (5 files) | `datetime.utcnow()` — deprecated since 3.12, removal scheduled; log timestamps will break. | **[FIXED]** `datetime.now(timezone.utc)` in 5 sync scripts |
| 40 | 🟡 | `requirements.txt` | No upper bounds on `pandas`, `numpy`, `fastapi`, `scikit-learn`, `ccxt` — a fresh install can silently change backtest math (pandas 3.0 Copy-on-Write, numpy 2.x semantics) → results not reproducible across installs. | **[FIXED]** upper bounds pinned (pandas<3, numpy<3, fastapi<1, scikit-learn<2, ccxt<5) |
| 41 | 🟡 | `services/demo_runner/demo_server.py:504` | `@app.on_event("startup")` deprecated (FastAPI lifespan); breaks on a future FastAPI/Starlette. | **[FIXED]** FastAPI lifespan handler |
| 42 | 🟡 | `core/ml/features.py:167` | `labels.fillna(-1, inplace=True)` — chained/inplace mutation flagged by pandas Copy-on-Write (pandas 3.0 emits warnings or errors). | **[FIXED]** `labels = labels.fillna(-1)` |
| 43 | 🟡 | `scripts/evaluate_leverage_roi_4h.py:50` | `np.roll(ema50, 3)` wraps the series tail into the first 3 rows → contaminated `ema50_slope` feature at the start. | **[FIXED]** `np.roll` wrap-around replaced with NaN-head shifts |
| 44 | 🟡 | `scripts/evaluate_leverage_roi_4h.py:193` | `monthly_roi` computed from a module-global `months_elapsed` — fragile implicit coupling; a wrong global silently rewrites all sweep output. | **[FIXED]** `months_total` parameter (no module-global coupling) |
| 45 | 🟡 | `services/demo_runner/demo_server.py` (~1.5k LOC), `multi_asset_engine.py`, `real_paper_engine.py`, `quantum_paper_engine.py`, most `scripts/` | **No unit tests** for the user-facing demo server and 3 of 5 engines (only dual_slot, micro-mode and Hyperliquid executor are covered). | partial — regression tests added for engines (`tests/test_audit_fixes.py`); demo server still undertested |
| 46 | 🟢 | `scripts/run_hyperliquid_live_smoke.py:25`, `tests/test_hyperliquid_integration.py:6`, others | Dead imports (pyflakes): 191 warnings repo-wide incl. unused imports that mask intent. | partial — unused imports removed in touched files; full pyflakes sweep pending |
| 47 | 🟢 | `scripts/run_dual_slot_shared_pool_benchmark.py:407,409` | f-strings without placeholders (formatting debt). | **[FIXED]** f-strings cleaned |
| 48 | 🟢 | `core/analysis/roi_ledger.py:73-75` | Ledger key-schema drift was the root cause of the `months_elapsed=0.0` corruption: callers pass `duration_months`/`months`/`months_elapsed` interchangeably. Alias fallback fixed the symptom; the schema itself is still implicit. | partial — `RESULT_KEY_ALIASES` + `normalize_results()`; explicit dataclass schema pending |
| 49 | 🟢 | `core/ml/train.py:48,114`, `walk_forward_learner.py:105`, `evaluate_leverage_roi_4h.py:64` | Model artifacts written to **CWD-relative** `models/...` paths → train/predict can silently load different files depending on launch directory. | **[FIXED]** model paths anchored to repo root |
| 50 | 🟢 | `tests/` collection | `tests/__pycache__` .pyc files are picked up by grep/IDE searches as duplicate test sources (noise in audits); no `pytest.ini` `testpaths` pinning. | **[FIXED]** `pytest.ini` `testpaths` pinned to all 5 test dirs |

---

## Already fixed in earlier audit rounds (kept for the record)

- Round 1 (`936d7ff`): Hyperliquid price tick rules (5 sig figs + `6−szDecimals`), venue price
  rounding, pyramid min-notional gate, ccxt flat `params` dict, plan-dict consistency.
- Round 2 (`5c43b80`): wrong-side `long`/`short` plan routing (critical), `atr=0` size explosion in
  the live gate + paper engine, dry-run `fetch_equity` silent 0.0, ledger `months_elapsed`
  corruption (+ 5 stored entries repaired).

## Recommended sequence

1. **Re-run the experiment ledger after Tier A patches** (entries 1-13): the champion numbers
   (EXP-013/015) are affected by maker-on-stop fees (#11) and optimistic fill ordering (#6-10);
   re-baseline `reports/roi_progress_ledger.json` with the corrected engines and record the new
   experiments honestly. — **DONE (2026-10-29):** `EXP-016-AUDIT-CORRECTED-DUAL-SLOT` (corrected
   fill model, bench panel at `data/timeframes/bench_panel/`) and
   `EXP-017-AUDIT-CORRECTED-INTRABAR-SYNTHETIC` recorded; EXP-013/014 preserved and re-labelled.
   Note: the corrected fill model changed ROI materially vs EXP-013 (control rerun of the old model
   reproduces $3,391.10 exactly) — read EXP-016's notes for the model-sensitivity caveat.
2. Land Tier B/C patches with the regression tests added in this commit.
3. Tier D cleanup before the next feature sprint.

_This audit is exhaustive over the strategy/money paths and mechanical elsewhere; behavioral bugs
in low-traffic modules (`services/monitoring`, `services/mql5`, `services/freqtrade`) were not
line-audited and remain unexamined._
