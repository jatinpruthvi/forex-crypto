# Strategy Redesign — Round 1 Research (EXP-021)

**Status: SELECTION-ADJUSTED — forward paper validation required before any ROI claim.**
All results below were produced through the audited fill model (`execute_shared_pool_sim`:
bar-start stop snapshot, SL-first ambiguous bars, net-trade PnL, taker fees on stops and
pyramid adds) on real data. Baseline reproduction of EXP-020 was exact
(138 trades, WR 18.8%, PF 0.58, −13.59%/mo, DD 62.96%).

## 1. Diagnosis — where the old signal lost

Decomposition of every closed trade, bench 4h panel (8 pairs, 2022-10..2023-04) and
crypto 1d panel (21 coins, 2020-07..2023-04). Both panels agree:

| Bucket | Bench 4h | Crypto 1d |
|---|---|---|
| TP1 reached (+1.8×ATR) | **+$449 / 56t / WR 46%** | **+$1,325 / 68t / WR 50%** |
| TP1 never reached | **−$989 / 82t / WR 0.0%** | **−$1,302 / 74t / WR 0.0%** |
| Hold 1–3 bars | −$330 / WR 3.4% | −$527 / WR 5.7% |
| Hold 31+ bars | +$234 / WR 60% | +$315 / WR 40% |

**Not one trade that failed to reach TP1 closed green, on either panel.** The exit
system cannot rescue a bad entry; the entire edge question is *entry quality*
(raise the TP1-reach rate from ~40% toward 55%+) or *exit restructuring*
(cut doomed trades before the full 1.5×ATR stop). Side and pair effects are
panel-dependent (no blanket "drop shorts" fix).

## 2. Variant research (14 fixed hypotheses, chronological OOS)

Family summary (crypto 1d late-OOS window, risk 1.5%):

| Variant | OOS %/mo | PF | DD% | Notes |
|---|---|---|---|---|
| Baseline | +0.11 (full) | 1.01 | 38.9 | EXP-020 |
| MOMO_QUALITY (strong-close filter) | **+2.75** | 1.58 | 22.0 | early window −3.32 |
| Q_TIGHT_TP (quality + TP1 1.4 ATR) | **+3.43** | 1.70 | 25.0 | early −0.81, bench −2.85 |
| Q_TS8 (quality + 8-bar time stop) | +1.88 | 1.31 | 28.8 | full +2.52, early +4.48 |
| Q_TS12 (quality + 12-bar time stop) | +1.77 | 1.27 | 25.3 | flat elsewhere |
| MR_ONLY / MR_DEEP | negative | <0.7 | — | mean reversion dead |
| Q_MACRO_SIDE | +1.01 | 1.24 | 25.5 | **0/3 folds — dead** |
| All variants on forex H4 | catastrophic | 0.22–0.69 | — | family is crypto-only viable |

## 3. Risk ladder + fold stability

DD scales with size. At **risk 0.5%**, three variants pass the pre-registered gate
(OOS monthly > 0, PF > 1.05, DD < 15%) on the OOS window:

| Variant | OOS | Full-period |
|---|---|---|
| Q_TIGHT_TP r=0.5 | +1.17%/mo, PF 1.51, **DD 11.6%** | +0.80%/mo, PF 1.35, DD 16.3% |
| Q_TS8 r=0.5 | +0.62%/mo, PF 1.22, DD 13.0% | +1.23%/mo, PF 1.43, DD 17.8% |
| Q_TS12 r=0.5 | +0.68%/mo, PF 1.23, DD 11.9% | +0.57%/mo, PF 1.21, DD 16.9% |

Rolling 3-fold stability (risk 1.0): Q_TIGHT_TP 2/3, Q_TS8 2/3, Q_TS12 2/3.
**Every variant fails fold 2** (2021 blow-off top + May crash) — the regime
robustness problem is unsolved.

## 4. Honest conclusions

1. The old signal's failure is **diagnosed precisely**: it is an entry-quality
   problem (no-TP1 trades never win), not fees, not sides, not one bad pair.
2. Entry quality filters (strong close, tighter TP1, time stops) produce a
   **real but regime-fragile edge**: OOS PF 1.2–1.7, positive on 2 of 3 folds.
3. At prop-firm-compliant risk the honest expectation is **~0.6–1.2%/mo**, with
   full-period DD 16–18% marginally above the 15% crypto constraint. This is
   far from the 25%/mo target — which remains unreachable without a stronger,
   regime-robust edge.
4. **Selection-adjustment caveat**: the 1d panel was examined across three
   research rounds; the numbers above are in-sample-guided and MUST be confirmed
   by forward paper validation on fresh data before any ROI claim or live use.

## 5. Personal-account risk ladder (EXP-022 — no prop-firm gate)

Risks 1.5→5%/trade (lev 2.0, 2 slots, dd-throttle ON), crypto 1d panel:

| Risk | Q_TS8 full-period | Q_TIGHT_TP OOS half | Fold range (Q_TS8 r2.5) |
|---|---|---|---|
| 1.5% | +2.5%/mo, DD 47% | +3.4%/mo, DD 25% | — |
| 2.5% | +3.6%/mo, DD 66% | +4.8%/mo, DD 36% | −2.6% .. +13.5%/mo |
| 3.0% | +3.9%/mo, DD 72% | +5.1%/mo, DD 42% | — |
| 4.0% | +4.2%/mo, DD 83% | +6.1%/mo, DD 51% | −4.6% .. +18.5%/mo |
| 5.0% | +4.2%/mo, DD 89% | +6.6%/mo, DD 59% | diminishing |

Key facts:
- **Raising risk is sublinear for ROI, superlinear for DD** — past ~3% risk the
  monthly barely improves while DD approaches ruin. Sweet spot: risk 2–3%.
- **Account size**: $323 / $1,000 / $5,000 give identical percentages through
  the Hyperliquid lot gate. **$25 is NOT viable** (lot-gate distortion, −1.3%/mo).
- The 2022-10..2023-04 chop window loses at every risk level — losing for months
  is part of the honest expectation.
