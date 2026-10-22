# PRD: Automated Multi-Asset Trading System (AMATS)

> **Version:** 1.0.0  
> **Status:** Active  
> **Last Updated:** 2026-10-21  
> **Repo:** `jatinpruthvi/forex-crypto`  
> **Branch:** `arena/b657ea09-forex-crypto`

---

## 1. Executive Summary

### 1.1 Problem Statement
Retail traders with small initial capital ($500) cannot earn meaningful returns from slow basis yield arbitrage or multi-asset rebalancing:
- Layer 3 (Market-neutral quarterly basis spread, $100) yields only ~$1-3/quarter before fees.
- Layer 4 (Rebalancing across 4 assets, $50) is eaten entirely by transaction overhead.
- Liquidation feeds such as Coinglass require $99/mo (20% of account equity).

### 1.2 The 2-Layer Modified Solution
Reallocate the full $500 into high-efficiency engines:
1. **Crypto Directional ($323 on Bybit Perpetual Futures via FreqTrade):** Real compounding returns with dynamic ATR exits and free proxy signals (Funding Rate, Open Interest delta, Long/Short ratio, Taker ratio).
2. **Forex / Prop Challenge Multiplication ($177 allocated across 3 challenges via MQL5 EA):** Uses funded capital ($10,000+ accounts) with an 80% payout split to scale $500 into $2,000–$5,000/month.

---

## 2. System Architecture

```
External Data Feeds (Bybit, Binance, Forex Factory)
                     │
                     ▼
       Layer 1: Data Collector (Hourly Cron) ──→ SQLite (signals.db)
                     │
                     ▼
       Layer 2: Signal Processing (Hurst + ATR %ile Regime, 4-Signal Fusion)
                     │
                     ▼
       Layer 3: Optional ML Filter (22-Feature XGBoost Classifier)
                     │
                     ▼
       Layer 4: Brain Decision Engine (FastAPI REST Bridge :8000)
                     │
       ┌─────────────┴─────────────┐
       ▼                           ▼
  Layer 5A: Crypto            Layer 5B: Forex Prop Firms
  FreqTrade (Bybit)           MQL5 MasterRiskEA & PythonBrainEA (MT5)
       │                           │
       ▼                           ▼
  Bybit Futures Exchange       Prop Firm Broker Execution
```

---

## 3. Drawdown Escalation Protocol (Hard Limits)

| Monthly DD | Tier | Sizing Mult | Conviction Min | Action |
|---|---|---|---|---|
| **0 – 3%** | **GREEN** | 100% (1.0x) | ≥ 60 | Normal operation |
| **3 – 5%** | **YELLOW** | 50% (0.5x) | ≥ 75 | Cut risk in half, log all setups |
| **5 – 7%** | **ORANGE** | 25% (0.25x) | ≥ 85 | Defensive trading during London/NY overlap |
| **7 – 8%** | **RED** | 0% (0.0x) | ≥ 100 | Halt all new entries, trailing stops only |
| **> 8%** | **BLACK** | 0% (0.0x) | N/A | **Hard Kill Switch:** Market liquidation, 72h cooldown |

---

## 4. Kill-Switch Matrix

1. **KS1 (Brain API Silent > 10m):** MQL5 EA halts new trades and liquidates open positions after threshold.
2. **KS2 (Exchange Disconnect > 5m):** FreqTrade watchdog triggers Telegram alert & reconnection retry.
3. **KS3 (Single Trade Catastrophe > 3%):** Immediate cut via custom stoploss.
4. **KS4 (Daily Loss > 2%):** MasterRiskEA and FreqTrade protections halt trading until next UTC midnight.
5. **KS5 (Flash Crash > 5% single bar):** Immediate lockout on pair for 2 hours.
6. **KS6 (VPS Crash):** systemd watchdog auto-recovers microservices in < 2 minutes; broker positions remain secured by broker-side SL/TP.
