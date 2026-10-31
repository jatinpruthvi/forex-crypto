# Broker Setup Guide: Bybit & MEXC

This platform supports both **Bybit** (best-in-class API stability and low latency) and **MEXC** (0.00% maker fee rate).

---

## 1. Broker Profile Overview

| Feature | Bybit | MEXC |
|---|---|---|
| **Futures Maker Fee** | 0.020% (0.010% for VIPs) | **0.000% (Zero Maker)** |
| **Futures Taker Fee** | 0.055% | 0.020% |
| **Contract Type** | USDT Perpetual Linear (`category=linear`) | USDT Perpetual Swap (`defaultType=swap`) |
| **Recommended Strategy Mode**| Post-Only Maker Limit Orders (`"entry": "limit"`) | Post-Only Maker Limit Orders (`"entry": "limit"`) |
| **API Endpoints** | REST v5 + WebSocket (`api.bybit.com`) | REST v1 Contract (`contract.mexc.com`) |
| **Testnet Support** | Full Sandbox Testnet (`testnet.bybit.com`) | Dry-Run / Paper Simulation |

---

## 2. Configuration Files

### Option A (Pure Alpha BTC Donchian Engine)
- **Bybit**: `services/freqtrade/user_data/config_option_a.json` (Dashboard: `http://localhost:8081`)
- **MEXC**: `services/freqtrade/user_data/config_option_a_mexc.json` (Dashboard: `http://localhost:8083`)

### Option B (Multi-Asset 4-Coin Concurrent Portfolio)
- **Bybit**: `services/freqtrade/user_data/config_option_b.json` (Dashboard: `http://localhost:8082`)
- **MEXC**: `services/freqtrade/user_data/config_option_b_mexc.json` (Dashboard: `http://localhost:8084`)

---

## 3. Running All Bots Simultaneously via Docker

```bash
# Start all 4 demo instances (Bybit Option A & B + MEXC Option A & B)
docker compose -f docker-compose.demo.yml up -d
```

---

## 4. Live API Key Setup

To connect live accounts:
1. Open the respective configuration JSON file.
2. Update the `exchange` object:
```json
"exchange": {
  "name": "bybit", // or "mexc"
  "key": "YOUR_API_KEY",
  "secret": "YOUR_API_SECRET",
  "dry_run": false
}
```
3. Set your IP allowlist on the broker's dashboard for security.