- Expectation on personal capital: **~2–4%/mo at risk 2–3%, with 55–70% peak
  drawdowns**; best-regime months double-digit; still selection-adjusted.

## 6. Next steps

1. Volatility-targeted position sizing (rescue fold-2 + DD margin).
2. Regime gate: skip blow-off/chop phases (fold-2 killer).
3. Forward paper validation of **Q_TIGHT_TP @ risk 0.5%** (bench config:
   2 slots, lev 2.0, dd-throttle 8%) on fresh candles as they arrive.

Artifacts: `scripts/redesign_lab.py` (diagnostics + variant harness),
`reports/redesign_lab_results.json`, `reports/redesign_round2_results.json`,
ledger entry EXP-021.


---

## 6. EXP-023 — Strategy-Type Hunt for Optimum ROI:Drawdown (2026-10-28)

**Trigger**: user — "Peak drawdown is 10 times then ROI... check different type of strategy... check again
and again until we get optimum... think out of the box, think only on trade." The slot family's DD/Mo ratio
(11-23x) was rejected; the goal became an archetype with DD/Mo <= ~5-10 and Calmar >= 1.

**Method** (`scripts/strategy_hunt.py`): 13 genuinely different portfolio archetypes on the 21-coin 1d panel
(2020-07→2023-04, 10bp/side turnover): cross-sectional momentum / trend / mean-reversion / low-vol / tail,
long-short, BTC time-series momentum, RSI2 mean-reversion, dip-buying (RSI3<15 & >MA100), regime-gated
variants (BTC vs MA), and blends. Then a 37-config refine grid (gate MA x K x lookback x blend mix) with a
PRE-REGISTERED selection rule (max worst-fold monthly, s.t. full DD/Mo<=10, Calmar>=1.2, maxDD<=35%), a
passive gated equal-weight baseline, and leave-one-fold-out (LOFO) anti-curve-fit validation.

### Result — the user criterion is met by the gated-rotation + dip-buying family

| config (full period) | %/mo | maxDD | Calmar | DD/Mo | folds (3) |
|---|---|---|---|---|---|
| **BLEND ma150 rot50/dip50** | **+6.66** | **29.8%** | **3.92** | **4.5** | +18.2 / +0.02 / +0.24 |
| GATED_ROT ma150 K5 lb90 | +11.63 | 32.8% | 8.37 | 2.8 | +31.8 / -0.80 / +2.44 |
| GATED_ROT ma150 K7 lb40 | +9.96 | 34.9% | 6.08 | 3.5 | +26.7 / -0.19 / +1.72 |
| passive gated equal-weight | +7.52 | 42.2% | 3.28 | 5.6 | +21.1 / -1.60 / +1.65 |
| (old slot family Q_TS8) | +3.08 | 54-66% | 0.7 | 11-23 | +13.5 / -2.6 / +2.9 |

Every ma150 blend variant qualifies (worst-fold 0 +/- 0.2) — the FAMILY is robust, not one lucky row. Active
selection beats the passive gated baseline on return AND drawdown. **MA250 gates are a trap** (they miss the
rallies and still catch the crashes). Forex panel: no edge in any archetype (best B TSMOM_VOL +0.36%/mo).

**What the strategy IS** (plain words): stay in cash while BTC trades below its 150-day MA; in risk-on,
hold a 50/50 blend of (a) the 4-7 strongest 60-day-momentum coins, inverse-vol weighted, rotated weekly,
and (b) limit-buying panic dips (RSI3<15 above the long MA) with quick 5-day-high exits.

### Honesty (mandatory reading)

1. **Selection-adjusted**: configs were chosen on these folds; the reported numbers overstate forward
   expectations. LOFO held-out folds: **+29.9 / -0.80 / -1.35 %/mo** (bull / chop / bear). The real edge is
   alt-bull-regime concentration; chop and bear are roughly flat to slightly negative. Per-regime
   expectations: bull +15-30%/mo, chop ~0, bear -1..+2%/mo.
2. **Fold 2 (2021 blow-off/crash) is the weak regime for every archetype tested** (slot family and portfolio
   family alike). The gate + dip blend reduces it to ~0 but does not turn it positive.
3. Worst months: -17 to -19% (blends), -35% (pure rotation). DD 30-35% remains the price of admission.
4. Forward paper validation (3 months live-sim) is REQUIRED before any capital allocation. Do not size up on
   backtest numbers alone.

**Verdict vs user criterion**: old family DD/Mo 11-23 ("10x ROI" complaint) → new family **DD/Mo 2.8-4.5**,
Calmar 3.9-8.4, no losing fold in the blend. This is the optimum found across 13 archetypes + 37 configs
with honest fold and LOFO reporting. Next step: wire the family into the paper-trading harness.


---

## 7. EXP-024 — Hunt Rounds 4-5: Better Than the Round-3 Champion (2026-10-28)

**Trigger**: user asked to keep hunting for a better strategy and to SAVE all performance results for
later selection. Saved cumulatively in `reports/strategy_leaderboard.json` (48 entries, all rounds).

**Round 4** (18 new mechanics): portfolio vol-targeting, crash filters, per-asset absolute-momentum
filters, Donchian state systems, ensemble voting, weekly/golden-cross gates, dip v3. **Round 5**
(14 configs): GATED_ROT family grid over abs-mom lookback x vol-target x K x lb. Same pre-registered
rule (max worst-fold monthly s.t. DD/Mo<=10, Calmar>=1.2, maxDD<=35%).

### Leaderboard (top of 48 saved entries, crypto 1d 21c, 10bp/turnover side)

| rank | config | %/mo | maxDD | Calmar | DD/Mo | folds |
|---|---|---|---|---|---|---|
| 1 | **ABS90_GROT K5lb90** | **+11.68** | **25.1%** | **11.03** | **2.1** | +31.8 / -0.32 / +2.04 |
| 2 | ABS60_GROT K5lb90 | +11.43 | 29.7% | 8.97 | 2.6 | +32.2 / -0.99 / +1.78 |
| 3 | ABS60_GROT K5lb40 (all folds +) | +10.86 | 31.9% | 7.67 | 2.9 | +29.9 / +0.24 / +0.92 |
| 4 | VOL_GROT 35% (all folds +) | +4.31 | 20.9% | 3.16 | 4.8 | +8.9 / +0.60 / +2.33 |
| 5 | VOL_GROT 30% (all folds +) | +3.86 | 19.5% | 2.94 | 5.1 | +7.9 / +0.59 / +2.09 |
| - | (Round-3 champion BLEND ma150) | +6.66 | 29.8% | 3.92 | 4.5 | +18.2 / +0.02 / +0.24 |

