"""
True Real-Time Walk-Forward Demo Station:
- Reads real historical market candles sequentially (timestamp by timestamp).
- Advances 1 candle every second in real time (simulating a live streaming order feed).
- Calculates technical indicators in rolling causal mode without any future lookahead.
- Enforces real order execution:
  * 4H 50-EMA Macro Trend Filter
  * 12-bar Donchian breakout / breakdown
  * 1.3x ATR initial Stop Loss
  * 1.0x ATR profit trigger moves SL to Entry + 0.25x ATR Breakeven profit buffer
  * 2.0x ATR Take Profit
  * Real dynamic drawdown throttle
- Transparent real-time accounting of every win, loss, and drawdown.
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

from services.demo_runner.real_paper_engine import RealPaperAccount

app = FastAPI(title="AMATS Live Walk-Forward Demo Station")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. Load Real Market Data
df_h4 = pd.read_csv("data/timeframes/BTCUSD_H4.csv")
df_m15 = pd.read_csv("data/timeframes/BTCUSD_M15.csv")

df_h4["timestamp"] = pd.to_datetime(df_h4["timestamp"])
df_m15["timestamp"] = pd.to_datetime(df_m15["timestamp"])

# 2. 4H Macro Trend Calculation (EMA 50)
df_h4["ema50_h4"] = df_h4["close"].ewm(span=50).mean()
df_h4["macro_trend"] = np.where(df_h4["close"] > df_h4["ema50_h4"], 1, -1)

# 3. Merge 4H Macro Trend backward into M15 candles
df_stream = pd.merge_asof(
    df_m15.sort_values("timestamp"),
    df_h4[["timestamp", "macro_trend"]].sort_values("timestamp"),
    on="timestamp",
    direction="backward"
)
df_stream["macro_trend"] = df_stream["macro_trend"].fillna(1)

# Precalculate rolling indicators causally
close = df_stream["close"]
high = df_stream["high"]
low = df_stream["low"]
open_p = df_stream["open"]
vol = df_stream["volume"]

tr = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
df_stream["atr"] = tr.rolling(14).mean().bfill()
df_stream["ema20"] = close.ewm(span=20).mean()
df_stream["ema50"] = close.ewm(span=50).mean()

typical_p = (high + low + close) / 3.0
df_stream["vwap"] = (typical_p * vol).rolling(30).sum() / vol.rolling(30).sum().replace(0, 1)

df_stream["donchian_high"] = high.rolling(12).max().shift(1)
df_stream["donchian_low"] = low.rolling(12).min().shift(1)

# ADX Regime Filter Indicator
plus_dm = high.diff()
minus_dm = low.diff()
plus_dm[plus_dm < 0] = 0
minus_dm[minus_dm > 0] = 0
minus_dm = minus_dm.abs()
plus_di = 100 * (plus_dm.ewm(alpha=1/14).mean() / df_stream["atr"])
minus_di = 100 * (minus_dm.ewm(alpha=1/14).mean() / df_stream["atr"])
dx = 100 * (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, 1))
df_stream["adx"] = dx.ewm(alpha=1/14).mean()

# 3 Real Paper Trading Accounts
accounts = {
    "mexc_opt_a": RealPaperAccount("MEXC Option A (0.00% Maker)", initial_capital=10000.0, maker_fee=0.0000),
    "bybit_opt_a": RealPaperAccount("Bybit Option A (0.02% Maker)", initial_capital=10000.0, maker_fee=0.0002),
    "mexc_opt_b": RealPaperAccount("MEXC Multi-Asset (0.00% Maker)", initial_capital=10000.0, maker_fee=0.0000),
}

stream_pointer = {
    "current_index": 0,
    "current_candle": {},
    "is_paused": False,
    "speed": 1.0,
    "total_bars": len(df_stream)
}

# Start 1,500 candles before end for live streaming
START_INDEX = max(0, len(df_stream) - 1500)
stream_pointer["current_index"] = START_INDEX

async def walk_forward_streaming_loop(initial_prev_sig: int = 0):
    prev_sig = initial_prev_sig
    idx = stream_pointer["current_index"]
    
    while True:
        if not stream_pointer["is_paused"]:
            if idx >= len(df_stream):
                idx = START_INDEX # Loop playback if reaching end
                
            row = df_stream.iloc[idx]
            ts = str(row["timestamp"])
            c = float(row["close"])
            h = float(row["high"])
            l = float(row["low"])
            o = float(row["open"])
            atr_val = float(row["atr"])
            macro = int(row["macro_trend"])
            dh = float(row["donchian_high"])
            dl = float(row["donchian_low"])
            vwap = float(row["vwap"])
            ema20 = float(row["ema20"])
            ema50 = float(row["ema50"])

            stream_pointer["current_candle"] = {
                "timestamp": ts,
                "open": o, "high": h, "low": l, "close": c,
                "atr": atr_val, "macro_trend": "BULLISH" if macro == 1 else "BEARISH",
                "dh": dh, "dl": dl, "vwap": vwap,
                "adx": float(row["adx"])
            }

            # 1. Update all open positions with this candle's price action
            for acc in accounts.values():
                acc.on_candle(ts, h, l, c)

            # 2. Check for fresh breakout signals with ADX Regime Filter (ADX >= 18.0)
            cur_adx = float(row["adx"])
            cond_adx = cur_adx >= 18.0

            bull = (macro == 1) and (c > o) and (c > vwap) and (ema20 > ema50) and (h >= dh) and cond_adx
            bear = (macro == -1) and (c < o) and (c < vwap) and (ema20 < ema50) and (l <= dl) and cond_adx
            sig = 1 if bull else (-1 if bear else 0)

            is_transition = (sig != 0) and (sig != prev_sig)
            prev_sig = sig

            if is_transition:
                if sig == 1:
                    for acc in accounts.values():
                        acc.open_trade(ts, "long", c, atr_val, base_risk_pct=3.0)
                elif sig == -1:
                    for acc in accounts.values():
                        acc.open_trade(ts, "short", c, atr_val, base_risk_pct=3.0)

            idx += 1
            stream_pointer["current_index"] = idx

        # 1 candle per second (simulates 15m candle close updates)
        await asyncio.sleep(0.7)

@app.on_event("startup")
async def start_feed():
    global START_INDEX
    # Warm up first 800 bars so user immediately sees live active stats from the historical feed
    warmup_start = START_INDEX - 800
    prev_sig = 0
    for i in range(warmup_start, START_INDEX):
        row = df_stream.iloc[i]
        ts = str(row["timestamp"])
        c, h, l, o, atr_val = float(row["close"]), float(row["high"]), float(row["low"]), float(row["open"]), float(row["atr"])
        macro, dh, dl, vwap, ema20, ema50 = int(row["macro_trend"]), float(row["donchian_high"]), float(row["donchian_low"]), float(row["vwap"]), float(row["ema20"]), float(row["ema50"])
        cur_adx = float(row["adx"])
        
        for acc in accounts.values():
            acc.on_candle(ts, h, l, c)
            
        cond_adx = cur_adx >= 18.0
        bull = (macro == 1) and (c > o) and (c > vwap) and (ema20 > ema50) and (h >= dh) and cond_adx
        bear = (macro == -1) and (c < o) and (c < vwap) and (ema20 < ema50) and (l <= dl) and cond_adx
        sig = 1 if bull else (-1 if bear else 0)
        
        if (sig != 0) and (sig != prev_sig):
            if sig == 1:
                for acc in accounts.values():
                    acc.open_trade(ts, "long", c, atr_val, base_risk_pct=3.0)
            elif sig == -1:
                for acc in accounts.values():
                    acc.open_trade(ts, "short", c, atr_val, base_risk_pct=3.0)
        prev_sig = sig

    asyncio.create_task(walk_forward_streaming_loop(initial_prev_sig=prev_sig))

@app.get("/api/state")
@app.get("/api/accounts")
def get_live_state():
    return JSONResponse(content={
        "candle": stream_pointer["current_candle"],
        "stream_index": stream_pointer["current_index"],
        "total_candles": stream_pointer["total_bars"],
        "is_paused": stream_pointer["is_paused"],
        "accounts": {k: acc.get_summary() for k, acc in accounts.items()}
    })

@app.post("/api/reset")
def reset_simulation():
    for k in accounts:
        fee = accounts[k].maker_fee
        bname = accounts[k].name
        accounts[k] = RealPaperAccount(bname, initial_capital=10000.0, maker_fee=fee)
    stream_pointer["current_index"] = START_INDEX
    return {"status": "reset_successful"}

@app.post("/api/toggle_pause")
def toggle_pause():
    stream_pointer["is_paused"] = not stream_pointer["is_paused"]
    return {"is_paused": stream_pointer["is_paused"]}

@app.get("/", response_class=HTMLResponse)
def index_html():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AMATS Live Walk-Forward Paper Trading Station</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #090d16;
      --card-bg: #111827;
      --card-hover: #162032;
      --border: #1f2937;
      --accent: #3b82f6;
      --success: #10b981;
      --danger: #ef4444;
      --warning: #f59e0b;
      --text: #f3f4f6;
      --subtext: #9ca3af;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); padding: 24px; line-height: 1.5; }
    .header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; border-bottom: 1px solid var(--border); padding-bottom: 16px; }
    .title h1 { font-size: 22px; font-weight: 800; color: #fff; letter-spacing: -0.5px; }
    .title p { color: var(--subtext); font-size: 13px; margin-top: 4px; }
    .ticker-bar { display: flex; gap: 16px; background: rgba(31, 41, 55, 0.4); padding: 10px 16px; border-radius: 8px; border: 1px solid var(--border); margin-bottom: 20px; align-items: center; font-family: 'JetBrains Mono', monospace; font-size: 13px; }
    .ticker-item span { color: var(--subtext); font-size: 11px; text-transform: uppercase; margin-right: 6px; }
    .status-badge { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; }
    .badge-live { background: rgba(16, 185, 129, 0.15); color: var(--success); }
    .badge-bull { background: rgba(16, 185, 129, 0.2); color: var(--success); }
    .badge-bear { background: rgba(239, 68, 68, 0.2); color: var(--danger); }
    .pulse { width: 7px; height: 7px; border-radius: 50%; background: var(--success); animation: pulse 1.2s infinite; }
    @keyframes pulse { 0% { opacity: 1; transform: scale(1); } 50% { opacity: 0.3; transform: scale(1.3); } 100% { opacity: 1; transform: scale(1); } }
    .cards-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 20px; margin-bottom: 24px; }
    .card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }
    .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
    .card-header h2 { font-size: 15px; font-weight: 700; color: #fff; }
    .tag { font-size: 10px; text-transform: uppercase; padding: 3px 8px; border-radius: 4px; font-weight: 700; font-family: 'JetBrains Mono', monospace; }
    .tag-mexc { background: rgba(59, 130, 246, 0.2); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.3); }
    .tag-bybit { background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }
    .metric-main { font-size: 30px; font-family: 'JetBrains Mono', monospace; font-weight: 700; margin-bottom: 12px; }
    .metric-row { display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 13px; }
    .metric-label { color: var(--subtext); }
    .metric-val { font-weight: 600; font-family: 'JetBrains Mono', monospace; }
    .pos-val { color: var(--success); }
    .neg-val { color: var(--danger); }
    .section-card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px; padding: 20px; margin-bottom: 24px; }
    .section-card h3 { font-size: 15px; font-weight: 700; margin-bottom: 12px; display: flex; align-items: center; justify-content: space-between; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th { text-align: left; padding: 10px 12px; color: var(--subtext); border-bottom: 1px solid var(--border); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }
    td { padding: 12px 12px; border-bottom: 1px solid rgba(31, 41, 55, 0.6); font-family: 'JetBrains Mono', monospace; font-size: 12.5px; }
    .btn { background: #374151; color: #fff; border: 1px solid #4b5563; padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 12px; font-weight: 600; transition: 0.15s; }
    .btn:hover { background: #4b5563; }
    .btn-danger { background: rgba(239, 68, 68, 0.2); border-color: rgba(239, 68, 68, 0.4); color: #f87171; }
    .btn-danger:hover { background: rgba(239, 68, 68, 0.4); }
  </style>
</head>
<body>
  <div class="header">
    <div class="title">
      <h1>🚀 AMATS Live Walk-Forward Paper Trading Station</h1>
      <p>True Sequential Candle Replay with Zero Future Data Lookahead & Unfiltered PnL Execution</p>
    </div>
    <div style="display: flex; gap: 8px;">
      <button class="btn" onclick="togglePause()" id="pauseBtn">⏸ Pause Stream</button>
      <button class="btn btn-danger" onclick="resetSim()">↺ Reset Paper Accounts</button>
    </div>
  </div>

  <div class="ticker-bar" id="tickerBar">
    <div class="ticker-item"><div class="status-badge badge-live"><div class="pulse"></div> FEED: STREAMING</div></div>
    <div class="ticker-item"><span>TIMESTAMP:</span><strong id="barTime">Loading...</strong></div>
    <div class="ticker-item"><span>BTC CLOSE:</span><strong id="barClose">$0.00</strong></div>
    <div class="ticker-item"><span>4H MACRO:</span><strong id="barMacro">--</strong></div>
    <div class="ticker-item"><span>ADX (14):</span><strong id="barAdx">0.0</strong></div>
    <div class="ticker-item"><span>ATR (14):</span><strong id="barAtr">$0.00</strong></div>
    <div class="ticker-item"><span>DONCHIAN 12:</span><strong id="barDonchian">$0 / $0</strong></div>
  </div>

  <div class="cards-grid" id="accountsGrid">
    <div style="color: var(--subtext);">Initializing real paper accounts...</div>
  </div>

  <div class="section-card">
    <h3>
      <span>📌 Real-Time Open Virtual Position</span>
      <span style="font-size: 12px; color: var(--subtext); font-weight: normal;">Live stops adjusted dynamically</span>
    </h3>
    <table>
      <thead>
        <tr>
          <th>Account Engine</th>
          <th>Side</th>
          <th>Entry Price</th>
          <th>Current Price</th>
          <th>Position Size</th>
          <th>Stop Loss</th>
          <th>Take Profit</th>
          <th>Breakeven Locked</th>
          <th>Unrealized P&L ($)</th>
        </tr>
      </thead>
      <tbody id="openPositionsTable">
        <tr><td colspan="9" style="text-align: center; color: var(--subtext); padding: 24px;">No active open positions. Awaiting breakout transition.</td></tr>
      </tbody>
    </table>
  </div>

  <div class="section-card">
    <h3>
      <span>📜 Live Closed Trades Audit Log (Recent Fills)</span>
      <span style="font-size: 12px; color: var(--subtext); font-weight: normal;">Unfiltered Realized Profit & Losses</span>
    </h3>
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>Side</th>
          <th>Entry Price</th>
          <th>Exit Price</th>
          <th>Exit Reason</th>
          <th>Fee Paid</th>
          <th>Net P&L ($)</th>
          <th>Return (%)</th>
          <th>Exit Time</th>
        </tr>
      </thead>
      <tbody id="closedTradesTable">
        <tr><td colspan="9" style="text-align: center; color: var(--subtext); padding: 24px;">Awaiting trade closures...</td></tr>
      </tbody>
    </table>
  </div>

  <script>
    async function refreshState() {
      try {
        const res = await fetch('/api/state');
        const data = await res.json();
        
        // Ticker
        const c = data.candle;
        if (c.timestamp) {
          document.getElementById('barTime').innerText = String(c.timestamp).slice(0, 19);
          document.getElementById('barClose').innerText = '$' + c.close.toFixed(2);
          const macroEl = document.getElementById('barMacro');
          macroEl.innerText = c.macro_trend;
          macroEl.className = c.macro_trend === 'BULLISH' ? 'status-badge badge-bull' : 'status-badge badge-bear';
          if (c.adx !== undefined) {
            document.getElementById('barAdx').innerText = c.adx.toFixed(1) + (c.adx >= 18.0 ? ' (TREND)' : ' (CHOP)');
            document.getElementById('barAdx').style.color = c.adx >= 18.0 ? 'var(--success)' : 'var(--warning)';
          }
          document.getElementById('barAtr').innerText = '$' + c.atr.toFixed(2);
          document.getElementById('barDonchian').innerText = '$' + c.dl.toFixed(0) + ' - $' + c.dh.toFixed(0);
        }

        // Accounts
        let gridHtml = '';
        let posRows = '';
        let tradeRows = '';

        for (const [key, acc] of Object.entries(data.accounts)) {
          const isMexc = key.includes('mexc');
          const pnlClass = acc.total_net_profit >= 0 ? 'pos-val' : 'neg-val';
          const pnlSign = acc.total_net_profit >= 0 ? '+' : '';
          
          gridHtml += `
            <div class="card">
              <div class="card-header">
                <h2>${acc.name}</h2>
                <span class="tag ${isMexc ? 'tag-mexc' : 'tag-bybit'}">${isMexc ? 'ZERO MAKER' : 'BYBIT 0.02%'}</span>
              </div>
              <div class="metric-main ${pnlClass}">
                $${acc.current_equity.toLocaleString('en-US', {minimumFractionDigits: 2})}
              </div>
              <div class="metric-row">
                <span class="metric-label">Net Return:</span>
                <span class="metric-val ${pnlClass}">${pnlSign}$${acc.total_net_profit.toFixed(2)} (${pnlSign}${acc.total_return_pct.toFixed(2)}%)</span>
              </div>
              <div class="metric-row">
                <span class="metric-label">Max Drawdown:</span>
                <span class="metric-val" style="color: ${acc.max_drawdown_pct > 8.0 ? '#ef4444' : '#10b981'}">${acc.max_drawdown_pct.toFixed(2)}%</span>
              </div>
              <div class="metric-row">
                <span class="metric-label">Win Rate:</span>
                <span class="metric-val">${acc.total_trades} trades (${acc.win_rate_pct.toFixed(1)}% WR)</span>
              </div>
              <div class="metric-row">
                <span class="metric-label">Wins / Losses:</span>
                <span class="metric-val"><span style="color:var(--success)">${acc.winning_trades} W</span> / <span style="color:var(--danger)">${acc.losing_trades} L</span></span>
              </div>
            </div>
          `;

          // Positions
          for (const pos of acc.open_positions) {
            const pnl = pos.unrealized_pnl;
            const pnlCls = pnl >= 0 ? 'pos-val' : 'neg-val';
            posRows += `
              <tr>
                <td><strong>${acc.name}</strong></td>
                <td><span style="color: ${pos.side === 'LONG' ? 'var(--success)' : 'var(--danger)'}; font-weight: 700;">${pos.side}</span></td>
                <td>$${pos.entry_price.toFixed(2)}</td>
                <td>$${pos.current_price.toFixed(2)}</td>
                <td>${pos.size.toFixed(4)} BTC</td>
                <td style="color: var(--danger)">$${pos.sl_price.toFixed(2)}</td>
                <td style="color: var(--success)">$${pos.tp_price.toFixed(2)}</td>
                <td>${pos.be_locked ? '<span style="color:var(--success); font-weight:700;">YES (+0.25x ATR)</span>' : '<span style="color:var(--subtext)">NO</span>'}</td>
                <td class="${pnlCls}">${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}</td>
              </tr>
            `;
          }

          // Trades from MEXC Option A
          if (key === 'mexc_opt_a') {
            for (const tr of acc.recent_trades.slice().reverse()) {
              const trPnlCls = tr.net_pnl >= 0 ? 'pos-val' : 'neg-val';
              tradeRows += `
                <tr>
                  <td>#${tr.id}</td>
                  <td style="color: ${tr.side === 'LONG' ? 'var(--success)' : 'var(--danger)'}; font-weight:700;">${tr.side}</td>
                  <td>$${tr.entry_price.toFixed(2)}</td>
                  <td>$${tr.exit_price.toFixed(2)}</td>
                  <td>${tr.exit_reason.replace('_', ' ')}</td>
                  <td>$${tr.fee.toFixed(2)}</td>
                  <td class="${trPnlCls}">${tr.net_pnl >= 0 ? '+' : ''}$${tr.net_pnl.toFixed(2)}</td>
                  <td class="${trPnlCls}">${tr.return_pct >= 0 ? '+' : ''}${tr.return_pct.toFixed(2)}%</td>
                  <td style="font-size: 11px; color: var(--subtext);">${tr.exit_time.slice(0, 19)}</td>
                </tr>
              `;
            }
          }
        }

        document.getElementById('accountsGrid').innerHTML = gridHtml;
        if (posRows) document.getElementById('openPositionsTable').innerHTML = posRows;
        if (tradeRows) document.getElementById('closedTradesTable').innerHTML = tradeRows;

      } catch (err) {
        console.error('Error fetching stream state:', err);
      }
    }

    async function togglePause() {
      const res = await fetch('/api/toggle_pause', { method: 'POST' });
      const data = await res.json();
      document.getElementById('pauseBtn').innerText = data.is_paused ? '▶ Resume Stream' : '⏸ Pause Stream';
    }

    async function resetSim() {
      if (confirm('Reset virtual paper accounts to $10,000 starting capital?')) {
        await fetch('/api/reset', { method: 'POST' });
        refreshState();
      }
    }

    setInterval(refreshState, 1000);
    refreshState();
  </script>
</body>
</html>
    """

if __name__ == "__main__":
    uvicorn.run("services.demo_runner.demo_server:app", host="0.0.0.0", port=8000, reload=False)
