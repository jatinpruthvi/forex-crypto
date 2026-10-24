# AMATS Troubleshooting & Failure Recovery

| Issue | Root Cause | Immediate Fix |
|---|---|---|
| **MQL5 EA: WebRequest 4040 error** | URL not in MT5 whitelist | Go to `Tools > Options > Expert Advisors` and add `http://<vps-ip>:8000`. |
| **Brain API: Port 8000 in use** | Zombie Python process running | `sudo lsof -ti:8000 \| xargs kill -9` |
| **FreqTrade: "No data found"** | Bybit futures pair format mismatch | Bybit futures pairs must have suffix `:USDT` (e.g. `BTC/USDT:USDT`). |
| **Data collector: Missing Binance LS** | Non-major pair requested | Binance only provides global L/S accounts for BTC & ETH. System defaults to neutral 1.0 for altcoins. |
| **Hurst calculation lagging** | Unvectorized chunking | Use the optimized Rescaled Range function in `core/regime/detector.py`. |
| **Drawdown Alert: RED or BLACK** | Protocol triggered hard stop | Automated lock engaged. Review `logs/brain.log`. Do not override manually; follow the 72-hour cooldown. |
