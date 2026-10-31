# IMPROVEMENT PLAN — Out-of-the-Box ROI Hunt (started 2026-10-30)

**Directive (user)**: think with full freedom, focus on trading only, no fantasy — every idea tested
on real data with real costs, **one by one**, ROI tracked per idea. **ALL strategies must be listed
in this document FIRST; validation then proceeds ONE strategy per turn.**

## Ground rules
1. Every idea tested on real historical data with ≥10bp/side costs (taker) or 3bp maker where the
   execution design says post-only.
2. Book admission requires standalone placebo AND blend placebo. Search-level honesty always.
3. Tracker updated after EVERY test — PASS or FAIL both count.
4. Bug gate before any number: `python scripts/audit_scan.py <script>` + Tier A checklist
   (`.agent/skills/quantitative-trading-bug-hunter/SKILL.md`).
5. **Validation protocol: one strategy per invocation. Test → record its tracker row → commit →
   stop. Wait for the user's go before the next.**

## Baseline books (what every idea must beat)
| book | %/mo | SR | DD | minYr |
|---|---|---|---|---|
| R3 ×2 (all-years-positive variant) | +4.52 | 1.68 | 25.7 | +0.31 |
| **R3.1 ×2 (growth champion)** | **+4.73** | **1.77** | 27.4 | −0.06 |
| R3.1 ×3 | +6.80 | 1.77 | 39.0 | −0.30 |

---

## A. VOLUME PROFILE — MASTER LIST (VP-01 … VP-18) + VP×SS COMBOS

Rolling N-day volume-at-price profile built causally from intraday bars (15m), profile features:
POC (point of control), VAH/VAL (value-area high/low, 70%), HVN/LVN (high/low volume nodes),
profile width, volume delta. Every strategy below is its own validation unit.

| ID | strategy (exact rule) | mechanism | status |
|---|---|---|---|
| VP-01 | **POC fade** — long below POC, short above (20d profile, daily decision) | reversion to highest-volume price | PRE-SCREENED FAIL (EXP-048: −3.03%/mo BTC, −6.32 ETH) |
| VP-02 | **POC breakout** — long above POC, short below (trend away from POC) | acceptance outside value | UNTESTED |
| VP-03 | **VAH/VAL breakout** — long above VAH, short below VAL | value-area escape | PRE-SCREENED FAIL (best +0.12 SR, placebo 77pct) |
| VP-04 | **VAH/VAL fade** — short above VAH, long below VAL (back to POC) | value edges repel | PRE-SCREENED FAIL (−2.2/−2.2%/mo) |
| VP-05 | **Value-area rotation** — fade only INSIDE the value area (VAH↔VAL oscillation) | rotation regime | UNTESTED |
| VP-06 | **HVN support/resistance reversion** — fade toward nearest high-volume NODE (multi-node, not just POC) | HVN attract price | UNTESTED |
| VP-07 | **LVN breakout** — enter in direction of travel through low-volume nodes (fast-through zones) | LVN repel price | UNTESTED |
| VP-08 | **LVN gap-fill** — fade moves that jumped an LVN, target the unfilled LVN | unfilled volume vacuum | UNTESTED |
| VP-09 | **Volume-at-price z-reversion** — fade when price z > 1.5 vs profile σ | distribution extremes | PRE-SCREENED FAIL (−2.7/−3.1%/mo) |
| VP-10 | **Anchored VWAP (aVWAP)** — volume profile anchored to weekly open / monthly open / swing low; fade to anchor, or trend with price vs anchor | institutional reference | UNTESTED |
| VP-11 | **Developing-POC slope** — trend signal from POC drift direction (rising/falling POC over k days) | value migration = trend | UNTESTED |
| VP-12 | **Profile-width compression** — narrow profile (σ of volume distribution ↓) predicts breakout; enter with break direction | compression → expansion | UNTESTED |
| VP-13 | **Volume delta** — up-bar volume minus down-bar volume imbalance (15m) → daily net pressure signal | aggressive flow | UNTESTED |
| VP-14 | **Volume climax / exhaustion** — extreme volume spike bar → fade the bar's direction | capitulation reversal | UNTESTED |
| VP-15 | **Prior-day levels (PDH/PDL/PDC)** — breakout through prior-day high/low, or fade to prior-day close | classic floor-trader levels | UNTESTED |
| VP-16 | **Prior-week levels (PWH/PWL/PWC + weekly VAH/VAL/POC)** — same logic, weekly profile | swing reference | UNTESTED |
| VP-17 | **Multi-timeframe profile confluence** — daily POC + weekly POC agreement required for entry | confluence filter | UNTESTED |
| VP-18 | **RVOL confirmation overlay** — volume vs 20d norm gates the squeeze/VP signals | volume confirms | PRE-SCREENED FAIL (gating squeeze: SR 1.77→1.60) |

