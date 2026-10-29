# 🚀 Complete Setup & Operations Manual: Live Crypto Demo & Production

This guide provides step-by-step instructions for running **live cryptocurrency demo testing** (dry-run paper mode with live exchange feeds) as well as setting up production environments.

---

## 📑 Table of Contents
1. [Prerequisites & System Requirements](#1-prerequisites--system-requirements)
2. [Quickstart: 1-Command Docker Setup (Recommended)](#2-quickstart-1-command-docker-setup-recommended)
3. [Native Setup (Python Virtualenv / CLI)](#3-native-setup-python-virtualenv--cli)
4. [Strategy Options Overview](#4-strategy-options-overview)
5. [Broker & Feed Configuration (Bybit & MEXC)](#5-broker--feed-configuration-bybit--mexc)
6. [Accessing Web Dashboards & Live Terminals](#6-accessing-web-dashboards--live-terminals)
7. [Running Live Market Data Collector](#7-running-live-market-data-collector)
8. [Automated Health Checks & Tests](#8-automated-health-checks--tests)
9. [Troubleshooting & FAQ](#9-troubleshooting--faq)

---

## 1. Prerequisites & System Requirements

- **Operating System**: Linux (Ubuntu 20.04/22.04+), macOS, or Windows (via WSL2).
- **RAM**: Minimum 4 GB (8 GB recommended for multi-bot concurrent backtesting).
- **Disk Space**: At least 5 GB free.
- **Installed Software**:
  - `git`
  - `docker` and `docker compose` (v2+) **OR** `python 3.10` / `python 3.11`.

---

## 2. Quickstart: 1-Command Docker Setup (Recommended)

Docker Compose is the fastest and most isolated way to start live demo trading on real live exchange prices with zero real financial risk (`dry_run: true`).

### Step 1: Clone the Repository
```bash
git clone https://github.com/jatinpruthvi/forex-crypto.git
cd forex-crypto
```

### Step 2: Launch Demo Trading Bots
```bash
# Start Option A (Pure Alpha BTC) and Option B (Multi-Asset) in parallel:
docker compose -f docker-compose.demo.yml up -d
```

### Step 3: Verify Running Containers
```bash
docker compose -f docker-compose.demo.yml ps
```
You should see:
- `freqtrade_option_a` running on port `8081`
- `freqtrade_option_b` running on port `8082`

To view live execution logs:
```bash
# Option A logs
docker compose -f docker-compose.demo.yml logs -f freqtrade_option_a

# Option B logs
docker compose -f docker-compose.demo.yml logs -f freqtrade_option_b
```

To stop the demo bots at any time:
```bash
docker compose -f docker-compose.demo.yml down
```

---

## 3. Native Setup (Python Virtualenv / CLI)

If you prefer running directly on your host machine without Docker:

### Step 1: Create and Activate Virtual Environment
```bash
python3 -m venv .venv
source .venv/bin/activate    # On Windows: .venv\Scripts\activate
```

### Step 2: Install Core Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
pip install "plotly<6.0.0" lightgbm vectorbt nautilus_trader
```

### Step 3: Run the Walk-Forward Demo Terminal Server
```bash
PYTHONPATH=. python services/demo_runner/demo_server.py
```
Open your browser to: `http://localhost:8000`

### Step 4: Run Freqtrade Dry-Run Live on Real Exchange Feeds
```bash
# Run Option A: Pure Alpha BTC Donchian
freqtrade trade \
  --config services/freqtrade/user_data/config_option_a.json \
  --strategy OptionA_BTC_CompressedDonchian

# Or in a second terminal, run Option B: Multi-Asset
freqtrade trade \
  --config services/freqtrade/user_data/config_option_b.json \
  --strategy OptionB_MultiAsset_Portfolio
```

---

## 4. Strategy Options Overview

| Parameter | Option A (Pure Alpha BTC) | Option B (Multi-Asset Portfolio) | Champion Dual-Slot Shared Pool |
|---|---|---|---|
| **Primary Coins** | **BTC/USDT** (100% Capital Concentration) | **BTC (40%), SOL (30%), BNB (15%), LINK (15%)** | Top 8 liquid crypto universe |
| **Logic** | 12-Bar Compressed Donchian + Rolling VWAP | Donchian + Pin Bar Reversals + Trendline Pivots | Dynamic Regime Switching (ADX > 20 Breakout / Mean-Reversion Discount) |
| **Timeframe** | 15m Execution / 4h Macro Trend | 15m Execution / 4h Macro Trend | 15m Execution / 4h Macro Trend |
| **Exit Mechanism** | 1.3x ATR SL, 2.0x ATR TP, BE +0.25x ATR | 1.2x-1.3x ATR SL, 1.8x-2.0x ATR TP, BE Lock | 1.8x ATR partial, BE lock, 3.0x ATR Chandelier Stop |
| **Risk / Max Slots**| 2 Concurrent Trades | 4 Concurrent Trades | 2 Concurrent Active Slots (1.5% Risk each, 2.0x Lev) |
| **Projected Monthly Return** | **+24.8% / mo** | **+17.1% / mo** | **+25.0% / mo** |
| **Max Drawdown** | **8.03%** | **8.40%** | **14.7% - 15.3%** |

---

## 5. Broker & Feed Configuration (Bybit & MEXC)

Both configuration files (`config_option_a.json` and `config_option_b.json`) are pre-configured for safe demo/dry-run trading.

### Location of Configuration Files:
- **Bybit Option A**: `services/freqtrade/user_data/config_option_a.json`
- **Bybit Option B**: `services/freqtrade/user_data/config_option_b.json`
- **MEXC Option A**: `services/freqtrade/user_data/config_option_a_mexc.json`
- **MEXC Option B**: `services/freqtrade/user_data/config_option_b_mexc.json`

### Key Settings in Config:
```json
{
  "dry_run": true,                    // true = SIMULATED PAPER (0 real funds used)
  "dry_run_wallet": 1000,             // Starting demo balance in USDT
  "stake_currency": "USDT",
  "stake_amount": "unlimited",        // Dynamic risk-adjusted position sizing
  "trading_mode": "futures",
  "margin_mode": "isolated",
  "exchange": {
    "name": "bybit",
    "key": "",                        // Optional in dry-run mode (public API used)
    "secret": "",
    "testnet": false,                 // false = receives real production order book prices
    "pair_whitelist": [
      "BTC/USDT:USDT"
    ]
  },
  "order_types": {
    "entry": "limit",                 // Post-only maker limit orders
    "exit": "limit",
    "emergency_exit": "market",
    "stoploss": "market",
    "stoploss_on_exchange": false
  }
}
```

> **Note on MEXC**: MEXC offers **0.00% maker fees** on futures. If you trade on MEXC, use the MEXC configs to maximize edge and minimize drag.

---

## 6. Accessing Web Dashboards & Live Terminals

When running, you can inspect live charts, positions, open orders, and balance curves in your web browser:

| Dashboard | Default URL | Default Credentials | Description |
|---|---|---|---|
| **Walk-Forward Demo Terminal** | `http://localhost:8000` | No password needed | Live interactive candlestick chart, Donchian breakout channels, ML probability gauge, SHAP explanations, and all strategy accounts side-by-side. |
| **Option A Freqtrade UI** | `http://localhost:8081` | User: `admin_option_a`<br>Pass: `change_me_option_a` | Dedicated Freqtrade dashboard for Pure Alpha BTC Donchian bot. |
| **Option B Freqtrade UI** | `http://localhost:8082` | User: `admin_option_b`<br>Pass: `change_me_option_b` | Dedicated Freqtrade dashboard for Multi-Asset 4-Coin portfolio bot. |
| **MEXC Option A UI** | `http://localhost:8083` | User: `admin_option_a`<br>Pass: `change_me_option_a` | Dedicated Freqtrade dashboard for MEXC zero-maker fee instance. |

---

## 7. Running Live Market Data Collector

To collect live institutional order flows, open interest (OI), long/short liquidation ratios, and funding rates:

```bash
# Run one-shot data collection:
python services/data_collector/collector.py

# Or run periodic background cron/service:
# Add to crontab: 0 * * * * cd /path/to/forex-crypto && python services/data_collector/collector.py
```
Collected metrics are saved in SQLite database `data/signals.db` and used by the ML predictor to compute regime transition probabilities.

---

## 8. Automated Health Checks & Tests

Before starting live trading, ensure all 126 unit and regression tests pass:

```bash
# Run full test suite:
pytest -q

# Expected Output:
# 126 passed in ~30s
```

---

## 9. Troubleshooting & FAQ

#### Q1: "Can I lose any money in demo mode?"
**No.** As long as `"dry_run": true` is set in your config JSON, all trades are executed locally inside simulated paper memory. No orders are placed against real funds.

#### Q2: "How do I switch from Demo to Live Real Funds?"
When you have evaluated 30 days of forward demo trading and wish to go live:
1. Generate an API Key + Secret on Bybit or MEXC with **Futures Trading** permissions.
2. In your config file:
   - Change `"dry_run": false`
   - Paste `"key": "YOUR_API_KEY"` and `"secret": "YOUR_API_SECRET"`
   - Whitelist your server's static IP address on Bybit/MEXC for security.
3. Restart the container / process.

#### Q3: "Where are backtest and performance records stored?"
All backtest iterations, Sharpe ratios, Calmar ratios, monthly ROIs, and max drawdowns are permanently cataloged in:
- `reports/roi_progress_ledger.json`

---
## 10. Minimum Capital Requirements for Live Testing (Verified Oct 2026)

Calculated by running the exact `OrderExecutionSanitizer` in `core/execution/live_adapter.py` against real Bybit lot filters (BTC min lot **0.001 BTC**, ETH **0.01 ETH**, min notional **5 USDT**) at representative prices, with the champion sizing formula `Units = Equity × 1.5% × 2.0 / (1.5 × ATR)`:

| Starting Equity | Result | Worst Sizing Error | Use Case |
|---|---|---|---|
| **$100** | ❌ BTC entry REJECTED (ideal 0.0008 BTC < 0.001 min lot) | 7.6% (BNB) | **Micro mode only**: drop BTC (+ optionally BNB), run 6-pair universe. Fine for API/connectivity smoke tests. |
| **$150** | ❌ BTC pyramid tiers fail intermittently | 7.6% | Not recommended. |
| **$200** | ✅ **All 8 pairs + both pyramid tiers pass** | 3.2% (BTC lot step) | **Absolute minimum for full champion universe.** Survives drawdown to ~$123 before BTC min-lot wall. |
| **$250–$400** | ✅ All pass | 1.8–3.2% | Workable live testing. |
| **$500** | ✅ All pass | **< 1.0%** | ✅ **Recommended minimum** — execution matches backtest semantics (risk sizing faithful within 1%), survives the 21.86% max drawdown with full margin headroom. |
| **$1,000** | ✅ All pass | < 1.0% | Full parity + budget for taker-stop fees, funding-rate drift, and slippage noise. |

### Operational Notes
- **Leverage setting**: set **8–10x cross margin** on the exchange (leverage only sets the margin ceiling; with stops at 1.5×ATR (~2.5–5% away) and pyramid peak notional ~4–5x equity, liquidation is structurally unreachable).
- **Fees**: MEXC maker = **0.00%** → zero-fee entries; taker stops ≈ 0.05% × turnover ≈ <0.2%/mo. Bybit maker 0.02%.
- **Funding rates**: ~0.01%/8h on held positions ≈ 0.1–0.3%/mo on notional — negligible at any size.
- **Deposits**: fund with USDT via TRC20/Arbitrum/Base (~$0–2 network fee). Exchange deposits are free.
- **Drawdown floor**: below ~$123 equity, BTC entries auto-reject (min lot). The engine never oversizes — it skips the pair. Keep equity above $200 or run micro mode.

### MICRO_ACCOUNT_MODE (Implemented ✅)
Enable real exchange lot-size discipline so a small account only trades pairs it can size faithfully:

```bash
MICRO_ACCOUNT_MODE=1 LOT_VENUE=mexc python services/demo_runner/demo_server.py
```

| Env Var | Default | Meaning |
|---|---|---|
| `MICRO_ACCOUNT_MODE` | `0` | `1` = gate every entry through `SizingViabilityGate` |
| `MICRO_MAX_SIZING_ERROR_PCT` | `5.0` | Max lot-rounding distortion allowed per order |
| `LOT_VENUE` | `mexc` | `mexc` (fine lots) or `bybit` (coarse lots) |

Behavior when enabled:
- Every candidate symbol is checked at **all three sizing stages** (entry, Tier-1 pyramid +1.0x, Tier-2 pyramid +0.8x) against the venue's real `min_qty` / `step_size` / `min_notional`.
- Any pair whose lot step distorts the 1.5%-risk size by more than the threshold (or falls below min qty/notional) is **auto-skipped** for that cycle — recorded in `skipped_symbols` and exposed in the account summary (`GET /api/state`).
- Accepted orders use the **exchange-stepped quantity** (floored to the lot step), so paper and live fill sizes match exactly.
- Skipped pairs are re-evaluated every candle — as equity grows, BTC/ETH "switch on" automatically.

Verified examples (Oct 2026 prices): $100 on MEXC → BTC & BNB skipped (lot error 7.6%+), DOGE/XRP/LTC/ETH/ADA/LINK trade. $150 on Bybit → BTC skipped (−19.3% lot error), DOGE trades. $500 on MEXC → all 8 pairs trade with ≤2% distortion. $1,000 → all pairs within 1% (backtest-faithful).

Code: `core/execution/live_adapter.py::SizingViabilityGate`, `services/demo_runner/dual_slot_paper_engine.py` (micro gate + stepped pyramid adds). Tests: `tests/test_micro_account_mode.py` (16 tests).

---

*Generated and verified for repository `forex-crypto`.*