**Two genuine discoveries**: (1) the **absolute-momentum filter** (only hold coins with positive
trailing 90d return) cuts DD 32.8->25.1% while keeping bull returns (Calmar 8.4->11.0); (2)
**vol-targeting** normalizes risk across regimes (every VOL_GROT config positive in all 3 folds).

**Failed mechanics (negative knowledge, saved in leaderboard)**: crash filters (whipsaw), Donchian
state systems (DD 64-85%), golden-cross gate (Calmar 1.6), dip v3 (over-filtered), stacking all
filters into SUPER_BLEND (Calmar 0.5 — filters fight each other).

### Honesty (same as section 6)
Selection-adjusted; edge concentrated in alt-bull regimes (LOFO held-out: bull +7.9..+31.8 with
DD 19-33%, chop ~-1..0, bear ~-1.4..+0); fold-2 (2021 blow-off) remains the weak regime though
smaller; 3-month forward paper validation required before capital. `reports/strategy_leaderboard.json`
`selection_guide` has the saved picks: best_calmar (ABS90_GROT) and best_all_folds_positive
(ABS60_GROT K5lb40), plus the VOL_GROT tier as the low-risk option (+3-4%/mo at 17-21% DD).


---

## 8. EXP-025 — Nuclear-Explosion Tree Search (2026-10-28)

