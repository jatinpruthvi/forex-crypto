---
name: quantitative-trading-bug-hunter
description: "Quantitative trading bug-hunting skill for the forex-crypto research harness (Tier A: run before recording ANY backtest result) and for production engines, MT5/MQL5 bridging, and live execution (Tier B: run before deployment). Audits lookahead, cost accounting, panel alignment, null designs, math boundaries, position sizing, and broker integration."
---

# Quantitative Trading Bug Hunter

Run **Tier A before recording every backtest result** and **Tier B before deploying engine code**.
Begin every experiment by scanning the code: `python scripts/audit_scan.py <files...>` and fix
(or justify in writing) every finding. Then walk the checklists below. Record the audit outcome
next to the result — an unaudited number must never be claimed.

## Tier A — Research harness pillars (this repo, EVERY test)

### A1. Lookahead & bar timing
- Signal at bar t may use information only up to t−1: breakouts compare against
  `rolling(n).max().shift(1)`; moving stats that feed signals need `.shift(1)` or
  `expanding().mean()` (causal), never `shift(-1)`, `bfill()`, or full-sample statistics.
- Execution convention: `pnl = pos.shift(1) * ret − |Δpos| * cost` — decisions at t fill at t+1.
- Calendar rules (day-of-week, holidays) are known in advance → may apply same-day; event rules
  (funding, signals) must be shifted. Timezone-normalize timestamps BEFORE comparing sessions.

### A2. Cost & P&L accounting
- Costs 10bp/side taker on notional turnover `|Δpos|` (or `|Δw|` row-summed). Maker (3bp) only
  with a documented fill model. Funding accrues as `−(w * funding).sum(axis=1)` on held positions.
- Short return sign: `(entry − exit)/entry`; verify long/short formulas are mirror images.
- Gross exposure cap (≤ 2) applied AFTER signal stacking; leverage applied to the FINAL book only.

### A3. Panels, alignment & windows
- Slice every asset/panel to an identical index before interaction; assert
  `w.index.equals(px.index)` and column equality. `reindex().fillna(0.0)` on weights.
- Pivot/parse timestamps (`pd.to_datetime`) BEFORE `pivot_table`; watch symbol renames
  (`USDT` suffixes). After any filter, assert nonzero counts — empty-filter fallbacks must not
  silently return zeros.

### A4. Math boundaries
- Guard divisions: vol ratios (`std_n1/std_n2`), `cumsum` volume, `avg_loss`, ranges `high−low`;
  floor with `np.maximum(x, 1e-8)`. Logs need strictly positive inputs.
- NaN policy explicit in signals (`fillna(0)` at the signal layer only, never inside costs).
- `np.where` with Series conditions: keep shapes aligned (broadcast `np.repeat` for panels).

### A5. Nulls & selection honesty
- Placebos block-permute SIGNAL/weight ROWS and recompute P&L (`recompute`-style). Never shuffle
  a P&L series (Sharpe is permutation-invariant — a known trap).
- Book changes (new sleeve, weight change, slot swap) require a BLEND placebo (30 block shuffles,
  report real SR vs null p90 and pct). Best-of-N searches require a search-level null.
- All candidates must be gated identically (DD ≤ 40, minYr ≥ −1.5); report every node tried,
  not just survivors.

### A6. Reproducibility & rebuild
- Every claimed number has a runnable, committed definition. If a historical claim cannot be
  reproduced, demote it to UNVERIFIED — never blend it into a book.
- Rebuild books from sleeves and assert equality with the composite (`sum(sleeves) == book`);
  yearly tables from equity `groupby(equity.index.year)`.

### A7. Post-run sanity sweep
- Count nonzero positions and trades per node (all-zero = bug until proven otherwise).
- Independently re-derive at least the top node with a second implementation.
- Check magnitudes against physics: cost burn/day ≈ turnover/day × cost — absurd P&L usually
  means turnover, not alpha (verify before calling anything a bug).

## Tier B — Engine pillars (production/live code, before deployment)

### B1. Execution timing
Orders fill at t+1 (next bar/tick), never at bar close t using t prices. Audit intra-candle
high/low sequencing for optimistic fills.

### B2. Asymmetric long/short formulas
Short stops/targets mirror longs; trailing-stop distances keep correct sign; percentage shorts:
`(P_entry − P_exit)/P_entry`.

### B3. Position sizing & leverage bounds
Contract multipliers per instrument (no Forex pip math on crypto perps/metals); risk sizing
cannot explode when stop distance → 0; leverage ceilings and broker tiers respected in all
volatility regimes.

### B4. Mathematical boundaries
Div-by-zero guards, log input floors, `np.polyfit` variance checks (`LinAlgError`).

### B5. ML & feature alignment
Inference column order mirrors `model.feature_names_in_`; ≥ 2 classes in every train/val window;
directional gating tested as `P ≥ thr` BUY / `P ≤ 1−thr` SELL.

### B6. Concurrency & state isolation
DB: WAL mode, timeouts, context managers. Shared state keyed by account+symbol. No silent
exception swallowing in alert paths.

### B7. Broker/exchange integration
Magic-number scoping enforced on liquidations; risk from `SYMBOL_TRADE_TICK_SIZE/TICK_VALUE`;
limit orders carry expiry (`ORDER_TIME_SPECIFIED`) to avoid stale fills.

## Per-test audit gate (copy into the experiment record)

```
AUDIT (quantitative-trading-bug-hunter):
- [ ] audit_scan.py clean (or findings justified)
- [ ] A1 no lookahead; execution at t+1 (spot-check 1 signal manually)
- [ ] A2 costs on |Δpos|; funding sign; gross cap
- [ ] A3 index/columns asserted; identical windows; nonzero counts printed
- [ ] A4 div guards; NaN policy
- [ ] A5 correct null design (weights permuted, P&L recomputed); blend placebo if book changes
- [ ] A6 runnable definition committed; rebuild check if composite
- [ ] A7 nonzero-position counts printed; top node re-derived
```

## Help tags
When stuck after exhausting solutions: `<promise>BLOCKED:brief description</promise>`,
`<promise>DECIDE:question (Option A vs B)</promise>`.
