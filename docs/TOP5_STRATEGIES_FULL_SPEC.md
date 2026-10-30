# Top-5 Strategies — Full Specification (all parameters)

Status: 2026-10-30, after EXP-035 (nuclear hunt) and EXP-036 (recovery rates).
Numbers are from the certified pipeline runs saved in
`reports/strategy_leaderboard.json` (`exp035_nuclear`, `exp036_recovery`) and
reproduced independently (`scripts/recovery_rate.py`, `scripts/nuclear_regime.py`).

---

## 0. Shared foundation (applies to all five)

### Data
- 21-coin daily panel (Binance-style USDT pairs, 1000 bars): BTC, ETH, BNB, XRP, ADA,
  DOGE, LTC, LINK, MATIC, ALGO, ATOM, CHZ, EOS, ETC, IOTA, NEO, TRX, VET, XLM, XMR, XTZ.
- Period **2020-07-20 → 2023-04-15** (~1000 daily bars). Source: `data/timeframes/1d_panel/`.
- Close panel drives all states/signals except the FVG engine, which uses the dataset's
  real OHLC.

### Execution & portfolio engine (identical for every strategy)
- Weights set at close of day `t`, realized returns `t → t+1` (**no lookahead**).
- Turnover fee **FEE = 0.0010** (10 bps) charged on `|Δw|` per rebalance.
- Gross exposure cap **lev_cap = 2.0** (gross book scaled down if `Σ|w| > 2`).
- Rotation engines rebalance every **5 days** (`rb=5`); state composites re-slice daily.
- Metric: `monthly_roi = (final/initial)^(1/years/12) − 1`; max DD on daily equity.

### The 4 trading engines (+ CASH) the mappings draw from
| Engine | Definition | Parameters |
|---|---|---|
| **FVG_LS** | Fair-value-gap retest portfolio, long+short. Per coin: bullish gap when `low[t] > high[t-2]`, bearish when `high[t] < low[t-2]`; signal ±1 fires when price returns INTO an unfilled gap; gap expires after **max_age=15** days or on close-through. A coin is "active" if a trigger fired within the last **hold=3** days. Inverse-20d-vol weights. Book = **0.6 × longs − 0.4 × shorts** (normalized per side). | `sig_fvg(max_age=15)`, `smc_pf(hold=3, long_only=False)` |
| **FVG_LONG** | Same, long book only (signals clipped to +1, `long_only=True`). | `sig_fvg(max_age=15).clip(lower=0)`, `hold=3` |
| **TSMOM** | Vol-targeted time-series momentum, per coin: `mom = sign(close[t-3]/close[t-103] − 1)` (100-day with 3-day skip); `size = clip(0.25/annvol, 0, 4)`, `annvol = 20d-std × √365`; weight = `mom × size`. | `w_tsmom_vol(lb=100, ann_vol=0.25, rb=5)` |
| **ABS_GROT** | Gated cross-sectional rotation + absolute-momentum filter. Momentum `close[t-5]/close[t-95] − 1` (90-day, 5-day skip); gate = **BTC > BTC 100-day MA** (hard gate); gate ON → top-**5** coins by momentum, inverse-20d-vol weights; then zero any coin whose trailing **90-day** return ≤ 0. | `abs_mom_filter(w_gated_rot(K=5, lb=90, gate_ma=100, rb=5), px, 90)` |
| **CASH** | Flat (all-zero weights). | — |

### State machines (regime definitions; all causal)
| State | Definition | Cells |
|---|---|---|
| **P3** (`H100b2`) | BTC vs its **100-day MA with ±2% hysteresis**: ON when `BTC > MA100×1.02`, OFF when `BTC < MA100×0.98`, hold in between. | A(ON) / B(OFF) |
| **CORR30** | Average of all **210 pairwise 30-day rolling return correlations** across the 21 coins, vs its own **expanding median shifted 1 day**. | A(high-corr) / B(low-corr) |
| **H4** | P3 hysteresis (ON/OFF) × breadth: share of coins above their own **50-day MA** — BHI `>0.60`, BLO `<0.40`, BMID otherwise. | ON_BHI, ON_BMID, ON_BLO, OFF_BHI, OFF_BMID, OFF_BLO |