### VP × SS combo strategies (each its own unit)
| ID | strategy | status |
|---|---|---|
| VPSS-01 | Prior-day POC/VA levels traded only during London+US sessions | UNTESTED |
| VPSS-02 | Initial Balance (first hour) + volume delta confirmation → IB extension | UNTESTED |
| VPSS-03 | Session VWAP + daily POC confluence (both aligned → trade) | UNTESTED |

## B. SESSION-BASED — MASTER LIST (SS-01 … SS-18)

Sessions (UTC): Asia 00:00–08:00 · London 08:00–13:30 · US 13:30–20:00 · Off 20:00–24:00.

| ID | strategy (exact rule) | mechanism | status |
|---|---|---|---|
| SS-01 | **Asian-range breakout** — stop-and-reverse at Asia range high/low | session momentum continuation | PRE-SCREENED FAIL (−6.3 BTC / −3.5 ETH %/mo at 10bp) |
| SS-02 | **Asian-range fade** — fade breaks of Asia range edges (return into range) | Asia range as magnet | UNTESTED |
| SS-03 | **Opening Range Breakout (ORB)** — first 30/60 min of ANY session; breakout of that range | opening auction imbalance | UNTESTED |
| SS-04 | **London-open momentum** — sign of first hour (08–09) holds 09–13:30 | EU flow continuation | PRE-SCREENED FAIL (−5.7/−5.0%/mo) |
| SS-05 | **London-open breakout confluence** — trade London break of Asia range only (subset of SS-01/SS-05 logic, direction confirmed by gap) | confluence | UNTESTED |
| SS-06 | **NY-open momentum** — sign of 13:30–14:30 holds 14:30–20:00 | US flow continuation | PRE-SCREENED FAIL (−6.1/−6.6%/mo) |
| SS-07 | **NY lunch-hour fade** — fade the direction of 12:00–13:30 drift into the 13:30 reopen | midday liquidity dip | UNTESTED |
| SS-08 | **Late-session (US-close) momentum** — hours 20–22 direction continues (descriptive sample: h21 +1.2bp/bar, h22 +0.8) | documented late-day drift | UNTESTED |
| SS-09 | **Session-VWAP trend** — with price vs session VWAP | intraday value trend | PRE-SCREENED FAIL (−45 to −57%/mo: 2.95%/day cost burn — 15m flip frequency is fatal at 10bp) |
| SS-10 | **Session-VWAP fade** — against price vs session VWAP | mean reversion to value | PRE-SCREENED FAIL (same cost burn) |
| SS-11 | **Session-gap fade/continue** — fade small gaps, continue large gaps (gap = session open vs prior session close) | overnight positioning | UNTESTED |
| SS-12 | **Day-of-week seasonality (causal)** — per-weekday mean signals via expanding stats | calendar effects | UNTESTED |
| SS-13 | **Hour-of-day seasonality (causal z)** — expanding hour means, z > 1 filter | timezone flows | PRE-SCREENED FAIL (max causal z 0.24 → 0 trades) |
| SS-14 | **Fixed late-day hours hypothesis** — long hours 20–22, short hour 23 (fixed a priori from external literature, not our sample) | published intraday effect | UNTESTED |
| SS-15 | **Session-volatility filter** — trade the book only during London+US, skip Asia/off hours | quality-of-liquidity | UNTESTED |
| SS-16 | **Initial Balance extension** — first-hour range (09:30-equivalent): breakout target = 1×/2× IB range | auction theory | UNTESTED |
| SS-17 | **Friday-close / Sunday-open effects** — Friday 20:00–24:00 and Sunday 00:00–08:00 specific rules | weekly positioning | UNTESTED |
| SS-18 | **Multi-session confluence** — Asia range + London break + NY confirmation chain (all three must agree) | staged confirmation | UNTESTED |

### Volume profile + session additions found in gap-audit (2026-10-30)
| ID | strategy (exact rule) | mechanism | status |
|---|---|---|---|
| VP-19 | **CVD divergence** — cumulative volume delta (up-bar minus down-bar volume) diverges from price → fade price | informed flow vs price | UNTESTED |
| VP-20 | **Classic pivot levels** — floor pivots PP/R1/R2/S1/S2 and Camarilla from prior-day HLC; breakout/fade at levels | institutional reference levels | UNTESTED |
| VP-21 | **Market Profile TPO** — value area from time-price-opportunity counts (not volume); trade TPO value edges | time-based value | UNTESTED |
| SS-19 | **Turn-of-month** — first 3/last 3 trading days of month long-bias (documented equity/crypto effect) | month-end flows | UNTESTED |
| SS-20 | **Deribit options-expiry day effect** — last Friday of month: pre/post-expiry positioning rules (calendar is computable) | dealer hedging flows | UNTESTED |
| SS-21 | **FOMC / CPI / NFP event days** — fixed public calendar; day-of and day-after directional/vol rules | macro event flows | UNTESTED |
| SS-22 | **London-fix time (16:00 UTC)** — mean reversion or drift around the fixing window | fix-related flows | UNTESTED |

