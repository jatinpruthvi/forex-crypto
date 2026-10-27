---
name: quantitative-trading-bug-hunter
description: "Comprehensive quantitative trading and algorithmic engine bug-hunting skill. Audits execution logic, signal generation, mathematical models, machine learning pipeline, risk management guards, MT5/MQL5 bridging, and exchange fee accounting."
---

# Quantitative Trading Bug Hunter

## Intent
Use this skill to perform deep architectural, logical, and mathematical audits of quantitative trading systems, crypto perpetual engines, forex algorithmic bridges, and MQL5 expert advisors.

## 7-Pillar Inspection Checklist

### Pillar 1: Bar-Timing Ordering & Lookahead Leakage
- Verify whether orders are executed at $t+1$ (open of next candle or tick) rather than at bar close $t$ using $t$ prices.
- Inspect indicator calculations for unshifted `.diff()`, `.rolling().max()`, or `shift(-1)` lookahead bias.
- Audit high/low intra-candle execution sequence to prevent optimistic fill assumptions.

### Pillar 2: Asymmetric Long/Short Formula Integrity
- Audit directional formulas: short stops and targets must move inversely to long formulas.
- Verify percentage returns on short positions: $\frac{P_{\text{entry}} - P_{\text{exit}}}{P_{\text{entry}}}$.
- Verify that trailing stop distances and breakeven offsets remain negative relative distances in execution engines.

### Pillar 3: Position Sizing & Leverage Bound Checks
- Check currency/lot conversion: ensure Forex pip calculations are not applied to Crypto Perpetual or Metal contracts without proper contract multipliers.
- Ensure risk amounts respect equity bounds and cannot explode when stop-loss distance is extremely small.
- Verify that leverage ceilings and broker tier limits are respected under all market volatility regimes.

### Pillar 4: Statistical & Mathematical Boundaries
- Inspect divisions for zero or near-zero denominators (e.g. `avg_loss`, `volume`, `lags`, `high - low`).
- Check logarithmic transformations: ensure inputs are strictly positive (`np.maximum(x, 1e-8)`).
- Verify polynomial fitting (`np.polyfit`) has variance across coordinates to prevent `LinAlgError`.

### Pillar 5: Machine Learning & Feature Engineering Alignment
- Verify that feature column order in inference strictly mirrors `model.feature_names_in_`.
- Check class diversity before retraining: ensure training/validation windows have $\ge 2$ classes.
- Verify directional probability gating: an ML model predicting upward probability must be tested directionally (`P >= threshold` for BUY, `P <= (1 - threshold)` for SELL).

### Pillar 6: Concurrency, Thread Safety & State Isolation
- Ensure database connections use WAL mode, timeouts, and context managers to avoid file descriptor leaks.
- Ensure shared global state is keyed by account ID and symbol to prevent multi-tenant race conditions.
- Prevent unhandled timeouts or silent exception swallowing in critical alert dispatchers.

### Pillar 7: MetaTrader (MQL5) & Broker Integration
- Ensure Magic Number scoping is strictly enforced during liquidations to protect manual/third-party trades.
- Calculate risk using broker-reported `SYMBOL_TRADE_TICK_SIZE` and `SYMBOL_TRADE_TICK_VALUE`.
- Ensure order expiration (`ORDER_TIME_SPECIFIED`) is set on limit orders to avoid stale fills.