**Method** (user: "think like nuclear explosion in idea where one idea become 2, 2 become 4... visit each
node of the nuclear path"): an explicit strategy tree, every node validated on the real 21-coin 1d panel
(3 chronological folds + full period, 10bp/turnover) and saved with its tree path to
`reports/strategy_leaderboard.json` (96 entries). No production code until the tree was fully visited.

- **L1 signal cores x6**: momentum, momentum-acceleration, trend-slope, dual-timeframe, leader-lag,
  quality-momentum. Discovery: all viable, but daily-rebalance versions are fee-inferior to weekly.
- **L2 gates x15** (MA150 / MA100 / weekly-MA10 / golden-cross / 2-of-3 ensemble): **MA100 > MA150**;
  golden-cross consistently bad (Calmar 0.8-1.1).
- **L3 overlays x9**: abs-mom, vol-target, both, rank-proportional. Discovery: rank-prop and quality
  scores keep all folds positive at high Calmar.
- **L4 mutations x4**: regime-switch (works, Calmar 3.9), impulse-laggard (fails), strongest-only
  (boom-bust, folds -8.2/-1.7), mr-trend-split (Calmar 2.0).
- **L5 combinations x4**: tree discoveries merged onto the champion family.
- **L6**: neighbor-plateau check x7 + final LOFO x3.

### Champion: L5/C1 — ABS90_GROT + MA100 gate

BTC>**MA100** regime gate; in risk-on hold top-5 coins by 90-day momentum (skip=5), inverse-vol
weights, weekly rebalance, **90-day absolute-momentum filter** (only hold coins with positive own
trend). Cash otherwise.

| scope | %/mo | maxDD | Calmar | DD/Mo | folds |
|---|---|---|---|---|---|
| full period | **+13.54** | **29.2%** | **12.28** | **2.2** | **+34.1 / +1.70 / +2.47 (ALL POSITIVE)** |
| LOFO held-out bull (fold1) | +34.11 | 23.4% | - | 0.7 | worstM -10.3 |
| LOFO held-out chop (fold2) | +0.75 | 33.0% | - | 44 | worstM -20.1 |
| LOFO held-out bear (fold3) | +2.47 | 23.8% | - | 9.6 | worstM -1.2 |

**First strategy in the program whose LOFO held-out returns are positive in all three regimes.**
Neighbor plateau: all 7 parameter neighbors (gate 85/115, lb 80/100, K 4/6) also all-fold-positive
(Calmar 5.2-12.3) — a broad plateau, not a lucky point. Runner-ups (saved in leaderboard):
L5/C2 quality-mom (+10.75, Calmar 7.29, ALLPOS), L5/C4 rank-prop (+10.22, Calmar 5.29, ALLPOS).

### Honesty
Few folds (3) and one market regime sequence (2020-23 bull->chop->bear); all searches share the same
panel, so selection-adjustment persists despite LOFO. Worst held-out month -20.1%. Forward paper
validation (3 months) remains required before capital. Realistic forward expectation: bull +15-30%/mo,
chop +0-2%, bear +0-3%, DD 25-35%.


---

## 9. EXP-026 — Dynamic-Strategy Hunt: Anti Bull-Hold, BFS+DFS, 100 Nodes (2026-10-28)

**Trigger**: user — "make sure our strategy is dynamic not like by an hold for the bull run in the past";
"use nuclear expansion... depth first search and breadth first search... validate at least 100 different
nodes." Pre-registered **DYNAMIC selection rule** before running: maximize worst-fold monthly subject to
all folds > -1%/mo, **non-bull avg (chop+bear) > 0**, **bull profit share < 0.8**, DD/Mo <= 10,
Calmar >= 1.2, maxDD <= 35%. This structurally rejects bull-hold strategies.

**Search** (100 validated nodes, real panel, saved to `reports/strategy_leaderboard.json`):
BFS L1 breadth x31 (LS momentum, regime switches, bear shorts, MR, vol dynamics, adaptive params,
11 reference configs) -> BFS L2 expansions -> DFS parameter descent x56 -> neighbor plateau x7 -> LOFO x3.

### The user's concern is CONFIRMED by the data

| config | %/mo | folds | bull share | verdict |
|---|---|---|---|---|
| old champion L5/C1 | +13.54 | +34.1/+1.7/+2.5 | **0.89** | FAILS dynamic rule = largely bull-hold |
| ABS90_GROT g150 | +11.68 | +31.8/-0.3/+2.0 | 0.95 | fails |
| **dynamic champion L2/03-T1** | **+3.95** | **+7.74/+0.97/+2.09** | **0.72** | **PASSES: chop and bear genuinely pay** |

**Dynamic champion = VOL_GROT 30% + hyst-gate**: weekly top-5 90d-momentum inverse-vol rotation gated
by BTC regime, **risk scaled to 30% annualized vol** (this is the dynamic part - exposure adapts to
market volatility), gate with **MA100 +-2% hysteresis** (no whipsaw). Full: +3.95%/mo, DD 19.5%,
Calmar 3.04, non-bull avg +1.53%/mo. **LOFO held-out: +7.74 / +0.41 / +2.09 %/mo (bull/chop/bear),
all positive, DD 10-20%**. Neighbor plateau: 5/7 DYN-OK (any vol target 20-40%, hysteresis optional).

**Negative knowledge (100 nodes of it, saved)**: every short-selling, mean-reversion, LS, and
regime-switching mechanic FAILED to pay in chop/bear on this panel (LS_MOM folds -2.2/-2.3, SWITCH3
bear -2.1, DUAL_TREND bear -2.2, BOLL_MR -3.2, VOL_BRK_LS -2.9...). The only genuine dynamic edge
source on this panel = **vol-targeting + regime gating of the momentum rotation**. Shorts of altcoins
in the 2022 bear still lost (bear-market rallies ripped them).

### The honest trade-off
Dynamic champion: +3.95%/mo, DD 19.5%, regime-balanced (bull share 0.72).
Bull-hold champion: +13.5%/mo, DD 29.2%, bull share 0.89.
Same mechanics core (momentum rotation); the difference is risk adaptation. Forward paper validation
required for both before capital. Worst dynamic month: -9.9%.


---

## 10. EXP-027 — Smart Money Concepts Hunt (2026-10-28)

**Trigger**: user — "hunt again for smart money concept using nuclear explosion method." ICT/SMC mechanics
implemented systematically on the real 21-coin daily OHLC panel, exploded BFS + DFS style, 164 distinct
validated nodes, all saved to `reports/strategy_leaderboard.json`. Same pre-registered DYNAMIC rule
(anti bull-hold) as EXP-026.

### What was tested (BFS breadth x22)
Fair value gaps (3-candle imbalance retests with fill/invalidation state machines), order blocks
(pre-displacement opposite candles), liquidity sweeps (stop-hunt fades of prior swing extremes), breaks of
structure, change of character, premium/discount dealing ranges, volume absorption, AMD weekly fake-outs,
confluence combos (BOS+OB, FVG+sweep, 2-of-3 votes) - long-only and long-short variants of each, plus
regime adaptations (gate/hyst/vol-target) and DFS parameter depth (hold x K x gap-lifetime).

### Champion: FVG_LS fresh-gap retests — the most dynamic strategy in the program

| config | %/mo | maxDD | Calmar | folds | worst-fold | non-bull | bull share |
|---|---|---|---|---|---|---|---|
| **FVG_LS age15 h3** | **+6.38** | **28.2%** | **3.91** | **+7.6/+5.7/+5.7** | **+5.70** | **+5.71** | **0.40** |
| FVG_LS age10 h3 | +6.88 | 26.2% | 4.67 | +9.6/+5.3/+5.4 | +5.25 | +5.31 | 0.47 |
| FVG_LS age20 h3 | +6.35 | 30.9% | 3.54 | +6.9/+6.4/+5.6 | +5.59 | +5.97 | 0.37 |
| (EXP-026 dynamic champ) | +3.95 | 19.5% | 3.04 | +7.7/+1.0/+2.1 | +0.97 | +1.53 | 0.72 |
| (old bull-hold champ) | +13.54 | 29.2% | 12.28 | +34.1/+1.7/+2.5 | +1.70 | +2.08 | 0.89 |

**Mechanic**: when price returns into a FRESH unfilled fair-value gap (<= ~2-4 weeks old) - the 3-candle
imbalance zone where "smart money" is theorized to rebalance - take the position in the gap's direction
(long into bullish gaps, SHORT into bearish gaps), inverse-vol across all active setups, hold ~3 bars.
The SHORT side of fresh gaps is the true dynamic engine: it made +5.7%/mo in the 2021 chop fold and
+5.7%/mo in the 2022 bear fold.

**Plateau**: gap lifetimes 10-30 all pass (Calmar 3.3-4.7, bull share 0.37-0.47); hold 2-5 x K 0-5 combos
pass. LOFO (pre-age discovery): +8.48/+1.84/+3.23 held-out, all positive.

### SMC-specific negative knowledge (saved)
Liquidity sweeps (the signature ICT stop-hunt) LOSE on daily crypto (-5.4%/mo long side); order blocks
weak and bull-heavy; CHoCH fails; BOS continuation is a bull-hold (bull share 2.0); premium/discount ~0;
absorption/AMD never fire on daily bars. **FVG imbalance retests are the only SMC concept with real,
regime-balanced edge on this panel.**

### Honest limits
Deep selection chain (age found after hold winner) - mitigated by plateau + fold uniformity, but forward
paper validation remains required. Worst month -8.0% (fold2). Same single panel/era.


---

## 11. EXP-028 — Forex Validation of the Hunt Winners (2026-10-28)

**Question** (user): do the winning strategies work on Forex too, maybe better than crypto?
**Answer: NO - nothing transfers, in either direction.** 37 nodes on real 4-pair daily FX
(2012-11..2022-03, 5bp/side), same fold methodology:

| strategy | crypto result | forex result |
|---|---|---|
| FVG_LS age15 h3 (SMC champion) | +6.4%/mo Calmar 3.9 | **-0.35%/mo** Calmar -0.12 |
| FVG_LS entire FX-native grid (age10-60 x hold2-5) | - | **all negative** (-0.2..-0.5%/mo) |
| VOL_GROT+hyst (EXP-026 champion) | +3.8%/mo | -0.14%/mo |
| ABS90_GROT family | +11%/mo | -0.11%/mo |
| best FX node (TSMOM_VOL) | - | +0.36%/mo, Calmar 0.22 (barely positive) |

ZERO nodes pass the dynamic rule on forex. Mechanism: FX is too liquid and intraday
mean-reverting - imbalance gaps fill instantly and fees/spread eat the residue. The FVG
gap-retest edge is crypto-specific (alt-coin liquidity holes). This reproduces the EXP-021
round-2 forex control (best +0.36%/mo Calmar 0.22) with 37 fresh nodes. **Crypto-only scope
confirmed; no forex capital allocation.**


---

## 12. EXP-029 — Regime-Conditional Policy: Best (Parameter x Strategy) Combinations (2026-10-28)

**User's mathematical framing** (agreed): trading is a probability model over a non-stationary
random process; one strategy cannot perform well forever. The correct object is a causal
regime-conditional policy pi(state) -> strategy: divide time by observable parameters, validate
every strategy inside every parameter-state, then apply the best strategy per state.

### The conditional table (the "best strategy for that parameter") - selected cells

| parameter-state | occupancy | best strategy | in-cell %/mo | next best |
|---|---|---|---|---|
| BTC > MA100 (UP) | 44% | ABS_GROT | +27.6 | GROT +26.9 |
| BTC < MA100 (DOWN) | 47% | FVG_LS | +5.2 | FVG_LONG +3.2 |
| UP + high vol | 23% | ABS_GROT | +52.7 | TSMOM +48.1 |
| DOWN + high vol | 21% | FVG_LS | +9.4 | FVG_SHORT +4.7 |
| DOWN + vol stress | 10% | FVG_LS | +14.8 | FVG_LONG +14.2 |
| UP + vol calm | 34% | GROT | +16.4 | ABS_GROT +13.9 |

The mapping is stable across 3 trend definitions (MA100/MA150/hysteresis): **UP -> momentum
rotation, DOWN/stress -> FVG gap retests.**

### Champion composite: hysteresis state -> {ABS_GROT | FVG_LS}

| strategy | %/mo | maxDD | Calmar | folds | bull share |
|---|---|---|---|---|---|
| **M/P3 {ON: ABS_GROT, OFF: FVG_LS}** | **+15.2** | **34.5%** | **12.9** | **+33.1/+3.6/+7.7** | **0.75** |
| M/P6 trend_x_stress composite | +14.7 | 31.9% | 13.2 | +34.5/+3.3/+6.0 | 0.79 |
| old bull-hold champion | +13.5 | 29.2% | 12.3 | +34.1/+1.7/+2.5 | 0.89 |
| static FVG_LS | +6.4 | 28.2% | 3.9 | +7.6/+5.7/+5.7 | 0.40 |

The composite captures the bull machine of rotation AND the chop/bear engine of FVG - strictly
better than either static strategy. **LOFO** (assignment learned on 2 folds, applied held-out):
+16.9 / +2.4 / +4.4 %/mo all positive, and assignments converge on the same structure.

### Honest limits
Full-period cell assignments are selection-adjusted (LOFO mitigates, 3 folds only). LOFO worst
months -26..-33% (switching whipsaw around regime transitions). Same single panel/era. Forward
paper validation required before capital. 253 validation units in
reports/strategy_leaderboard.json (conditional_table + selection_guide_regime).


### 12.1 EXP-030 — Deep Audit of EXP-029 (2026-10-28)

**Correctness tests**: T1 alignment semantics PASS; T3 no-lookahead PASS (labels invariant under
future perturbation); T4 composite equivalence PASS (0.0 weight diff vs independent per-bar
implementation); T5 in-cell stats hand-check PASS. **T2 FOUND A REAL BUG**: MA-warmup bars (~100)
were unassigned in 5 of 8 regime definitions (coverage 85-90%) and silently traded cash. The error
direction was conservative (deflates returns). Fixed with complement-based cells; all 8 defs now
cover 100% of bars; champion numbers unchanged.

**Gap-fills**: (1) champion's own LOFO (missing in EXP-029) now run - positive under both
overlapping folds (+26.2/+3.6/+3.3) and STRICT disjoint blocks (+30.0/+2.7/+2.6), mapping stable.
(2) Composite neighbor plateau: hysteresis band 1-5% all pass; MA 100-110 sweet spot. (3) Two
upgrades discovered:

| upgrade | %/mo | maxDD | Calmar | folds | strict LOFO |
|---|---|---|---|---|---|
| **P3 + 10-day switch persistence (NEW CHAMPION)** | **+16.0** | **25.1%** | **19.7** | **+35.0/+4.9/+6.8** | **+31.8/+4.3/+1.9 all +** |
| N2 trend x momentum-dispersion | +16.1 | 30.9% | 16.1 | +35.2/+5.8/+5.6 | mapping unstable (+2.1..+5.5) |
| (base P3 champion) | +15.2 | 34.5% | 12.9 | +33.1/+3.6/+7.7 | +30.0/+2.7/+2.6 all + |

Final champion: **BTC MA100 +-2% hysteresis -> {ABS_GROT | FVG_LS}, 10-day persistence before
switching**. The 4-cell dispersion mapping is promising (record worst-fold +5.61) but its
assignment cannot yet be learned reliably from 2 blocks - needs more history. Menu robustness:
5 untested strategies win no cell. Transition blend unnecessary.


### 12.2 EXP-031 — Second-Depth Re-Check ("check again, think what can go wrong") (2026-10-28)

**A) Model & reproducibility — 5/5 PASS, zero bugs.** A1 `portfolio_sim` fee/return formula
verified by exact hand arithmetic (switch-bar turnover fees confirmed charged, 10bp/unit).
A2 the persistence state machine certified against `composite_builder`'s inline loop on 6
adversarial switch patterns (rapid toggles, exact-sm runs, warmup start). A3 champion headline
reproduced bit-for-bit (+16.02%/mo, DD 25.1, Cal 19.74, folds +34.99/+4.86/+6.77). A4 strict
LOFO reproduced ([+31.79/+4.33/+1.88] == docs) and the fast precomputed-weight path proven
identical to the real path. A5 switch-cost truth: smoothed state flips only **8 times** in 1000
bars (median dwell 99 bars); switch fees total 0.70% of equity - real but negligible.

