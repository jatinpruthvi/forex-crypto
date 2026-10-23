"""
Interactive AMATS Demo Trading Web Server & Live Simulation UI:
Spins up a lightweight FastAPI dashboard hosting both:
1. Option A (Pure 12-bar Donchian BTC on MEXC Zero-Fee & Bybit)
2. Option B (4-Asset Portfolio on MEXC Zero-Fee & Bybit)
With real-time Paper Accounts, Live Feed Simulator, and interactive control buttons.
"""
import os
import json
import asyncio
from datetime import datetime, timezone
import pandas as pd
import numpy as np
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from services.demo_runner.paper_broker import PaperAccount

app = FastAPI(title="AMATS Live Demo Trading Station")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Demo Accounts
demo_accounts = {
    "option_a_mexc": PaperAccount("MEXC (0.00% Maker)", starting_capital=10000.0, maker_fee=0.0000),
    "option_a_bybit": PaperAccount("Bybit (0.02% Maker)", starting_capital=10000.0, maker_fee=0.0002),
    "option_b_mexc": PaperAccount("MEXC Multi-Asset (0.00% Maker)", starting_capital=10000.0, maker_fee=0.0000),
}

# Load replay market data
historical_data = {}
try:
    if os.path.exists("data/timeframes/BTCUSD_M15.csv"):
        df_btc = pd.read_csv("data/timeframes/BTCUSD_M15.csv")
        historical_data["BTC"] = df_btc
except Exception as e:
    print(f"Historical load error: {e}")

# Precompute indicators for replay simulation
def prepare_signals(df: pd.DataFrame):
    df = df.copy()
    close = df["close"]
    high = df["high"]
    low = df["low"]
    vol = df["volume"]
    
    tr = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
    df["atr"] = tr.rolling(14).mean().bfill()
    df["ema20"] = close.ewm(span=20).mean()
    df["ema50"] = close.ewm(span=50).mean()
    
    typical_p = (high + low + close) / 3.0
    df["vwap"] = (typical_p * vol).rolling(30).sum() / vol.rolling(30).sum().replace(0, 1)
    
    df["donchian_high"] = high.rolling(12).max().shift(1)
    df["donchian_low"] = low.rolling(12).min().shift(1)
    return df

prepared_btc = prepare_signals(historical_data["BTC"].tail(1000).reset_index(drop=True)) if "BTC" in historical_data else None
simulation_state = {
    "index": 0,
    "is_running": True,
    "last_tick_time": ""
}

async def simulation_loop():
    while True:
        if simulation_state["is_running"] and prepared_btc is not None and len(prepared_btc) > 0:
            idx = simulation_state["index"]
            if idx >= len(prepared_btc):
                simulation_state["index"] = 0
                idx = 0
            
            row = prepared_btc.iloc[idx]
            timestamp = str(row["timestamp"])
            high = float(row["high"])
            low = float(row["low"])
            close = float(row["close"])
            atr = float(row["atr"])
            dh = float(row["donchian_high"])
            dl = float(row["donchian_low"])
            vwap = float(row["vwap"])
            ema20 = float(row["ema20"])
            ema50 = float(row["ema50"])
            
            simulation_state["last_tick_time"] = timestamp
            
            # Check price updates on existing positions
            for acc in demo_accounts.values():
                acc.update_price("BTC/USDT", high, low, close, timestamp)
            
            # Check breakout signal
            # Long
            if close > row["open"] and close > vwap and ema20 > ema50 and high >= dh:
                sl = close - 1.3 * atr
                tp = close + 2.0 * atr
                for k in ["option_a_mexc", "option_a_bybit", "option_b_mexc"]:
                    demo_accounts[k].open_position("BTC/USDT", "long", close, risk_pct=3.0, sl_price=sl, tp_price=tp, atr=atr, tag="Donchian-12 Breakout")
            # Short
            elif close < row["open"] and close < vwap and ema20 < ema50 and low <= dl:
                sl = close + 1.3 * atr
                tp = close - 2.0 * atr
                for k in ["option_a_mexc", "option_a_bybit", "option_b_mexc"]:
                    demo_accounts[k].open_position("BTC/USDT", "short", close, risk_pct=3.0, sl_price=sl, tp_price=tp, atr=atr, tag="Donchian-12 Breakdown")

            simulation_state["index"] += 1
        
        await asyncio.sleep(0.5) # 2 ticks per second