### PRE-SCREEN NOTE (EXP-048, 2026-10-30)
The PRE-SCREENED rows above were run as a batch at 10bp taker and failed. The screen covered only
those exact rules — **it does NOT close the family**: every UNTESTED row remains a validation unit.
Additionally, all 15m-frequency rules must be re-tested under the maker-fee regime (I-07, 3bp
post-only) before final closure, since the screen showed the deaths were cost-burn driven.

---

## C2. GAP-AUDIT ADDITIONS (2026-10-30) — families missed in the original inventory

### Candle & chart patterns (CH) — classical TA signals never tested here
| ID | strategy | status |
|---|---|---|
| CH-01 | Engulfing / harami reversal patterns (daily & 4h) | UNTESTED |
| CH-02 | Pin bar / hammer / shooting-star reversal | UNTESTED |
| CH-03 | Doji indecision → breakout direction filter | UNTESTED |
| CH-04 | Double top / double bottom (swing-based detector) | UNTESTED |
| CH-05 | Support/resistance retest (prior swing high/low touch → fade/hold) | UNTESTED |

### Sentiment & positioning (SNT/FG) — DATA FOUND, never used (olaxbt repo)
Data: `data/news_sentiment/daily_by_coin.csv` + `daily_titles.jsonl` + `data/macro/fear_greed_daily.csv`
+ `fred_daily.csv` (restore via gh api blobs; not yet downloaded).
| ID | strategy | status |
|---|---|---|
| SNT-01 | Sentiment momentum — daily per-coin sentiment level/change → position | UNTESTED |
| SNT-02 | Sentiment extremes fade — top/bottom decile sentiment → reverse | UNTESTED |
| SNT-03 | Sentiment × funding cross-confirmation (crowded = sentiment + funding both extreme) | UNTESTED |
| SNT-04 | News-volume spike (titles/day surge) → volatility/event positioning | UNTESTED |
| FG-01 | Fear & Greed regime: extreme fear (<25) long-bias / extreme greed (>75) de-risk | UNTESTED |
| FG-02 | Fear & Greed change-velocity as contrarian signal | UNTESTED |
| MAC-01 | FRED rates/macro level changes → crypto risk-on/off (weekly rebalance) | UNTESTED |
| MAC-02 | Macro surprise direction (rates ↑/↓ regime) as book leverage modifier | UNTESTED |

### Two-leg arbitrage (CC) — market-neutral constructions never tested
| ID | strategy | status |
|---|---|---|
| CC-01 | **Delta-neutral cash-and-carry**: long spot + short perp when funding annualized > costs (harvest funding + basis convergence, zero delta). Needs two-leg P&L (spot daily = olaxbt panel, perp = binanceusdm intraday) | UNTESTED |
| CC-02 | **Basis convergence trade**: enter when basis z extreme, exit at convergence (two legs) | UNTESTED |

### Book-level overlays (REG/TM/RBT) — applied to the champion book, not standalone
| ID | strategy | status |
|---|---|---|
| REG-01 | Correlation/dispersion regime: avg pairwise 30d corr > threshold → halve book exposure | UNTESTED |
| REG-02 | 2-state HMM (trend/range) filter on the book — trade only in trend state | UNTESTED |
| REG-03 | Realized-vol percentile gate (30d RV > 80th pct → scale down) — ON/OFF, distinct from tested continuous vol-targeting | UNTESTED |
| TM-01 | ATR trailing stop on the book's trend entries (vs time-exit) | UNTESTED |
| TM-02 | Pyramiding — scale into winners on confirmation | UNTESTED |
| TM-03 | Partial profit-taking at k×risk | UNTESTED |
| RBT-01 | Rebalance timing alpha — rebalance sleeves at low-vol hours / post-funding timestamps | UNTESTED |

### Newly noted BLOCKED-DATA (don't spend time unless data appears)
- Open-interest history (no source) · US spot ETF flows (2024+, no source) · BTC halving cycle
  (n≈1-2 cycles — statistically unvalidatable; do not claim) · borrow/margin rates (no source) ·
  L2 order book, liquidations (already closed).

## C3. WEB-RESEARCH ADDITIONS (2026-10-30) — sourced from ICT/YouTube educators, Instagram-style price-action schools, quant Reddit, Wyckoff literature

