# IMPROVEMENT PLAN — Out-of-the-Box ROI Hunt (started 2026-10-30)

**Directive (user)**: think with full freedom, focus on trading only, no fantasy — every idea must be
tested on real data with real costs, one by one, and the ROI tracked per idea. This document is the
master plan + live tracker. Baseline = **Book R3** (certified 2026-10-30).

## Ground rules (unchanged, they protect us from fantasy)
1. Every idea tested on real historical data with ≥10bp/side costs (taker) or 3bp maker where
   execution design says post-only.
2. Any strategy proposed for the book must beat its own placebo AND pass a blend placebo before it
   earns weight. Search-level claims get selection-adjusted honesty.
3. Tracker below updated after EVERY test — PASS or FAIL, both are progress.
4. `2026` data is used in-search so far; idea I-21 is a dedicated leakage/lockbox audit — anything
   that only works with 2026 included gets demoted.

## Baseline — Book R3 (the number every idea must beat)
| lev | %/mo | SR | DD | minYr |
|---|---|---|---|---|
| ×1.0 | +2.36 | 1.68 | 13.3 | +0.22 |
| ×2.0 | +4.52 | 1.68 | 25.7 | +0.31 |
| ×3.0 | +6.47 | 1.68 | 37.2 | +0.27 |

---

## THE IDEA INVENTORY (what we have NOT tested)

### Wave 1 — direct book upgrades (highest EV, run first)
| ID | idea | mechanism | data | status |
|---|---|---|---|---|
| I-01 | **Squeeze-family systematic expansion** | grid + pair slot-upgrade | daily panel | **DONE — PASS → R3.1** |
| I-02 | **Fold the EXP-044 timeframe winners into the book** | blend + placebo | 4h + daily | **DONE — FAIL (claims unverified)** |
| I-03 | **Basis / perp-cash dispersion sleeve** (rebuilt as daily basis-MR) | basis dislocation → convergence | perp 4h vs spot daily | **DONE — FAIL (blend 43pct)** |
| I-04 | **Book engineering**: inverse-vol weights, vol-scaled leverage | growth-per-DD | R3 components | **DONE — dominated** |
| I-05 | **12h + common/EW squeeze** variants | regime timing | panel | **DONE — dead** |

