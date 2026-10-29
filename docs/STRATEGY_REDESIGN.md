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

## 5. Next steps

1. Volatility-targeted position sizing (rescue fold-2 + DD margin).
2. Regime gate: skip blow-off/chop phases (fold-2 killer).
3. Forward paper validation of **Q_TIGHT_TP @ risk 0.5%** (bench config:
   2 slots, lev 2.0, dd-throttle 8%) on fresh candles as they arrive.

Artifacts: `scripts/redesign_lab.py` (diagnostics + variant harness),
`reports/redesign_lab_results.json`, `reports/redesign_round2_results.json`,
ledger entry EXP-021.