### ICT / liquidity family (ICT) — the dominant retail educator methodology
| ID | strategy (exact rule) | source concept | status |
|---|---|---|---|
| ICT-01 | **Turtle Soup / liquidity-sweep fade** — price wicks through prior high/low (PDH/PDL/equal highs), closes back inside → fade the raid | fluxcharts, liquidityscan | UNTESTED |
| ICT-02 | **Judas Swing / Power-of-3 (AMD)** — fade the first 30-60min fake move after London/NY session open; trade the distribution leg | grandalgo ICT guide | UNTESTED |
| ICT-03 | **OTE (Optimal Trade Entry)** — after structure shift, enter on 62-79% fib retracement of the impulse leg | altrady/ICT glossary | UNTESTED |
| ICT-04 | **Breaker block retest** — failed order block (swept swing, reversed) retested from the other side → polarity-flip entry | liquidityscan | UNTESTED |
| ICT-05 | **Unicorn model** — breaker block ∩ FVG same price window (confluence zone, tight stop) | liquidityscan | UNTESTED |
| ICT-06 | **Silver bullet** — FVG entry inside the one-hour killzone window (London/NY macro hours) | innercircletrader | UNTESTED |
| ICT-07 | **Midnight-open anchor** (00:00 NY open) — bullish-bias dips below buy / bearish rallies above sell | liquidityscan | UNTESTED |
| ICT-08 | **SMT divergence** — BTC makes higher high while ETH fails (or vice versa) → intermarket reversal signal | ICT bias tools | UNTESTED |
| ICT-09 | **CISD confirmation** — candle closes back through the open of the last opposing candle run → shift-of-control entry | grandalgo | UNTESTED |

### Supply/demand + pattern additions (SD/CH) — Instagram/trading-school price action
| ID | strategy (exact rule) | source | status |
|---|---|---|---|
| SD-01 | **Supply/demand zones (RBR/DBR/Drop-Base-Rally)** — base candle zone + retest entry | ebc.com, maktradingschool | UNTESTED |
| SD-02 | **Golden zone** — supply/demand zone ∩ 50%/61.8% fib retracement confluence | protradingschool | UNTESTED |
| CH-06 | **Inside bar / NR7 narrow-range breakout** — narrowest range 7 days + inside bar → breakout with the break direction | unofficed NR7 | UNTESTED |
| CH-07 | **Fakey** — inside bar false breakout, fade the failure | price-action canon | UNTESTED |
| CH-08 | **Marubozu / strong-close continuation** — full-body candle → next-bar continuation | candle canon | UNTESTED |
| CH-09 | **RSI/MACD divergence** — price vs oscillator peak divergence → reversal | classic TA | UNTESTED |
| CH-10 | **Trendline / LinReg-channel break** — regression channel violation | classic TA | UNTESTED |
| CH-11 | **Renko / Point-and-Figure / Kagi / Three-Line Break** (alternative-bar signals) | classic TA | UNTESTED |

### Quant-Reddit additions (QNT)
| ID | strategy (exact rule) | source | status |
|---|---|---|---|
| QNT-01 | **Z-score trend state machine** — (c − EMA65)/σ65 > bull-filter long / < bear-filter cash | r/algotrading (Dual Signal Trend Sentinel) | UNTESTED |
| QNT-02 | **Mean-reversion eligibility gate** — Hurst < 0.4 + variance-ratio + lag-autocorrelation pre-screen per asset before running MR signals | r/algotrading | UNTESTED |
| QNT-03 | **BTC-ETH 30d correlation regime gate for MR** — skip mean-reversion when market moves together (reported SR 1.86→2.13 in one thread) | r/algotrading | UNTESTED |

### Wyckoff units (WCK) — simplified rule forms (full method is untestable as a whole)
| ID | strategy (exact rule) | source | status |
|---|---|---|---|
| WCK-01 | **Spring / UTAD fade** — range-break on LIGHT volume, recovery within 1-3 bars → fade back into range | tradingwyckoff, denntech | UNTESTED |
| WCK-02 | **SOS/LPS continuation** — sign-of-strength bar on rising volume + light-volume pullback (LPS) → trend entry | capital.com | UNTESTED |

### Anomaly additions (ANM) — cross-sectional finance anomalies never tested here
| ID | strategy | status |
|---|---|---|
| ANM-01 | **52-week-high proximity momentum** — proximity to 52w high predicts continuation (published equity anomaly) | UNTESTED |
| ANM-02 | **MAX/lottery effect** — coins with extreme max daily return in past month underperform (short bias) / low-MAX outperform | UNTESTED |

