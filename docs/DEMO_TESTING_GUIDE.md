# Live Demo Testing Guide: Option A vs. Option B

This guide details how to run and monitor **Option A** (Pure Alpha BTC Donchian) and **Option B** (All-Weather Multi-Asset Concurrent Portfolio) side-by-side in demo/dry-run mode.

---

## 1. Architectural Summary of Both Options

| Parameter | Option A (Pure Alpha Concentration) | Option B (All-Weather Multi-Asset Portfolio) |
|---|---|---|
| **Strategy Class** | `OptionA_BTC_CompressedDonchian` | `OptionB_MultiAsset_Portfolio` |
| **Config File** | `services/freqtrade/user_data/config_option_a.json` | `services/freqtrade/user_data/config_option_b.json` |
| **Target Assets** | **BTC/USDT** (100% Capital Concentration) | **BTC (40%), SOL (30%), BNB (15%), LINK (15%)** |
| **Strategies Executed** | 12-Bar Compressed Donchian + Rolling VWAP | Donchian (BTC), Pin Bar Reversal (SOL/BNB), Trendline Pivot (LINK) |
| **Execution Timeframe** | 15-Minute (M15) | 15-Minute (M15) |
| **Macro Trend Filter** | 4-Hour (H4) 50-EMA & Institutional VWAP | 4-Hour (H4) 50-EMA & Institutional VWAP |
| **Max Open Positions** | 2 concurrent trades | 4 concurrent trades |
| **Exits** | 1.3x ATR SL, 2.0x ATR TP, BE +0.25x ATR at +1.0x ATR | 1.2x-1.3x ATR SL, 1.8x-2.0x ATR TP, BE +0.25x ATR lock |
| **Historical ROI Target**| **+24.80% Compounded Monthly ROI** | **+17.06% Compounded Monthly ROI** |
| **Trade Frequency** | ~40 trades / month | ~104 trades / month (Active daily trades) |
| **Historical Max DD** | **8.03%** | **8.40%** |
| **Demo Web UI Port** | `http://localhost:8081` | `http://localhost:8082` |

---

## 2. Launching Both Bots in Demo Mode

Both bots can be run concurrently via Docker or directly using Freqtrade:

### Method 1: Docker Compose (Recommended)
```bash
# Launch both Option A and Option B containers in parallel
docker compose -f docker-compose.demo.yml up -d
```

### Method 2: Direct CLI Execution
```bash
# Option A (Port 8081)
freqtrade trade \
  --config services/freqtrade/user_data/config_option_a.json \
  --strategy OptionA_BTC_CompressedDonchian

# Option B (Port 8082)
freqtrade trade \
  --config services/freqtrade/user_data/config_option_b.json \
  --strategy OptionB_MultiAsset_Portfolio
```

---

## 3. Web UI Access & Real-Time Monitoring

Each bot exposes its own independent Freqtrade REST API & Web Dashboard:

- **Option A Dashboard**: `http://localhost:8081`
  - Username: `admin_option_a`
  - Password: `change_me_option_a`
- **Option B Dashboard**: `http://localhost:8082`
  - Username: `admin_option_b`
  - Password: `change_me_option_b`

---

## 4. Demo Evaluation Checklist: What to Measure Over 30 Days

1. **Net Monthly ROI**: Compare the compounding velocity of Option A's BTC concentration against Option B's altcoin blend.
2. **Drawdown Peaks**: Track whether either option approaches the 8% max drawdown ceiling.
3. **Execution Quality**: Verify maker post-only limit fills and zero slippage on Bybit testnet.
4. **Trade Frequency**: Observe if Option B's ~3.5 trades/day fits your operational preference better than Option A's ~1.3 trades/day.