### Persistence (switch smoothing)
- `persist(sm)`: a state change must hold **sm consecutive daily bars** before the
  composite switches strategies (exact port of the production state machine).
- **sm=10** for P3 and H4 (the "smooth10" in the champion); **sm=0** for CORR30_s0
  (instant switching).

### Mapping-learning rule (walk-forward; never re-selected at runtime)
- For each state cell, compute in-cell monthly ROI of every menu engine on **training bars
  only**; discard engines with `dd/Mo > 10`; pick the argmax (CASH if none qualify).
- Strict-LOFO evaluation: learn on 2 of 3 blocks (38/32/30 split of the panel), apply to
  the held-out block — the honest out-of-sample numbers.
- **Deployment = FROZEN spec**: learn once on all history, freeze the mapping (tables
  below), never re-learn at runtime (nested re-selection was proven overfitting, EXP-029/031).
- Mappings below are the **full-period-learned mapping as of 2023-04-15**.

---

## 1. Blend3 @ 75% — risk-capped deployment leader

**Definition:** `w = 0.75 × (⅓·Champion + ⅓·CORR30_s0 + ⅓·H4_s10)` — three state-driven
composites on three DIFFERENT state variables (trend/hysteresis, correlation, breadth),
averaged, scaled to ¾ size.

**Parameters:**
| Component | State | sm | Mapping (frozen 2023-04-15) | Weight |
|---|---|---|---|---|
| Champion P3 | BTC MA100 ±2% hysteresis | 10 | A→ABS_GROT, B→FVG_LS | 0.25 |
| CORR30_s0 | 30d pairwise corr vs expanding median | 0 | A(high-corr)→FVG_LONG, B(low-corr)→TSMOM | 0.25 |
| H4_s10 | hyst × breadth(50d MA, 0.6/0.4) | 10 | ON_BHI→ABS_GROT, ON_BMID→TSMOM, ON_BLO→ABS_GROT, OFF_BHI→FVG_LS, OFF_BMID→CASH, OFF_BLO→FVG_LS | 0.25 |

**Performance (real data, 10 bp fees):**
| Metric | Value |
|---|---|
| Full-period monthly | **+18.64%/mo** |
| Max drawdown / Calmar | 34.5% / 19.66 |
| Median / worst / best month | +11.2% / −15.6% / +176.6% |
| Strict-LOFO blocks (honest OOS) | **+27.78 / +5.94 / +9.65** (all positive, min +5.94) |
| Frozen blocks (deployable view) | +34.90 / +6.66 / +12.60 |
| Recovery (EXP-036) | 98.4% of dips recover; **99.7% of lost depth** returns; ≥20% dips 6/6 recovered (median 0.3 mo); deepest −34.5% → back in 2.4 mo; RF 790; OOS RF **273** (best of menu) |