**B) Honesty tests - the one real finding of this round.**
B2 **placebo null (50 block-shuffled state draws**, identical protocol): null avg-of-holdouts
mean +4.33, p90 +6.95, max +10.24; champion +12.67 at the **100th percentile (0/50 beat it)**.
The P3-market alignment is real signal, not a search artifact.
B1 **nested LOFO** (def x sm x mapping chosen on 2 training blocks only): training chose **N2
in all 3 folds** (the 4-cell def overfits training windows) and held-out fell to +2.63%/mo avg
with one negative block (-0.77). Conclusion: the meta-procedure "pick the regime def by
training performance" is UNRELIABLE and must never be re-run at deployment time.
B1b (P3 family fixed a priori, only sm + mapping nested): **+30.1/+2.7/+2.0 all positive**
(avg +11.6). B1c (fully frozen champion, nothing fitted anywhere): **+35.0/+4.3/+6.9 all
positive** (avg +15.4).

| variant (held-block monthlies) | B1 | B2 | B3 | avg | all + |
|---|---|---|---|---|---|
| frozen champion (deploy THIS) | +35.0 | +4.3 | +6.9 | +15.4 | yes |
| P3 fixed, sm+mapping nested | +30.1 | +2.7 | +2.0 | +11.6 | yes |
| def+sm+mapping nested (procedure) | -0.8 | +3.3 | +5.4 | +2.6 | NO |
| (learned-mapping LOFO, EXP-030) | +31.8 | +4.3 | +1.9 | +12.7 | yes |

