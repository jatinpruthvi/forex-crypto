# 🏦 Prop Firms with API Access — Full Comparison & ROI vs. Invested Capital

**Date**: October 28, 2026
**Question**: Which funded-account prop firms allow our automated strategy via API, and what ROI does each deliver versus trading our own invested capital?
**Previous verdict**: Vest Markets REJECTED — no API trading on funded accounts, 6% max drawdown, XRP banned.

---

## ✅ 1. Screening Criteria (What Our Strategy Demands)

| Requirement | Why It Matters |
|---|---|
| **API / Bot automation allowed** | Our engine is 100% automated Python (CCXT / WebSocket / MQL5 bridge). Manual execution is a non-starter. |
| **Crypto pairs (8-coin universe)** | DOGE, BNB, XRP, ADA, BTC, LTC, ETH, LINK — XRP must be tradable (Vest failed here). |
| **Max Drawdown ≥ 8–10%** | Our champion runs 21.86% Max DD at 1.5% risk. Even throttled, we need DD headroom. |
| **Daily Loss Limit ≥ 4–5%** | 4H crypto candles with 2 open slots produce 1.5–3% daily swings at throttled risk. |
| **Static (non-trailing) drawdown preferred** | Trailing drawdowns ratchet against floating profits — hostile to our pyramiding ratchet. |
| **Reasonable fee / refundable deposit** | Fee is the "invested capital" at risk on the prop route. |

---

## 📊 2. The Candidate Field (Verified October 2026)

| Firm | Market | Automation Route | Max DD | Daily Loss | Profit Split | Entry Fee (50K) | Bots Policy |
|---|---|---|---|---|---|---|---|
| **HyroTrader** | Crypto perps (700+ pairs, real Bybit/Binance) | **Native Bybit REST API** (same as our bot) | 10% static (2-Step) / 6% (1-Step) | 5% (2-Step) / 4% (1-Step) | 80% → 90% | ~$499 (1-Step) / ~$579 per 100K (2-Step) | ✅ Own + third-party bots via API (funded); HFT banned |
| **Propr.xyz** | Crypto perps (Hyperliquid, 160+ markets) | **Public REST API + Python/JS SDK**, Beta sandbox, 1,200 req/min | 6% static (Classic 1-Step) | 3% | 80% | $495 (Classic) / $245 (Turbo, 3% DD) | ✅ Bots, copy-trading, third-party tools all allowed |
| **FTMO** | Forex / CFD + ~22 crypto CFDs | **MT4/MT5 Expert Advisors** (our MQL5 bridge fits) | 10% static (2-Step) | 5% | 80% → 90% | ~€345 (~$370) | ✅ EAs allowed, no pre-approval; $400K per-strategy cap |
| **FundedNext** | Forex / CFD + crypto CFDs | **MT4/MT5 EAs** ($5/mo EA fee below 50K; EAs prohibited at 50K Stellar) | 10% static (Stellar 2-Step) | 5% | 80% → 95% | $299.99 | ⚠️ EAs allowed below $50K only on Stellar |
| **Topstep / TopstepX** | CME Futures (NOT crypto) | TopstepX / ProjectX API ($29/mo) | Trailing | Intraday | 90%+ | $49/mo + $149 | ⚠️ Bots off at Live; futures-only — wrong asset class |
| **Vest Markets** | Crypto / FX / Equities | ❌ **NO API on funded accounts** | 6% fixed | 3–4% | 80–95% | — | ❌ REJECTED |
| **Apex / Take Profit Trader** | Futures | ❌ Manual order entry required | — | — | — | — | ❌ REJECTED (bots prohibited) |

---

## 📐 3. Risk Throttling Math — Fitting Our Strategy into Prop Rules

Our Dual-Slot crypto engine's verified risk spectrum (ledger EXP-013 / risk sweep):

| Base Risk | Monthly ROI | Max Drawdown |
|---|---|---|
| 0.75% | +12.09%/mo | 14.72% |
| 1.25% | +21.71%/mo | 19.51% |
| **1.50% (Champion)** | **+25.01%/mo** | **21.86%** |

Scaling to fit prop-firm drawdown limits (with our built-in Dynamic Drawdown Throttle as safety net):

