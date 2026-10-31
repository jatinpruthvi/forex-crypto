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

### PRE-SCREEN NOTE (EXP-048, 2026-10-30)
The PRE-SCREENED rows above were run as a batch at 10bp taker and failed. The screen covered only
those exact rules — **it does NOT close the family**: every UNTESTED row remains a validation unit.
Additionally, all 15m-frequency rules must be re-tested under the maker-fee regime (I-07, 3bp
post-only) before final closure, since the screen showed the deaths were cost-burn driven.

---

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
| VP-02,05,06,07,08,10,11,12,13,14,15,16,17 · VPSS-01..03 · SS-02,03,05,07,08,11,12,14,15,16,17,18 | **UNTESTED — validate one by one on user's go** | | | |
| I-07..I-24 (others) | untested | | | |

**Cumulative best: R3.1 ×2 +4.73%/mo SR 1.77 (×3 +6.80%/mo). All-years-positive: R3 ×2 +4.52/minYr +0.31.**