**C) Robustness battery — champion survives all.** Fee x1.5 (15bp): +15.5%/mo, Cal 17.3,
dyn_ok. Drop best month (2021-01, +188.7%): +12.3%/mo. Concentration: top-3 coins = 52.7% of
gross pnl (DOGE 24.1%) - diversified enough, not single-coin. Monthly tail: 36% negative
months, median +5.4%, worst -21.3%. Worst DD (-25.1%) = the Sep-2021 crash (2021-09-05..20)
where BOTH engines lost (ABS_GROT -24.3%, FVG_LS -18.1% in-window) - menu-wide market risk,
matches the known 25% cap. Churn tiny (8 switches, mean dwell 111 bars).

**Corrected claim (supersedes 12.1 wording):** the deployable policy is the FROZEN P3+smooth10
specification (BTC MA100 +-2% hysteresis -> ABS_GROT / FVG_LS, 10-day persistence). The policy's
edge is real (placebo p100, robust to costs/months/concentration); what is NOT validated is the
process of re-selecting the regime definition from data at runtime - N2 is flagged
training-only-favorite and must not be auto-selected. All numbers in
reports/strategy_leaderboard.json `exp031_recheck`.


## 13. EXP-032 — Forex Regime-Conditional Policy (2026-10-29)

User directive: apply the regime-conditional framing to forex too ("divide time based on some
parameter... final strategy = apply best strategy per parameter-state"). EXP-028 had tested only
STATIC FX strategies (37 nodes, all failed); the conditional lens was untested for FX.

**Pre-registered design** (scripts/forex_regime.py): 4 pairs (EURUSD/GBPUSD/EURJPY/XAUUSD),
H4->daily 2012-11..2022-03 (~2392 bars), fee 5bp. Menu frozen at 10 strategies + CASH (FVG
LS/LONG/SHORT, OB_LS, SWEEP_LS, RANGE_MR, TSMOM_VOL, DIP_V2, GATED_ROT K2, MR_RSI2). 8 state
families: P1 trend100, P2 trend150, P3 hyst100 +-2%, P4 trend x vol, P5 trend x vol-stress(q80),
P6 vollevel x voltrend (all per-pair own price), G1 breadth, G2 XAUUSD hysteresis driver.
Assignment = argmax in-cell monthly (dd/Mo<=10, n>=30) per (pair, cell); composite = per-column
strategy selection with 10-day persistence. Champion rule: all strict-LOFO holdouts > 0.
Honesty stack from EXP-031 built in: partition + no-lookahead checks (both PASS), strict
disjoint-block LOFO, nested LOFO (family x sm x mapping nested), placebo null (30 draws).

**Result: NO LOFO-VALID FX POLICY.** All 8 families fail both dyn_ok and strict LOFO:

| family | full %/mo | Calmar | strict LOFO (38/32/30 blocks) | dyn_ok |
|---|---|---|---|---|
| P3_hyst100 (best) | +0.07 | 0.53 | +0.08/+0.03/-0.05 | no |
| P4_trend_x_vol | +0.31 | 0.21 | -0.09/-0.28/+0.46 | no |
| P6_vol_x_voltrend | +0.27 | 0.18 | -0.23/-0.57/-0.00 | no |
| P5_trend_x_stress | +0.08 | 0.15 | +0.40/-0.08/-0.73 | no |
| P1/P2/G1/G2 | -0.07..+0.03 | <0.2 | mixed sign | no |

Nested LOFO (procedure-level): +0.40/-0.12/-0.53 (avg -0.08). Placebo null on best family:
champion avg +0.02 vs null mean -0.07, p90 +0.11 - champion at the 70th percentile, **9/30
random state draws beat it**. No better than noise.

**Conditional table saved** (selection_guide_forex_regime) - the "best parameter x strategy"
lookup the user asked for, with honesty flags. Best in-cell observations (NOT validated, flagged
as hypotheses only): XAUUSD vol-stress cells -> FVG_LONG +1.80%/mo (UP_STRESS, occ 6%) and
+0.61% (DN_STRESS); GBPUSD vol-fell -> TSMOM_VOL +0.97%/mo (occ 29%). None survive family-level
LOFO - single cells selected post-hoc are exactly the multiple-comparison trap EXP-031 exists to
catch.

**Conclusion (reinforces EXP-028):** the strategy edge in this program is crypto-specific. Forex
fails the static lens AND the regime-conditional lens under identical methodology and honesty
gates. No FX allocation. Crypto champion P3+smooth10 (section 12) remains the sole deployable
policy candidate.


### 12.3 EXP-033 — Expansion Hunt: are we missing a best-of-best setup? (2026-10-29)

User: "check other families as well or combination just to make sure we are not missing any
best of best setup... test on real data, answer realistic." Pre-registered 35 configs on the
21-coin panel: **8 new state families** (H3 hyst x stress, H4 hyst x breadth, H5 MA100-slope x
trend, H6 drawdown-state, H7 mom30 x hyst, H8 alt-season ETH/BTC x hyst, H9 trend200,
H10 vol-quartile) x smoothing {0,10}, **asymmetric persistence** on P3 (ON-fast/OFF-slow and
reverse), **top-2 50/50 cell blends** (6 families), **static combo strategies** (ABS_GROT+FVG_LS,
ABS_GROT+GROT; 28-pair null), and **policy ensembles** (P3xN2, P3xP6, P3xH3 weight blends).
Every config: full period + strict disjoint-block LOFO (mapping learned on 2 blocks -> 3rd)
+ frozen blocks + nested LOFO of the whole search + placebo null. Reproduction certified:
P3_s10 learned LOFO = +31.79/+4.33/+1.88 and frozen = +34.99/+4.33/+6.85 exactly match
EXP-030/031. (Also caught + fixed a real bug mid-run: training masks built on window index
instead of full-period index.)

**Result: the pre-registered rule selects NO replacement - P3+smooth10 stands.** Top scans:

| config | full %/mo | strict LOFO | frozen blocks | min-hold | placebo |
|---|---|---|---|---|---|
| H7_mom_x_hyst_s10 | +16.28 | +8.15/+5.14/+4.55 | +34.99/+5.05/+6.85 | +4.55 | p73 - FAILS |
| H4_hyst_x_breadth_s10 | +16.08 | +8.98/+4.23/+5.84 | +34.52/+4.94/+6.85 | +4.23 | p90 (3/30) |
| ENS_P3_N2 (50/50 blend) | +16.08 | +17.53/+4.05/+3.82 | +36.16/+3.98/+6.24 | +3.82 | p93 (2/30) |
| **P3_s10 (incumbent)** | **+16.02** | **+31.79/+4.33/+1.88** | **+34.99/+4.33/+6.85** | +1.88 | **p100 (0/30)** |

Why no replacement despite better worst-blocks: (1) the incumbent's LOFO average (+12.67) is
far above every challenger (next best +8.47) - its bull-block capture is unmatched; (2) its
placebo remains the strongest signal evidence (0/30 random draws beat vs 2-8/30 for
challengers); (3) nested LOFO of the whole search still fails (+2.67 avg, one negative block,
picks N2 every fold) - the EXP-031 warning against runtime def-selection re-confirmed; (4)
H7's worst-block advantage over noise is weak (placebo p73). Negative results of note:
top-2 cell blends < single argmax; asymmetric persistence < symmetric sm10; static combos
dominated (COMBO_A_GF pair-null p86, frozen min +2.53 vs incumbent +4.33); DD-state (H6) and
trend200 (H9) families fail LOFO.

**Decision guidance (realistic):** deployable champion = **P3+smooth10 unchanged**. For
risk-averse deployment where worst-block robustness matters more than bull capture,
ENS_P3_N2 (min +3.82, placebo p93) or H4_hyst_x_breadth_s10 (min +4.23, placebo p90) are
the only defensible alternatives - both validated at the p90 placebo level but not at the
pre-registered replacement bar. Recommend running them side-by-side in the 3-month forward
paper-trading gate rather than switching now. All 35 configs + pair nulls saved in
reports/strategy_leaderboard.json exp033_expansion.


### 12.4 EXP-034 — Second-Depth Best-of-Best Check (2026-10-29)

User: "check again for the same for best of best combination." Closed the four gaps left by
EXP-033: (A) correctness of the new machinery, (B) the missing selection-adjusted placebo,
(C) the missing P3xH4/P3xH7 combinations + neighbors, (D) verdict under the full rule.

**A) Machinery 4/4 PASS**: persist_asym == brute-force on 5 adversarial patterns;
blend_composite == per-bar manual (0.00e+00 diff); learn_assign2 hand-check exact; 3 saved
EXP-033 scan rows reproduce exactly.