| Prop DD Limit | Safe Operating DD | Throttled Base Risk | Expected Monthly ROI | Daily Swing |
|---|---|---|---|---|
| **10%** (FTMO, FundedNext, Hyro 2-Step) | ~8% | **0.40–0.50%** | **+6.5% – +8%/mo** | ~1.5–2.5% |
| **6%** (Propr Classic, Hyro 1-Step) | ~5% | **0.25%** | **+4% – +5%/mo** | ~1–1.5% |
| **3%** (Propr Turbo) | ~2.5% | **0.10–0.15%** | **+2%/mo** | ~0.5% |

> 💡 **Forex variant bonus**: For FTMO/FundedNext (forex brokers), our 5-Year Forex Macro engine (2-Slot, 0.75% risk) delivers **+25.43%/mo at 15.35% DD** (Calmar 19.88). Throttled to 8% DD → ~0.39% risk → **~+13%/mo** — nearly double the crypto-throttled rate on forex prop accounts.

---

## 💰 4. ROI Comparison — 12-Month Projection (Starting Capital: $1,000 of Your Money)

### Route A: Invested Account (Self-Funded on MEXC / Bybit)
| Month | Balance (Champion 1.5% risk, +25.01%/mo) |
|---|---|
| 0 | $1,000 |
| 3 | $1,953 |
| 6 | $3,817 |
| 9 | $7,459 |
| 12 | **$14,567** |
- **Your take-home**: 100% of profits. True compounding. No rules, no termination.
- **Your risk**: 21.86% Max DD is your own money ($218 of every $1,000).
- **Monthly ROI on invested capital**: **+25.01%/mo**.

### Route B: HyroTrader 2-Step $50K (Fee ≈ $400–500, refunded with first payout)
| Phase | Duration | Result |
|---|---|---|
| Eval Phase 1 (+10% target @ 0.45% risk, ~7.5%/mo) | ~1.4 months | Pass |
| Eval Phase 2 (+5% target) | ~0.7 months | Pass → Funded |
| Funded $50K @ ~7.5%/mo, 80% split | Month 3 onward | **≈ $3,000/month take-home** |
| After 12 months total | ~10 months funded | **≈ $28,000–32,000 collected** |
- **ROI on your fee**: $3,000/mo ÷ $450 ≈ **+660%/mo on capital at risk** once funded.
- **Fee is refunded** with first payout → cost basis returns to ~$0.
- Crypto-native: our 8-pair universe (incl. XRP) trades on real Bybit perps. Our CCXT bot connects **without code changes**.

### Route C: FTMO 2-Step $100K (Fee ≈ €540 ≈ $580)
| Phase | Duration | Result |
|---|---|---|
| Eval (10% + 5% targets @ 0.40% risk) | ~2 months | Pass → Funded |
| Funded $100K (forex engine @ ~13%/mo throttled, 80% split) | Month 3 onward | **≈ $10,400/month take-home** |
| After 12 months total | ~10 months funded | **≈ $95,000–105,000 collected** |
- **ROI on your fee**: $10,400 ÷ $580 ≈ **+1,790%/mo on capital at risk** once funded.
- Requires our **MQL5 bridge** (`services/mql5/PythonBrainEA.mq5`) on MT5 — already built in this repo.

### Route D: Propr.xyz Classic 1-Step $50K (Fee $495, non-refundable)
| Phase | Duration | Result |
|---|---|---|
| Eval (+10% target @ 0.25% risk, ~4.5%/mo, 6% static DD) | ~2.2 months | Pass → Funded |
| Funded $50K @ ~4.5%/mo, 80% split | Month 3 onward | **≈ $1,800/month take-home** |
- **ROI on your fee**: $1,800 ÷ $495 ≈ **+364%/mo on capital at risk**.
- Best developer experience: live REST API, Python SDK, Beta sandbox, 1,200 req/min, per-trade A/B-book labels, on-chain USDC payouts with published tx hashes.