@app.on_event("startup")
async def start_sim():
    # Fast forward first 500 candles so demo has trades already on boot
    if prepared_btc is not None:
        for i in range(min(450, len(prepared_btc))):
            row = prepared_btc.iloc[i]
            ts = str(row["timestamp"])
            h, l, c, atr = float(row["high"]), float(row["low"]), float(row["close"]), float(row["atr"])
            dh, dl, vwap, ema20, ema50 = float(row["donchian_high"]), float(row["donchian_low"]), float(row["vwap"]), float(row["ema20"]), float(row["ema50"])
            for acc in demo_accounts.values():
                acc.update_price("BTC/USDT", h, l, c, ts)
            if c > row["open"] and c > vwap and ema20 > ema50 and h >= dh:
                for k in ["option_a_mexc", "option_a_bybit", "option_b_mexc"]:
                    demo_accounts[k].open_position("BTC/USDT", "long", c, risk_pct=3.0, sl_price=c - 1.3 * atr, tp_price=c + 2.0 * atr, atr=atr, tag="Donchian-12 Breakout")
            elif c < row["open"] and c < vwap and ema20 < ema50 and l <= dl:
                for k in ["option_a_mexc", "option_a_bybit", "option_b_mexc"]:
                    demo_accounts[k].open_position("BTC/USDT", "short", c, risk_pct=3.0, sl_price=c + 1.3 * atr, tp_price=c - 2.0 * atr, atr=atr, tag="Donchian-12 Breakdown")
        simulation_state["index"] = 450
    asyncio.create_task(simulation_loop())

@app.get("/api/accounts")
def get_accounts():
    return {k: acc.get_summary() for k, acc in demo_accounts.items()}

@app.post("/api/reset")
def reset_demo():
    for k in demo_accounts:
        fee = 0.0 if "mexc" in k else 0.0002
        bname = demo_accounts[k].broker_name
        demo_accounts[k] = PaperAccount(bname, starting_capital=10000.0, maker_fee=fee)
    simulation_state["index"] = 0
    return {"status": "reset_complete"}