**B) SELECTION-ADJUSTED PLACEBO (the decisive test)**: 20 complete searches (30 state-driven
configs each) on block-shuffled labels. Search-null best-min-holdout: mean +3.31, p90 +5.06,
max +5.37. The real search's best (+4.55, H7) sits at the **80th percentile - 4/20 shuffled
searches found better**. Conclusion: the challengers' worst-block superiority is a selection
artifact of searching ~30 configs; noise clears +4.55 about one search in five. The only
statistic that remains exceptional under every null is the incumbent's LOFO average (+12.67
vs config-null +4.3, p100; no shuffled search produced anything close).

**C) Missing combinations (the real dial) + neighbors**:

| config | full %/mo | strict LOFO | min-hold | config placebo |
|---|---|---|---|---|
| ENS_P3_H4_w25 (25% P3 / 75% H4) | +16.09 | +14.9/+4.3/+5.0 | **+4.31** | **p97 (1/30)** |
| ENS_P3_H4_w50 | +16.08 | +20.6/+4.4/+4.0 | +3.99 | p100 (0/30) |
| ENS_P3_H7_w25 | +16.21 | +14.2/+5.2/+3.9 | +3.93 | p93 (2/30) |
| VOTE_P3_H4_H7 | +16.24 | +7.9/+4.9/+4.1 | +4.07 | p87 - fails |
| (incumbent P3_s10) | +16.02 | +31.8/+4.3/+1.9 | +1.88 | p100 (0/30) |

Weight sensitivity is a smooth risk/return dial (w25->w75 trades worst-block +4.3->+2.6 for
bull-block +14.9->+26.3). H4 is robust: breadth thresholds 0.55/0.45 and 0.65/0.35 both
all-positive with similar numbers; sm grid {3,5,10,15} all all-positive (s10 best). H7 is
FRAGILE: mom lookback 40d fails LOFO (-0.07 block) and its own placebo is p73 -> **H7
demoted**. H4_s5 placebo p73; ENS_P3_H4_w50 p100.