### Wave 2 — new mechanisms (completely untested territory)
| ID | idea | mechanism | data | status |
|---|---|---|---|---|
| I-06 | **Intraday seasonality (hour-of-day / day-of-week)** — crypto has persistent UTC-hour effects; we own the 5m tape 2019-2025 and never looked | recurring liquidity/timezone flows | 5m/1h parquet | UNTESTED |
| I-07 | **Maker-fill intraday mean-reversion (15m/1h)** — taker scalping is dead at 12bp, but post-only maker entries cost 3bp; the cost-regime flip can resurrect short-horizon MR | limit-order MR at maker fees | 5m tape | UNTESTED |
| I-08 | **EQ→crypto lead-lag** (yesterday's equity move sizes today's BTC/ETH) + **alt-season breadth** (share of 15 coins > 50d MA → risk-on regime) | intermarket information | daily panel | UNTESTED |
| I-09 | **Extreme-funding fade (event strategy)** — top-decile funding spike → fade the crowded side for k days | positioning capitulation | funding_all 5y × 15 coins | UNTESTED |
| I-10 | **DeFi TVL momentum as regime overlay** (defillama TVL restored, never used) | on-chain risk appetite | macro/defillama | UNTESTED |
| I-11 | **Cross-exchange basis mean-reversion** (Binance spot-vs-perp basis 5m 2022-2025 — own the data) | basis dislocation → convergence, two legs | olaxbt basis 5m | UNTESTED |
| I-12 | **Grid/range bot at maker fees on 4h/1h ranges** (grid = #3 GitHub family, 37/700 repos, never tested) | harvest chop that trend loses on | 4h/1h parquet | UNTESTED |
| I-13 | **Multi-timeframe confirmation** (1d trend gate × 4h trigger as ONE composite) | raise precision of tf winners | daily + 4h | UNTESTED |
| I-14 | **Walk-forward sleeve-weight adaptation** (rolling re-fit of sleeve weights — sleeve level, not the failed per-coin brain) | adapt to regime mix | R3 components | UNTESTED |

### Wave 3 — execution & live-ROI levers (reliable, boring, real money)
| ID | idea | mechanism | data | status |
|---|---|---|---|---|
| I-15 | **Maker-entry execution for the book** (post-only entries on forecast-driven signals; taker exits) — halves entry cost on all turnover | cost reduction ~0.035%/trade | 5m tape (fill realism) | UNTESTED |
| I-16 | **3x-funding-day avoidance** (exchanges charge triple funding on schedule days) | avoid known bleed | funding timestamps | UNTESTED |
| I-17 | **Drawdown parking**: after book DD > x, park exposure in stablecoin yield until re-confirmation | cut tail bleed, earn cash carry | defillama yields | UNTESTED |
| I-18 | **Weekend/overnight effects** (Fri-close→Mon-open, Asia-hour bias) as exposure filter | documented calendar effects | 5m tape | UNTESTED |

### Wave 4 — thin-data probes (cheap, honest about limits)
| ID | idea | mechanism | data | status |
|---|---|---|---|---|
| I-19 | **Options IV-RV carry on Deribit snapshots** (short vol when IV ≫ subsequent realized, delta-hedged proxy) | volatility risk premium | deribit hourly 2022-2025 | UNTESTED |
| I-20 | **Options skew probe** (25d RR skew as direction signal — expected flat, one probe then close) | informed positioning | deribit snapshots | UNTESTED |

### Wave 5 — truth & robustness (protects every result above)
| ID | idea | mechanism | status |
|---|---|---|---|
| I-21 | **2026 lockbox audit**: re-derive every champion using 2021-2025 only, then reveal 2026 | kill in-sample leakage | UNTESTED |
| I-22 | **Sleeve-level DD de-risk overlay** (reduce exposure after sleeve DD > threshold) | path-dependent risk control | UNTESTED |
| I-23 | **ETH/BTC ratio regime** (ratio momentum switches BTC-vs-ETH weights) | rotation between majors | UNTESTED |
| I-24 | **Short-vol sleeve regime-conditional add** (EXP-042 short-vol node, only when funding calm) | conditional diversifier | UNTESTED |

### Closed (pre-checked, don't spend time)
- Liquidation-cascade strategies: no historical liquidation data source.
- Order-book L2 microstructure: no L2 history.
- New-listing/small-cap rotation: 20bp+ costs kill it (EXP-036/037).
- Prediction markets / copy trading / airdrops: out of scope (trading only).

---

## ROI TRACKER (live — updated after every test)

Baseline for delta: Book R3 ×2 = +4.52%/mo, SR 1.68, DD 25.7, minYr +0.31.

| ID | test result (%, SR, DD, minYr) | placebo | book impact | new champion? |
|---|---|---|---|---|
| I-01 | sqz pair slot-upgrade: x1 +2.46%/mo SR 1.77 DD 14.5 minYr +0.04 (grid 126 nodes; best solo sqz_20_100_0.7_30_ETH +1.80 SR 0.94) | slot placebo **PASS 100th pct** (null p90 1.52) | **+0.09 SR, +0.10%/mo at x1; x3 = +6.80%/mo** | **YES — Book R3.1** |
| I-02 | **FAIL**: EXP-044 tf claims UNVERIFIED (reimpl +0.32/−0.66 vs claimed +2.68/+2.23; combo blend SR 1.34) | blend pct 67 FAIL | none (demoted) | no |
| I-03 | basis-MR_BTC +0.12%/mo SR 0.60 DD 2.2 (thin activity) | standalone 97pct; **blend pct 43 FAIL** | none | no |
| I-04 | inv-vol sleeves SR 1.44; vol-scaled SR 1.54 — both dominated by R3's 1.68 | n/a | none | no |
| I-05 | 12h squeeze dead (SR 0.49/0.07); common/EW squeeze dead (DD 90+) | n/a | none | no |
| I-06..I-24 | _untested_ | | | |

**Cumulative best book: R3.1 (x1 +2.46 SR 1.77 / x2 +4.73 DD 27.4 / x3 +6.80 DD 39.0). All-positive-years variant stays R3 (x2 +4.52 minYr +0.31). Next: Wave 2 (I-06 intraday seasonality, I-07 maker-fill MR, ...).**