### FINAL SWEEP ADDITIONS (2026-10-30, last pass)
| ID | strategy (exact rule) | why it was still missing | status |
|---|---|---|---|
| CH-12 | **Harmonic patterns** — Gartley/butterfly/bat exact fib-ratio reversal formations (XABCD) | fib-confluence (SD-02) != harmonic pattern detectors | UNTESTED |
| CH-13 | **Elliott wave simplified** — trade only rule-formable wave-3 impulse continuation (labeled wave counts are untestable) | pattern canon had no wave unit | UNTESTED |
| VP-22 | **VWAP bands** — fade to / ride along +/-1sd/2sd session-VWAP bands | aVWAP (VP-10) is anchor-based; bands are a distinct rule | UNTESTED |
| HLD-01 | **Holiday / thin-calendar drift** — pre-holiday drift + first-day-after-holiday reversal | SS-17 covers only Fri/Sun; holidays were never listed | UNTESTED |
| END-01 | **Ensemble harvest (meta-unit)** — after one-by-one validation, blend ALL placebo-passing units into Book R4 with blend placebo certification | the plan had no step connecting validated units to the book | UNTESTED |
| END-02 | **Regime dispatch (meta-unit)** — route validated units by state (trend regime -> trend units, range -> MR units), CPCV-validated | regime-conditional use of units was implicit only | UNTESTED |

### DEEP-PASS ADDITIONS (2026-10-30, category-by-category walk)
| ID | strategy (exact rule) | category | status |
|---|---|---|---|
| CH-14 | **Flags & pennants** — tight continuation wedge after impulse; trade measured-move breakout | chart patterns | UNTESTED |
| CH-15 | **Cup & handle** (incl. rounded bottom) — trade handle breakout | chart patterns | UNTESTED |
| CH-16 | **Head & shoulders** (incl. inverse) — neckline break entry | chart patterns | UNTESTED |
| CH-17 | **Triangles** — ascending/descending/symmetric breakout with the trend | chart patterns | UNTESTED |
| CH-18 | **Morning / evening star** (3-bar reversal) | candles | UNTESTED |
| CH-19 | **Three white soldiers / three black crows** (3-bar continuation) | candles | UNTESTED |
| LV-01 | **Round-number levels** — x000/x500 psychological magnet & fade (documented intraday effect) | levels | UNTESTED |
| ANM-03 | **Streak effects** — k consecutive up/down days → continuation or exhaustion (test both signs) | anomalies | UNTESTED |
| TM-04 | **Chandelier exit** (ATR-based trailing from highest high) vs time-hold | exits | UNTESTED |
| TM-05 | **Time-stop exit** — flat after N bars regardless of P&L | exits | UNTESTED |
| RBT-02 | **Threshold-band rebalancing** (only trade when weight drifts > x%) vs calendar rebalance | portfolio | UNTESTED |
| I-04b | **MVO / ERC / HRP sleeve weighting** (Markowitz mean-variance, equal-risk-contribution, hierarchical risk parity — distinct math from inv-vol) | portfolio | UNTESTED |
| IV-01 | **Options IV term-structure slope** (front vs back expiry IV) as vol signal — IF deribit snapshots carry multiple expiries (data-check first) | options probe | UNTESTED |
| QNT-04 | **Kaufman efficiency-ratio regime filter** (ER = |net move|/sum|moves|; trade trend only when ER high) | filters | UNTESTED |
| IND-01 | **Bill Williams Alligator + fractals** (the one classic indicator never in the EXP-046 adopted zoo) | indicator zoo | UNTESTED |

**COMPLETENESS STATEMENT (v2, 2026-10-30, revised after 3 passes found more):** a prior "CLOSED"
claim was WRONG twice (VSA methodology + 6 zoo gaps + calendar layer still surfaced). The standing
rule: anything further found in the wild is one of (a) recombination of listed units (END-01/02 job),
(b) data-blocked (listed), (c) discretionary method (only rule-formable units listed), or (d) ANOTHER
named methodology / zoo gap / calendar effect — which must be ADDED as its own unit, not waved away.
The list stays open until one-by-one validation begins.

### METHODOLOGY-PASS ADDITIONS (2026-10-30, named-methodology + calendar + zoo-gap walk)
**VSA — Tom Williams Volume Spread Analysis (full quantified bar methodology, was entirely missing)**
| ID | strategy (exact rule) | status |
|---|---|---|
| VSA-01 | **No-demand / no-supply bars** — narrow spread (<0.6xATR20) + low volume (<0.7xV30) + close position; fade weak legs | UNTESTED |
| VSA-02 | **Stopping volume & climax** — ultra-high volume (>2xV30) bar closing off its extreme at a trend end -> reversal | UNTESTED |
| VSA-03 | **Upthrust + effort-vs-result** — wide bar spikes past resistance then closes low on high volume -> short; effort-without-result = distribution warning | UNTESTED |