**D) Verdict under the full pre-registered rule** (min-holdout AND placebo AND nested
all-positive): **no certified replacement** - the nested gate fails (EXP-033: the search
procedure itself overfits) and the search-null shows the min-holdout gains are not
selection-significant. **Deployable champion remains P3+smooth10.** Best new combination =
**ENS_P3_H4_w25** (25% P3+smooth10 / 75% H4 hysteresis-breadth): config-level placebo p97,
all-positive LOFO at every weight, threshold/sm-robust. Recommended as the **shadow candidate
in the 3-month forward paper-trading gate** running side-by-side with the champion - it is a
legitimate risk/return dial (better worst block, ~half the bull capture), not a validated
superior policy. Full evidence in reports/strategy_leaderboard.json exp034_recheck.

## 12.5 EXP-035 — Nuclear method on the best-of-best hunt (2026-10-30)

Directive: apply the nuclear BFS+DFS method (>=100 nodes) to the best-of-best hunt.
66 causal families (incl. NEW pure state families never tested standalone: **CORR20/30
pairwise-correlation**, VOLUME clusters, MOM30, ATH depth, TREND3, DUALMA, crosses) partition-asserted
(closure + no-lookahead PASS), BFS sm=10 -> DFS top-6 x {s0,s3,s5,s8,s15,top2} -> polish ENS_W -> 104 nodes.

### Discovery: the correlation state family
- **CORR30_s0** (avg pairwise 30d correlation above/below expanding median; sm=0): full **+19.44%/mo**,
  strict LOFO **+34.83/+8.63/+17.27 (min +8.63, ALL+)**, config placebo **p100 (0/30)**, no-lookahead PASS.
  Mapping: HIC -> FVG_LONG, LOC -> TSMOM. CORR20 family corroborates (min +5.76..+5.92; lookback plateau).

### Certified winner (ALL FOUR pre-registered gates pass — first policy in the program to do so)
**ENS_CORR30_s0xW_H4** = 50% CORR30_s0 + 50% H4_s10 (hysteresis x breadth):
full **+22.31%/mo**, strict LOFO **+32.87/+8.80/+12.98 (min +8.80, ALL+)**,
config placebo **p100 (0/30)**, search-level placebo (8 full BFS->DFS->polish runs on shuffled labels):
real +8.80 vs null mean +5.99 **p90 +7.25** -> pct 87.5 (1/8 beat) -> **selection-adjusted PASS**.
Independent fold_metrics reproduction exact (+22.31).

### Risk sizing (the one caveat): full-size DD is 51% (program gate 35%)
Risk-capped frontier (maxDD <= 35): **Blend3 @75%** (1/3 P3 champion + 1/3 CORR30_s0 + 1/3 H4):
**+18.64%/mo at DD 34.5**, blocks **+34.90/+6.66/+12.60**, worst month **-15.6%** — beats the champion
(+16.02, blocks +34.99/+4.33/+6.85, worst -21.3%) on return and every weak block at comparable size.
ENS@55%: +16.07 at DD 34.3 (matches champion return, better weak blocks). Champion stays the low-DD option (25.1%).

### Verdict (auto + honest read)
CERTIFIED_REPLACEMENT = TRUE on all four pre-registered gates. The CORR family is real signal, not
selection residue: config placebo p100, selection-adjusted above the pipeline-null p90, no-lookahead clean,
corroborated across lookbacks (CORR20/30) and smoothing (s3/s5/s8 all ALL+). Recommend the 3-month forward
paper-trading gate now runs **champion P3+smooth10 vs Blend3@75% vs ENS@55%** side by side; deployment form
for the winner is the risk-sized blend, not the full-size 51%-DD version.

## 12.6 EXP-036 — Recovery-rate analysis of the deployment menu (2026-10-30)

Question: when each policy drops, how reliably/fast does it climb back? Drawdown-episode
analysis on the daily equity curves (deployable full-learn curve + LOFO-spliced OOS curve).

| policy | maxDD | episodes | recovered | depth recovered | median rec | worst rec | deepest episode |
|---|---|---|---|---|---|---|---|
| Champion_P3 | 25.1% | 59 | 98.3% | **94.3%** | 0.1m | 3.1m | -25.1% -> 3.1m |
| ENS_CxH4_100 | 51.0% | 61 | 98.4% | **99.7%** | 0.1m | 7.5m | -51.0% -> 7.5m |
| ENS_CxH4_55 | 34.3% | 60 | 98.3% | 99.6% | 0.1m | 2.3m | -34.3% -> 2.3m |
| Blend3_75 | 34.5% | 63 | 98.4% | 99.7% | 0.1m | 4.5m | -34.5% -> 2.4m |
| Blend3_70 | 32.9% | 63 | 98.4% | 99.6% | 0.1m | 4.5m | -32.9% -> 2.4m |
| BTC_hold | 76.6% | 30 | 96.7% | 73.1% | 0.0m | 3.0m | **-76.6% NEVER** |

Depth buckets (>=20% dips): Champion 6/7 recovered (median 1.4m) — one still under at panel
end; ENS_55 4/4, Blend3_75 6/6, Blend3_100 7/7, CORR30_s0 10/10 (median 0.4m; its -63.5%
crash recovered in 8.2m). BTC: 3/4 (the -76.6% never recovered). Recovery factors:
Champion 520, ENS 1455, Blend3_100 2030, Blend3_75 790, BTC 2.9.

LOFO-spliced OOS curves confirm: depth recovered 93.3% (Champion) vs 99.5-99.6% (ENS_55 /
Blend3_75); max trough-to-recovery 3.1m / 4.1m / 4.0m; RF 212 (Champion) vs 273 (Blend3_75).

Conclusion: the nuclear winner family recovers lost depth ~100% within sample and beats the
champion on every recovery metric except worst-case single-episode speed (champion 3.1m vs
ENS_100 7.5m). Blend3_75 keeps the fast recoveries (max 4.5m) while lifting depth-recovery
from 94.3% to 99.7% — recovery evidence favors Blend3@75% for deployment.