**Why it exists:** at full size the components run 44–63% DD (above the program's 35% cap).
At 75% the blend is the return-maximizing variant that fits the cap, and it beats the
champion on return, weak blocks, worst month, and recovery depth.

---

## 2. ENS_CORR30_s0 × W_H4 @ 100% — the certified winner (return king)

**Definition:** `w = 0.5·CORR30_s0 + 0.5·H4_s10` (equal-weight average of the two composites).

**Parameters:** components exactly as §1 rows 2–3 (CORR30_s0 sm=0, H4_s10 sm=10), 50/50, no
extra scale. Gross ≤ 2.0, fees 10 bp.

**Performance:**
| Metric | Value |
|---|---|
| Full-period monthly | **+22.31%/mo** (reproduced independently, exact) |
| Max drawdown / Calmar | 51.0% / 20.03 ← **above the 35% cap at full size** |
| Median / worst / best month | +10.1% / −17.7% / +241.6% |
| Strict-LOFO blocks | **+32.87 / +8.80 / +12.98** (min +8.80, ALL+) |
| Frozen blocks | +39.21 / +9.82 / +15.88 |
| Recovery | 98.4% dips; 99.7% depth; ≥20% 8/8 (0.3 mo); deepest −51.0% → 7.5 mo; RF 1455 |

**Verification (only policy to pass ALL FOUR pre-registered gates):**
1. Min strict-LOFO +8.80 > champion +1.88 ✓
2. LOFO all-positive ✓
3. Config placebo **p100** (0/30 block-shuffled label draws beat it) ✓
4. Selection-adjusted: +8.80 vs full-pipeline search-null p90 +7.25 (8 BFS→DFS→polish
   runs on shuffled labels; 1/8 beat it) ✓ — no-lookahead audit PASS.

**Deployment form:** never at 100% size under the 35% DD gate — use §1 (Blend3@75%) or
§2-sized 55% (= +16.07%/mo at DD 34.3, LOFO +21.74/+5.30/+9.84, worst recovery 2.3 mo).

---

## 3. Champion P3 + smooth10 — the incumbent (low-drawdown anchor)

**Definition:** single state-driven composite: BTC MA100 ±2% hysteresis, 10-day persistence.

**Parameters:**
| Element | Value |
|---|---|
| State | `hyst_state(px, ma=100, band=0.02)`: ON if `BTC > MA100×1.02`, OFF if `BTC < MA100×0.98`, else hold |
| Persistence | sm = **10** consecutive daily bars to confirm a switch |
| Mapping (frozen) | **A(ON) → ABS_GROT**, **B(OFF) → FVG_LS** |
| Engine params | ABS_GROT: K=5, lb=90, gate MA100, abs-mom 90d, rb=5 · FVG_LS: max_age=15, hold=3, 0.6L/−0.4S |
| Sizing | full size (gross ≤ 2.0), fees 10 bp |

**Performance:**
| Metric | Value |
|---|---|
| Full-period monthly | +16.02%/mo |
| Max drawdown / Calmar | **25.1%** / 19.74 ← only menu member ≪35% |
| Median / worst / best month | +5.4% / −21.3% / +188.7% |
| Strict-LOFO blocks | +31.79 / +4.33 / +1.88 (all positive) |
| Frozen blocks | +34.99 / +4.33 / +6.85 |
| Recovery | 98.3% dips; **94.3%** depth (one ≥20% dip unrecovered at panel end); ≥20% 6/7 (1.4 mo); deepest −25.1% → 3.1 mo; RF 520 |

**Verification:** placebos p100 (EXP-033); search-null: LOFO avg +12.67 vs null +4.3
(p100, EXP-031/034). Only policy exceptional under every null. Smoothing plateau:
sm 3/5/15 ALL+ too; thresholds 0.55/0.45 and 0.65/0.35 robust.

---

## 4. ENS_CORR30_s0 × W_P3 — runner-up ensemble

**Definition:** `w = 0.5·CORR30_s0 + 0.5·Champion P3` (correlation-state × trend-hysteresis).

**Parameters:** §1 rows 1–2 at 50/50, no scale. Same execution envelope.

**Performance:**
| Metric | Value |
|---|---|
| Full-period monthly | +22.19%/mo |
| Max drawdown / Calmar | 49.8% / 20.24 |
| Median / worst month | +10.1% / −17.7% |
| Strict-LOFO blocks | **+37.76 / +8.53 / +10.24** (min +8.53 — highest block-1 of menu) |
| Frozen blocks | +39.19 / +9.49 / +15.88 |
| Recovery | 98.4% dips (60/61); **99.7%** depth; ≥20% dips 8/8 (median 0.3 mo); deepest −49.8% (2021-05-09→2022-02-06) → back in 7.5 mo; RF 1441 |

**Verification:** config placebo **p100** (0/30). Shares the CORR30_s0 engine that carries
the discovery; diversifies the champion's trend state with the correlation state.

---

## 5. CORR30_s0 — the core discovery (best single new policy)

**Definition:** single composite on the **correlation regime** alone, no smoothing.

**Parameters:**
| Element | Value |
|---|---|
| State | `corr30(t) = mean of all 210 pairwise rolling-30d return correlations`; A if `corr30 > expanding_median.shift(1)` (high-corr), else B |
| Persistence | sm = **0** (instant) — s3/s5/s8 also ALL+ (min +6.70/+7.04/+6.78); sm10 min +5.10 |
| Mapping (frozen) | **A(high-corr) → FVG_LONG**, **B(low-corr) → TSMOM** |
| Engine params | FVG_LONG: max_age=15, hold=3, long-only · TSMOM: lb=100, ann_vol 0.25, rb=5 |
| Sizing | full size (its DD is why it lives inside blends) |

**Performance:**
| Metric | Value |
|---|---|
| Full-period monthly | +19.44%/mo |
| Max drawdown / Calmar | **63.5%** / 11.70 ← do not deploy standalone at full size |
| Median / worst / best month | +9.1% / −26.4% / +205.6% |
| Strict-LOFO blocks | **+28.64 / +8.63 / +13.45** (min +8.63 — best single-policy weak block) |
| Frozen blocks | +28.64 / +10.10 / +17.82 |
| Recovery | 98.0% dips; **99.7%** depth; **≥20% dips 10/10 recovered** (median 0.4 mo); the −63.5% crash (2021-07→2022-03) fully recovered in 8.2 mo; RF 535 |

**Verification:** config placebo **p100** (0/30); no-lookahead PASS; lookback plateau
(CORR20 min +5.76..+5.92); smoothing plateau (s3/s5/s8). Interpretation: when everything
correlates (risk-off cascades) the retest-long book + TSMOM rotation recovers fastest;
when dispersion is high the rotation engines compound.

---

## Quick-select table

| # | Strategy | %/mo | MaxDD | LOFO min | Depth recov. | Worst recov. | Role |
|---|---|---|---|---|---|---|---|
| 1 | **Blend3@75%** | +18.64 | 34.5% | +5.94 | 99.7% | 4.5 mo | risk-capped deployable |
| 2 | ENS_CORR30×H4 (100%) | +22.31 | 51.0% | +8.80 | 99.7% | 7.5 mo | certified engine (size down) |
| 3 | Champion P3+sm10 | +16.02 | 25.1% | +1.88 | 94.3% | 3.1 mo | low-DD anchor |
| 4 | ENS_CORR30×P3 (100%) | +22.19 | 49.8% | +8.53 | 99.7% | ~7.4 mo | runner-up ensemble |
| 5 | CORR30_s0 | +19.44 | 63.5% | +8.63 | 99.7% | 8.2 mo | discovery engine (blend only) |

Sizing variants: ENS_CxH4@55% = +16.07%/mo @ DD 34.3 (LOFO +21.74/+5.30/+9.84);
Blend3@70% = +17.57%/mo @ DD 32.9. Banned from standalone deployment at full size by the
35% DD gate: rows 2, 4, 5. ForeX: zero allocation (EXP-032 negative).

## Verification status summary
- Selection-adjusted search-null (8 full BFS→DFS→polish runs on shuffled labels): only the
  ENS_CORR30 family clears the p90 bar; the EXP-034 challengers (H7, VOTE) failed it.
- Config placebos (30 block-shuffled draws each): rows 1–5 components all **p100**.
- No-lookahead audits: PASS on all state families used.
- Independent reproduction via `fold_metrics` + real builders: exact for the winner.