**Named systems & patterns**
| ID | strategy | status |
|---|---|---|
| DAR-01 | **Darvas box breakout** — new-high box definition, trade box breaks with volume confirm | UNTESTED |
| AMT-01 | **Auction Market Theory: excess vs poor extremes** — fade poor highs/lows (thin retest), follow excess (single prints) | UNTESTED |
| ICT-10 | **Quasimodo (over-under) reversal** — ICT head-shoulders variant with aligned left shoulder | UNTESTED |
| CH-20 | **Tweezer tops/bottoms** (equal-extreme 2-bar reversal) | UNTESTED |
| CH-21 | **Joe Ross 1-2-3 reversal + Ross hook** (named breakout-continuation system) | UNTESTED |
| CH-22 | **Wolfe waves** (5-point channel reversal) | UNTESTED |

**Classic indicator zoo gaps (none of these ever appeared in EXP-022..046 or EXP-046 adopted)**
| ID | strategy | status |
|---|---|---|
| IND-02 | **Awesome Oscillator** (zero-line cross + saucer) | UNTESTED |
| IND-03 | **Money Flow Index (MFI)** — volume-weighted RSI | UNTESTED |
| IND-04 | **Chaikin Money Flow + A/D line** | UNTESTED |
| IND-05 | **TRIX** (triple-smoothed momentum) | UNTESTED |
| IND-06 | **Ultimate Oscillator** (multi-timeframe momentum) | UNTESTED |
| IND-07 | **Elder Ray** (bull power/bear power) | UNTESTED |

**Calendar layer (literature is CONTESTED — test with lockbox, do not assume either way)**
| ID | strategy | evidence | status |
|---|---|---|---|
| SEAS-01 | **Month-of-year seasonality** (Uptober/November bias) | Oct mean +19.9%/median +14.7% 2013-25 [geekmetaverse]; Mueller 2024 calls it artifact | UNTESTED |
| SEAS-02 | **Halloween effect** (Oct 31-Apr 30 long) | Emerald 2026: strategy beats hold 2018-24 for 4/5 coins; GARCH study finds nothing | UNTESTED |
| SS-23 | **Pre-FOMC drift** (long into scheduled FOMC days) | documented equity anomaly; crypto untested | UNTESTED |

**Statistical + macro (FRED columns CONFIRMED: vix, us_10y_yield_pct, effective_fed_funds_pct, trade_weighted_usd_index, us_high_yield_oas_pct, sp500_index, wti_crude)**
| ID | strategy | status |
|---|---|---|
| QNT-05 | **Intraday jump effects** — post-jump drift vs reversal after large 15m jumps | UNTESTED |
| MAC-03 | **VIX & HY credit-spread (OAS) risk regime** -> book de-risk/risk-on | UNTESTED |
| MAC-04 | **DXY (trade-weighted USD) + 10y yield direction** -> BTC inverse positioning | UNTESTED |
| SNT-05 | **Keyword event studies** from daily_titles.jsonl (ETF/hack/SEC keyword days) | UNTESTED |

**NOTE:** FRED also carries sp500_index (feeds I-08 lead-lag with real data). No M2/gold in the file.

### EDUCATOR-SYSTEMS PASS (2026-10-30, named-author methodologies)
| ID | strategy (exact rule) | source | status |
|---|---|---|---|
| MNV-01 | **Minervini VCP** — progressive contractions (e.g. 18%->12%->6%, ATR shrinks to ~1/3 of 50d avg), volume dry-up, breakout of final pivot on +40-50% volume; stop under last contraction low | tradingsim, finwiz | UNTESTED |
| MNV-02 | **Minervini Trend Template (SEPA filter)** — >150d & >200d MA (200 rising), near 52w high, strong relative strength -> market-direction gate for breakout units | clearcurve, finwiz | UNTESTED |
| STR-01 | **The Strat (Rob Smith)** — bar taxonomy 1(inside)/2(directional 2U/2D)/3(outside) + combos (2-1-2, 3-1-2, 2-2, 1-2-2) + FTFC (full timeframe continuity) gate | luxalgo, forexmt4indicators | UNTESTED |
| WST-01 | **Weinstein stage analysis** — 30-week MA slope + price position -> stage 1-4 regime; trade stage 2/4 only | classic named system | UNTESTED |
| RSH-01 | **Raschke Holy Grail** — strong trend (ADX>30) first pullback to 20-MA -> continuation entry | Linda Raschke canon | UNTESTED |
| BRO-01 | **Al Brooks second entry / H2-L2** — second failed attempt at a signal bar level -> entry with trend | Al Brooks price action | UNTESTED |
| BRO-02 | **Brooks wedge (3-push) reversal + measured-move target** | Al Brooks | UNTESTED |
| ELD-01 | **Elder Triple Screen** — weekly trend (MACD-hist) x daily oscillator x intraday trigger | Alexander Elder | UNTESTED |
| ANM-04 | **Idiosyncratic-volatility effect** — low-idio-vol coins outperform (cross-sectional) | equity anomaly | UNTESTED |
| CAR-03 | **Funding & basis momentum** (delta signals: acceleration of funding/basis, not level) | crypto-native variant | UNTESTED |
| TM-06 | **Fib-extension profit targets** (1.618/2.618 measured moves) vs fixed exits | retail canon | UNTESTED |
| GRD-02 | **Laddered DCA profit-ladder** — staged buys below last buy + sell ladder above average cost | r/algotrading live systems | UNTESTED |
| EXE-02 | **Fee-tier optimization** — BNB fee discount (25%), maker rebates, referral tiers = pure cost ROI | venue mechanics | UNTESTED |