### 🏆 Route E (Recommended Hybrid): Invested + 2 Prop Accounts
| Vehicle | Capital at Risk | Monthly Take-Home (Steady State) | Role |
|---|---|---|---|
| Invested $1,000 (MEXC, 1.5% risk, full champion) | $1,000 (yours) | Grows 25%/mo compounding → $14.6K by M12 | **Wealth engine** (unbounded compounding) |
| HyroTrader $50K 2-Step (crypto, 0.45% risk) | ~$450 fee (refundable) | ~$3,000/mo | **Crypto prop income** (native Bybit API fit) |
| FTMO $100K 2-Step (forex engine, 0.40% risk) | ~$580 fee | ~$10,400/mo | **Forex prop income** (MQL5 bridge fit) |
| **Total** | **~$2,030** | **~$13,400/mo + compounding account** | |

---

## ⚖️ 5. Head-to-Head: Invested Account vs. Funded Account

| Dimension | Invested (Self-Funded) | Funded (Prop) | Winner |
|---|---|---|---|
| **Monthly ROI on your capital** | +25.01%/mo on $1,000 | +360% to +1,790%/mo on the fee | 🏆 Prop (capital leverage 50–100x) |
| **Absolute monthly $** | $250 → $3,000/mo (growing) | $1,800 – $10,400/mo flat | 🏆 Prop |
| **Compounding** | True exponential (12.5x in 12 months) | None — payouts extracted; account resets to base | 🏆 Invested |
| **Rule-termination risk** | None — drawdowns are survivable | One bad streak kills account + fee | 🏆 Invested |
| **Max usable risk** | 1.5% (full champion) | 0.25–0.50% (throttled to fit DD rules) | 🏆 Invested |
| **Strategy fit** | Perfect (all 8 pairs, pyramiding, 2.0x leverage) | Constrained (throttled risk, daily loss caps) | 🏆 Invested |
| **Automation** | Full API freedom | Allowed at API-friendly firms (Hyro, Propr, FTMO) | Tie |
| **Sweat/ops** | Set and monitor | Eval passing, rule compliance, payout cycles | 🏆 Invested |

**The math verdict**: Prop firms win on **income per dollar at risk** (you rent $50–100K of notional capital for ~$500). Invested accounts win on **wealth compounding and freedom**. They are complementary, not competing.

---

## 🎯 6. Final Recommendation

1. **DO run the invested account** as the core compounding engine at full 1.5% champion risk. This is where exponential wealth is built (12.5x/yr).
2. **ADD prop income from API-friendly firms only**:
   - **#1 HyroTrader (2-Step $50K–$100K)** — the only crypto prop with **native Bybit API** execution; our existing CCXT/Bybit bot runs unchanged. Throttle to 0.45% risk. Verify "own strategy" declaration at signup.
   - **#2 FTMO ($100K 2-Step)** — the most proven payout history (since 2015); deploy the **forex macro engine via our MQL5 bridge** throttled to 0.40% risk (~13%/mo).
   - **#3 Propr.xyz (optional, $25–$495)** — best-in-class API/SDK + Beta sandbox for testing; ideal for validating the bot under prop rules cheaply before committing larger fees. Choose **Classic 1-Step (6% static DD)** — never Turbo (3% DD is hostile to our pyramiding).
3. **NEVER use** Vest Markets (no API), Apex, or Take Profit Trader (bots banned) for this strategy.
4. **Risk discipline on prop accounts**: enable our Dynamic Drawdown Throttle at 4% (not 8%) on prop accounts, and cap daily loss at 2.5% internally to stay inside the 3–5% firm limits.

### Integration Status in This Repo
| Integration | Status |
|---|---|
| Bybit API (CCXT) — HyroTrader route | ✅ Already live in `services/demo_runner/` + Freqtrade config |
| MQL5 bridge — FTMO route | ✅ `services/mql5/PythonBrainEA.mq5` + `MasterRiskEA.mq5` |
| Propr REST API (Python SDK) | 🔧 Adapter needed (~1 day: map our signals to `api.propr.xyz/v1` orders) |
| Risk throttle preset for prop rules | 🔧 Add `PROP_SAFE_MODE` config (0.45% risk, 4% throttle threshold) |

---

*Sources: docs.vestmarkets.com (Vest rules), propfirmpal.com & hyrotrader.com (HyroTrader rules/fees), fundedtrading.com & propfirmbridge.com (Propr rules/fees), bestprops.com & propfirmautotrade.com (FTMO/FundedNext/bot policies), sentinel.redclawey.com & pickmytrade.io (futures firm bot policies) — all verified October 2026.*