@app.get("/", response_class=HTMLResponse)
def index_page():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AMATS Live Strategy Demo Station</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #0b0f19;
      --card-bg: #111827;
      --border: #1f2937;
      --accent: #3b82f6;
      --success: #10b981;
      --danger: #ef4444;
      --text: #f3f4f6;
      --subtext: #9ca3af;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); padding: 24px; }
    .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; border-bottom: 1px solid var(--border); padding-bottom: 16px; }
    .title h1 { font-size: 24px; font-weight: 800; color: #fff; }
    .title p { color: var(--subtext); font-size: 14px; margin-top: 4px; }
    .status-badge { display: inline-flex; align-items: center; gap: 8px; background: rgba(16, 185, 129, 0.15); color: var(--success); padding: 6px 14px; border-radius: 999px; font-size: 13px; font-weight: 600; }
    .pulse { width: 8px; height: 8px; border-radius: 50%; background: var(--success); animation: pulse 1.5s infinite; }
    @keyframes pulse { 0% { opacity: 1; transform: scale(1); } 50% { opacity: 0.4; transform: scale(1.3); } 100% { opacity: 1; transform: scale(1); } }
    .cards-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(350px, 1fr)); gap: 20px; margin-bottom: 24px; }
    .card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px; padding: 20px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3); }
    .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
    .card-header h2 { font-size: 16px; font-weight: 700; color: #fff; }
    .tag { font-size: 11px; text-transform: uppercase; padding: 4px 8px; border-radius: 4px; font-weight: 700; }
    .tag-mexc { background: rgba(59, 130, 246, 0.2); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.3); }
    .tag-bybit { background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }
    .metric-main { font-size: 28px; font-family: 'JetBrains Mono', monospace; font-weight: 700; margin-bottom: 8px; }
    .metric-row { display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 13px; }
    .metric-label { color: var(--subtext); }
    .metric-val { font-weight: 600; font-family: 'JetBrains Mono', monospace; }
    .pos-val { color: var(--success); }
    .neg-val { color: var(--danger); }
    .positions-section { background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px; padding: 20px; margin-bottom: 24px; }
    table { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 13px; }
    th { text-align: left; padding: 10px; color: var(--subtext); border-bottom: 1px solid var(--border); font-size: 12px; text-transform: uppercase; }
    td { padding: 12px 10px; border-bottom: 1px solid rgba(31, 41, 55, 0.5); font-family: 'JetBrains Mono', monospace; }
    .btn-reset { background: #374151; color: #fff; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-weight: 600; font-size: 13px; transition: 0.2s; }
    .btn-reset:hover { background: #4b5563; }
  </style>
</head>
<body>
  <div class="header">
    <div class="title">
      <h1>🚀 AMATS Live Demo Strategy Trading Station</h1>
      <p>Simulated Live Paper Execution & Real-Time Performance Comparison</p>
    </div>
    <div style="display: flex; gap: 12px; align-items: center;">
      <div class="status-badge"><div class="pulse"></div> DEMO ENGINE ACTIVE</div>
      <button class="btn-reset" onclick="resetDemo()">Reset Demo</button>
    </div>
  </div>

  <div class="cards-grid" id="accountsGrid">
    <div style="color: var(--subtext); padding: 20px;">Loading live demo feeds...</div>
  </div>

  <div class="positions-section">
    <h2 style="font-size: 16px; font-weight: 700; margin-bottom: 12px;">📈 Real-Time Active Open Positions (Virtual Paper Execution)</h2>
    <table>
      <thead>
        <tr>
          <th>Account Engine</th>
          <th>Symbol</th>
          <th>Side</th>
          <th>Entry Price</th>
          <th>Current Price</th>
          <th>Position Size</th>
          <th>Stop Loss</th>
          <th>Take Profit</th>
          <th>Unrealized P&L</th>
        </tr>
      </thead>
      <tbody id="positionsTable">
        <tr><td colspan="9" style="text-align:center; color: var(--subtext);">No open positions currently.</td></tr>
      </tbody>
    </table>
  </div>

  <div class="positions-section">
    <h2 style="font-size: 16px; font-weight: 700; margin-bottom: 12px;">📜 Recent Closed Trades Log</h2>
    <table>
      <thead>
        <tr>
          <th>Account</th>
          <th>Side</th>
          <th>Entry</th>
          <th>Exit</th>
          <th>Exit Reason</th>
          <th>Net P&L ($)</th>
          <th>ROI (%)</th>
          <th>Exit Timestamp</th>
        </tr>
      </thead>
      <tbody id="tradesTable">
        <tr><td colspan="8" style="text-align:center; color: var(--subtext);">Awaiting trade closures...</td></tr>
      </tbody>
    </table>
  </div>

  <script>
    async function updateDashboard() {
      try {
        const res = await fetch('/api/accounts');
        const data = await res.json();
        
        let gridHtml = '';
        let posRows = '';
        let tradeRows = '';

        for (const [key, acc] of Object.entries(data)) {
          const isMexc = key.includes('mexc');
          const pnlClass = acc.total_net_profit >= 0 ? 'pos-val' : 'neg-val';
          const pnlSign = acc.total_net_profit >= 0 ? '+' : '';
          
          gridHtml += `
            <div class="card">
              <div class="card-header">
                <h2>${acc.broker}</h2>
                <span class="tag ${isMexc ? 'tag-mexc' : 'tag-bybit'}">${isMexc ? 'ZERO MAKER FEE' : 'BYBIT 0.02%'}</span>
              </div>
              <div class="metric-main ${pnlClass}">
                $${acc.current_equity.toLocaleString('en-US', {minimumFractionDigits: 2})}
              </div>
              <div class="metric-row">
                <span class="metric-label">Net Profit / ROI:</span>
                <span class="metric-val ${pnlClass}">${pnlSign}$${acc.total_net_profit.toFixed(2)} (${pnlSign}${acc.total_return_pct}%)</span>
              </div>
              <div class="metric-row">
                <span class="metric-label">Max Drawdown:</span>
                <span class="metric-val" style="color: ${acc.max_drawdown_pct > 10 ? '#ef4444' : '#10b981'}">${acc.max_drawdown_pct}%</span>
              </div>
              <div class="metric-row">
                <span class="metric-label">Trades / Win Rate:</span>
                <span class="metric-val">${acc.total_trades} trades (${acc.win_rate_pct}%)</span>
              </div>
              <div class="metric-row">
                <span class="metric-label">Maker Fee Tier:</span>
                <span class="metric-val">${acc.maker_fee_pct.toFixed(2)}%</span>
              </div>
            </div>
          `;

          // Positions
          for (const pos of acc.open_positions) {
            const pnl = pos.unrealized_pnl;
            const pnlCls = pnl >= 0 ? 'pos-val' : 'neg-val';
            posRows += `
              <tr>
                <td><strong>${acc.broker}</strong></td>
                <td>${pos.symbol}</td>
                <td><span style="color: ${pos.side === 'long' ? 'var(--success)' : 'var(--danger)'}; font-weight: 700;">${pos.side.toUpperCase()}</span></td>
                <td>$${pos.entry_price.toFixed(2)}</td>
                <td>$${pos.current_price.toFixed(2)}</td>
                <td>${pos.size.toFixed(4)}</td>
                <td style="color: var(--danger)">$${pos.sl_price.toFixed(2)}</td>
                <td style="color: var(--success)">$${pos.tp_price.toFixed(2)}</td>
                <td class="${pnlCls}">${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}</td>
              </tr>
            `;
          }

          // Trades
          for (const tr of acc.recent_trades.slice(-5).reverse()) {
            const trPnlCls = tr.net_pnl >= 0 ? 'pos-val' : 'neg-val';
            tradeRows += `
              <tr>
                <td><strong>${acc.broker}</strong></td>
                <td style="color: ${tr.side === 'long' ? 'var(--success)' : 'var(--danger)'}">${tr.side.toUpperCase()}</td>
                <td>$${tr.entry_price.toFixed(2)}</td>
                <td>$${tr.exit_price.toFixed(2)}</td>
                <td>${tr.reason}</td>
                <td class="${trPnlCls}">${tr.net_pnl >= 0 ? '+' : ''}$${tr.net_pnl.toFixed(2)}</td>
                <td class="${trPnlCls}">${tr.pnl_pct >= 0 ? '+' : ''}${tr.pnl_pct.toFixed(1)}%</td>
                <td style="font-size: 11px; color: var(--subtext);">${tr.exit_time.split('T')[0]} ${tr.exit_time.split('T')[1]?.slice(0,8) || ''}</td>
              </tr>
            `;
          }
        }

        document.getElementById('accountsGrid').innerHTML = gridHtml;
        if (posRows) document.getElementById('positionsTable').innerHTML = posRows;
        if (tradeRows) document.getElementById('tradesTable').innerHTML = tradeRows;

      } catch (err) {
        console.error('Fetch error:', err);
      }
    }

    async function resetDemo() {
      await fetch('/api/reset', { method: 'POST' });
      updateDashboard();
    }

    setInterval(updateDashboard, 1000);
    updateDashboard();
  </script>
</body>
</html>
    """

if __name__ == "__main__":
    uvicorn.run("services.demo_runner.demo_server:app", host="0.0.0.0", port=8000, reload=False)