**BLOCKED-DATA register additions:** on-chain metric family (MVRV/NUPL/SOPR/Puell Multiple/hash ribbons) — no dataset in reach; options max-pain/GEX — needs option OI history.

### TRADINGVIEW-SCRIPT + SIZING-SYSTEMS PASS (2026-10-30)
| ID | strategy (exact rule) | source | status |
|---|---|---|---|
| IND-10 | **Nadaraya-Watson envelope** (kernel-regression bands, mean reversion) — MUST implement non-repainting mode; sources warn stock backtests show repaint artifacts (bug-gate Pillar 1!) | quantum-algo, masquant | UNTESTED |
| IND-11 | **QQE Mod** (smoothed RSI + volatility bands momentum cross) | abovethegreenline | UNTESTED |
| IND-12 | **GMMA (Guppy multiple moving averages)** — short/long ribbon compression & expansion | TradingView MA strategies | UNTESTED |
| IND-13 | **MA envelopes** (fixed %-bands fade/continuation) | TradingView MA strategies | UNTESTED |
| IND-14 | **Coppock curve** (long-horizon smoothed momentum) | classic named indicator | UNTESTED |
| ELD-02 | **Elder Impulse System** (MACD-hist + EMA-slope bar-color rules as entry/exit filter) | Alexander Elder | UNTESTED |
| RSK-01 | **Optimal f / fixed-ratio sizing** (Ralph Vince) vs fixed-fractional — sizing-system comparison on the book | named sizing method | UNTESTED |
| RSK-02 | **CPPI** (constant-proportion portfolio insurance: floor + multiplier exposure) on book equity | named risk method | UNTESTED |
| CAR-04 | **Funding-snip** — hold only around favorable funding timestamps (8h cycle), flat otherwise | crypto-native execution | UNTESTED |
| ANM-05 | **Betting-against-beta** (low-beta tilt cross-sectional) | equity anomaly | UNTESTED |
| ANM-06 | **Amihud illiquidity premium** | equity anomaly | UNTESTED |
| CH-23 | **3-bar play / hikkake** (named inside-bar failure & continuation variants) | Williams/Capre canon | UNTESTED |
| EXE-03 | **Prop-firm constraint envelope** — trade sizing/holding adapted to FTMO/Hyro-style daily-LL & profit-target rules (deployment realism for the live path) | live-trading mechanics | UNTESTED |

Edits: CH-11 now includes Kagi / Three-Line Break; SS-21 now includes NFP (first Friday). Blocked register += single-stock crypto proxies (MSTR/COIN) — no data.

### TAIL-CONSOLIDATION PASS (2026-10-30) — folk calendar, encyclopedia tails, named tools, meta-search
| ID | strategy (exact rule) | source | status |
|---|---|---|---|
| SEAS-03 | **Lunar New Year / China-holiday effect** (crypto folk seasonality: pre-CNY selling, post-CNY re-entry) | crypto folklore; test not assume | UNTESTED |
| MAC-05 | **Term-spread regime** (10y minus fed-funds, computable from FRED columns) — inverted/spread state -> risk posture | macro canon | UNTESTED |
| IND-15 | **Secondary-oscillator batch** (ONE unit, batch-tested): SMI, RVI, KST, QStick, Chande, Vortex, Force Index | named zoo tail | UNTESTED |
| CH-24 | **Bulkowski encyclopedia batch** (ONE unit): bump-and-run reversal, horn pattern, island reversal | Bulkowski encyclopedia | UNTESTED |
| CH-25 | **Andrews pitchfork** (median-line channel reaction/continuation) | named tool system | UNTESTED |
| QNT-06 | **Genetic-programming rule discovery** — symbolic search over rule space WITH CPCV + search-level nulls (method: finds candidates for the queue; claims only after END-01 gates) | quant practice | UNTESTED |
| PRT-01 | **Equal-weight top-15 basket vs BTC** — monthly rebalance premium (testable; cap-weighted needs caps = blocked) | index construction | UNTESTED |

**Precision edits:** VP-20 += Woodie/DeMark pivot variants · ICT-04 += mitigation block · ICT-07 += NWOG/NDOG (new week/day opening gaps) · SS-20 += quarterly major expiry distinction · MAC-04 += WTI impulse (inflation proxy).

