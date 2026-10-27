# AMATS Strategy Specifications

## 1. Simplified 2-Indicator Regime Detection Matrix

Instead of computationally heavy and fragile HMM/GARCH models, AMATS uses:
- **Trend vs Range:** Rolling 100-bar Hurst Exponent ($H$) via Rescaled Range (R/S).
- **Volatility Regime:** Rolling 200-bar ATR Percentile Rank.

### 2x2 Matrix:
| | ATR < 20%ile | ATR 20–80%ile | ATR 80–95%ile | ATR > 95%ile |
|---|---|---|---|---|
| **$H > 0.55$ (Trending)** | SQUEEZE | **TREND** (Trend Follower) | **BREAKOUT** (Wide ATR Stops) | **CRISIS** (Cash) |
| **$0.45 \le H \le 0.55$** | SQUEEZE | **TRANSITION** (50% Size) | **BREAKOUT** | **CRISIS** (Cash) |
| **$H < 0.45$ (Ranging)** | SQUEEZE | **RANGE** (Mean Reversion) | **BREAKOUT** | **CRISIS** (Cash) |

---

## 2. Free 4-Signal Fusion Engine (Liquidation Proxy)

Replaces expensive $99/mo feeds with free public metrics (25 pts each = 100 max):
1. **Funding Rate (25 pts):** $>0.05\%$ = Bearish (+25 Bear), $<-0.03\%$ = Bullish (+25 Bull).
2. **Open Interest Delta (25 pts):** OI expanding + Price rising = Bullish (+25 Bull).
3. **Long/Short Account Ratio (25 pts):** Extreme crowd long $>2.5$ = Contrarian Short (+25 Bear); $<0.5$ = Contrarian Long (+25 Bull).
4. **Taker Buy/Sell Volume Ratio (25 pts):** Taker ratio $>1.1$ = Bull (+25 Bull); $<0.9$ = Bear (+25 Bear).

**Execution Threshold:** Conviction $\ge 60$ required for trade generation.

---

## 3. Slippage & Fee Reality
- Backtests default to **0.1% market slippage**.
- Bybit Taker Fee: **0.055%**, Maker Fee: **0.02%**.
- Forex minimum slippage model: **10 points**.
- Rule: Only strategies profitable with real slippage + real fees are deployed to live.
