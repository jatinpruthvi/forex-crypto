# Automated Multi-Asset Trading System (AMATS)

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-009688.svg)](https://fastapi.tiangolo.com/)
[![MetaTrader 5](https://img.shields.io/badge/MetaTrader-5-green.svg)](https://www.metatrader5.com/)
[![FreqTrade](https://img.shields.io/badge/FreqTrade-Futures-orange.svg)](https://www.freqtrade.io/)

A complete, institutional-grade automated multi-asset trading system specifically optimized for small capital accounts ($500), combining:
- **Bybit Crypto Futures Layer ($323 allocation):** Directional multi-regime trading with FreqTrade.
- **Forex Prop Firm Challenge Layer ($177 allocation):** Funded account scaling with MetaTrader 5 (MQL5 Master/Slave architecture) and 80% profit payouts.
- **Unified Python Brain:** REST decision bridge providing real-time regime detection, free 4-signal fusion, 22-feature XGBoost filtering, and a 4-tier hard drawdown escalation protocol.

---

## Repository Structure

```
├── core/
│   ├── regime/         # Hurst exponent (R/S) + ATR percentile matrix
│   ├── signals/        # Signal fusion (Funding, OI, L/S, Taker), events & cross-asset
│   ├── risk/           # 4-tier Drawdown escalation & 6-scenario kill-switch
│   ├── ml/             # 22-feature pipeline, Optuna XGBoost training & inference
│   └── analysis/       # Kelly sizing, Monte Carlo stress tests & walk-forward validation
├── services/
│   ├── brain_api/      # FastAPI server (:8000) for real-time MQL5/FreqTrade decision bridge
│   ├── data_collector/ # Hourly collector for free Bybit/Binance signals & SQLite storage
│   ├── freqtrade/      # Production configs & strategies (Combined, Trend, MeanReversion)
│   ├── mql5/           # MetaTrader 5 Expert Advisors (MasterRiskEA & PythonBrainEA)
│   └── monitoring/     # Telegram alerts, health heartbeat, and live console dashboard
├── docs/               # PRD, Architecture, Deployment, Strategy & Troubleshooting guides
├── scripts/            # VPS setup, zero-downtime deploy, backup, and emergency liquidation
└── tests/              # Pytest test suite covering core components and API endpoints
```

---

## Quick Start

### 1. Local Environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Run Test Suite
```bash
pytest -v
```

### 3. Launch Services
- **Brain API:** `make run-api` (or `uvicorn services.brain_api.main:app --port 8000`)
- **Data Collector:** `make run-collector`
- **Docker Orchestration:** `docker-compose up -d`

For comprehensive documentation, see [docs/PRD.md](docs/PRD.md) and [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).