**TAIL POLICY:** endless secondary oscillators and encyclopedia pattern variants are absorbed into BATCH units (IND-15, CH-24) tested as one validation unit each — not infinite single rows.

**METHOD NOTE (from quant Reddit):** adopt **CPCV (combinatorial purged cross-validation)** for any future walk-forward instead of plain k-fold — purge overlapping labels, 15 folds. Also: feed-latency robustness checks before live.

## C. OTHER WAVES (unchanged inventory)

### Wave 1 — direct book upgrades (DONE)
| ID | result | placebo | verdict |
|---|---|---|---|
| I-01 squeeze-family expansion | pair slot upgrade: +2.46%/mo SR 1.77 DD 14.5 | slot **PASS 100th pct** | **→ Book R3.1** |
| I-02 EXP-044 tf-winner blends | claims UNVERIFIED on reimpl (+0.32/−0.66) | blend 67pct FAIL | FAIL |
| I-03 basis-MR sleeve | +0.12%/mo DD 2.2 | blend 43pct FAIL | FAIL |
| I-04 book engineering | inv-vol SR 1.44; vol-scale 1.54 | — | dominated |
| I-05 12h/common/EW squeeze | SR ≤ 0.5, DD 90+ | — | dead |

### Wave 2 — mechanisms (queued after VP/SS validation)
| ID | idea | status |
|---|---|---|
| I-07 | **Maker-fee regime (3bp post-only)**: maker-fill mean-reversion 15m/1h + maker-entry execution for the book | UNTESTED — now also gates final closure of all 15m VP/SS rules |
| I-08 | EQ→crypto lead-lag + alt-season breadth | UNTESTED |
| I-09 | Extreme-funding fade (event) | UNTESTED |
| I-10 | DeFi TVL regime overlay | UNTESTED |
| I-11 | Cross-exchange basis MR (blocked earlier: no data — recheck) | BLOCKED-DATA |
| I-12 | Grid/range bot at maker fees (4h/1h) | UNTESTED |
| I-13 | Multi-timeframe confirmation (1d gate × 4h trigger composite) | UNTESTED |
| I-14 | Walk-forward sleeve-weight adaptation | UNTESTED |
| I-16 | 3x-funding-day avoidance | UNTESTED |
| I-17 | Drawdown parking in stablecoin yield | UNTESTED |

### Wave 4 — thin-data probes
| ID | idea | status |
|---|---|---|
| I-19 | Options IV-RV carry (deribit snapshots) | UNTESTED |
| I-20 | Options skew probe | UNTESTED |

### Wave 5 — truth & robustness
| ID | idea | status |
|---|---|---|
| I-21 | 2026 lockbox audit (re-derive champions on 2021-25, reveal 2026) | UNTESTED |
| I-22 | Sleeve-level DD de-risk overlay | UNTESTED |
| I-23 | ETH/BTC ratio regime rotation | UNTESTED |
| I-24 | Short-vol sleeve conditional add | UNTESTED |

### Closed (pre-checked, don't spend time)
- Liquidation cascades (no data) · L2 microstructure (no data) · small-cap rotation (costs kill) ·
  prediction markets / copy trading (out of scope).

---

## ROI TRACKER (live — one row filled per validation unit)

Baseline: R3.1 ×2 = +4.73%/mo SR 1.77 DD 27.4.

| unit | result | placebo | book impact | champion? |
|---|---|---|---|---|
| I-01 | +2.46%/mo SR 1.77 slot upgrade | 100th pct | **→ R3.1** | YES |
| I-02 | unverified reimpl | 67pct | none | no |
| I-03 | +0.12%/mo | 43pct | none | no |
| I-04 | dominated | — | none | no |
| I-05 | dead | — | none | no |
| VP-01/03/04/09/18, SS-01/04/06/09/10/13 | pre-screen FAIL (EXP-048) | — | none | no |
| VP-02,05,06,07,08,10,11,12,13,14,15,16,17,19,20,21 · VPSS-01..03 · SS-02,03,05,07,08,11,12,14,15,16,17,18,19,20,21,22 · CH-01..11 · SD-01..02 · ICT-01..09 · QNT-01..03 · WCK-01..02 · ANM-01..02 · SNT-01..04 · FG-01..02 · MAC-01..02 · CC-01..02 · REG-01..03 · TM-01..03 · RBT-01 | **UNTESTED — validate one by one on user's go (~155 units)** | | | |
| I-07..I-24 (others) | untested | | | |

**Cumulative best: R3.1 ×2 +4.73%/mo SR 1.77 (×3 +6.80%/mo). All-years-positive: R3 ×2 +4.52/minYr +0.31.**
