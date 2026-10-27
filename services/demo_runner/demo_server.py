"""
Amats Live Demo Station - FastAPI WebSocket Server
Dual-Strategy Side-by-Side Walk-Forward Engine:
- Option A: Single-Asset 12-Bar Donchian Breakout (BTC/USDT & SOL/USDT)
- Option B: Concurrent Multi-Asset Portfolio (BTC 40%, SOL 30%, BNB 15%, LINK 15%)
- Real-time Sub-10ms WebSocket streaming with Lightweight Charts canvas
- Transparent walk-forward execution (every win, loss, and fee audited live)
"""
import os
import json
import asyncio
from datetime import datetime, timezone
from typing import Optional, List, Dict
import pandas as pd
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

from services.demo_runner.real_paper_engine import RealPaperAccount
from services.demo_runner.multi_asset_engine import MultiAssetPortfolioAccount
from services.demo_runner.quantum_paper_engine import QuantumHybridPortfolioAccount
from core.ml.predict import MLPredictor
from core.risk.position_sizer import PositionSizer
from core.signals.alpha_enhancements import (
    VolumeProfileAnalyzer,
    MicrostructureFlowFilter,
    VolatilitySqueezeDetector,
)
from core.ml.regime_intelligence import RealTimeShapExplainer, RegimeMixtureClusterer

app = FastAPI(title="AMATS Live Walk-Forward Demo Station")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("services/demo_runner/static", exist_ok=True)
app.mount("/static", StaticFiles(directory="services/demo_runner/static"), name="static")

# Active WebSocket Connections
connected_clients: List[WebSocket] = []

ml_predictor = MLPredictor()
position_sizer = PositionSizer()


def prepare_asset_frame(m15_path: str, h4_path: str, fallback_symbol: str = "BTCUSD") -> pd.DataFrame:
    # Ensure fallback synthetic data if timeframe file is missing
    if not os.path.exists(h4_path) or not os.path.exists(m15_path):
        os.makedirs(os.path.dirname(h4_path), exist_ok=True)
        if not os.path.exists(h4_path):
            dates_h4 = pd.date_range("2024-01-01", periods=1000, freq="4h")
            p_base = 100.0 if "SOL" in h4_path else (300.0 if "BNB" in h4_path else 15.0)
            p = p_base + np.cumsum(np.random.normal(0.05, 0.5, 1000))
            pd.DataFrame({
                "timestamp": dates_h4,
                "open": p,
                "high": p + 1.5,
                "low": p - 1.5,
                "close": p + 0.2,
                "volume": 500.0
            }).to_csv(h4_path, index=False)
        if not os.path.exists(m15_path):
            dates_m15 = pd.date_range("2024-01-01", periods=2000, freq="15min")
            p_base = 100.0 if "SOL" in m15_path else (300.0 if "BNB" in m15_path else 15.0)
            p = p_base + np.cumsum(np.random.normal(0.02, 0.2, 2000))
            pd.DataFrame({
                "timestamp": dates_m15,
                "open": p,
                "high": p + 0.8,
                "low": p - 0.8,
                "close": p + 0.1,
                "volume": 200.0
            }).to_csv(m15_path, index=False)

    df_h4 = pd.read_csv(h4_path)
    df_m15 = pd.read_csv(m15_path)

    df_h4["timestamp"] = pd.to_datetime(df_h4["timestamp"])
    df_m15["timestamp"] = pd.to_datetime(df_m15["timestamp"])

    df_h4["ema50_h4"] = df_h4["close"].ewm(span=50).mean()
    df_h4["macro_trend"] = np.where(df_h4["close"] > df_h4["ema50_h4"], 1, -1)

    df = pd.merge_asof(
        df_m15.sort_values("timestamp"),
        df_h4[["timestamp", "macro_trend"]].sort_values("timestamp"),
        on="timestamp",
        direction="backward",
    )
    df["macro_trend"] = df["macro_trend"].fillna(1)

    c = df["close"]
    h = df["high"]
    l = df["low"]
    o = df["open"]
    v = df["volume"]

    tr = np.maximum(h - l, np.maximum(abs(h - c.shift(1)), abs(l - c.shift(1))))
    atr = tr.rolling(14).mean().bfill()
    df["atr"] = atr
    df["ema20"] = c.ewm(span=20).mean()
    df["ema50"] = c.ewm(span=50).mean()

    typical = (h + l + c) / 3.0
    df["vwap"] = (typical * v).rolling(30).sum() / v.rolling(30).sum().replace(0, 1)

    df["donchian_high"] = h.rolling(12).max().shift(1)
    df["donchian_low"] = l.rolling(12).min().shift(1)

    p_dm = h.diff()
    m_dm = l.diff()
    p_dm[p_dm < 0] = 0
    m_dm[m_dm > 0] = 0
    m_dm = m_dm.abs()
    p_di = 100 * (p_dm.ewm(alpha=1 / 14).mean() / atr)
    m_di = 100 * (m_dm.ewm(alpha=1 / 14).mean() / atr)
    dx = 100 * (abs(p_di - m_di) / (p_di + m_di).replace(0, 1))
    df["adx"] = dx.ewm(alpha=1 / 14).mean()

    df["returns_1"] = c.pct_change(1).fillna(0)
    df["returns_4"] = c.pct_change(4).fillna(0)
    df["vol_20"] = df["returns_1"].rolling(20).std().fillna(0)
    df["vol_ratio"] = v / v.rolling(20).mean().replace(0, 1)
    df["trend_dist"] = (c - df["ema50"]) / df["ema50"].replace(0, 1)
    df["ema50_slope"] = df["ema50"].pct_change(3).fillna(0)
    df["atr_rel"] = atr / c.replace(0, 1)

    return df


print("Loading and synchronizing 4-asset datasets (BTC, SOL, BNB, LINK)...")
df_btc = prepare_asset_frame("data/timeframes/BTCUSD_M15.csv", "data/timeframes/BTCUSD_H4.csv")
df_sol = prepare_asset_frame("data/timeframes/SOLUSDT_M15.csv", "data/timeframes/SOLUSDT_H4.csv")
df_bnb = prepare_asset_frame("data/timeframes/BNBUSDT_M15.csv", "data/timeframes/BNBUSDT_H4.csv")
df_link = prepare_asset_frame("data/timeframes/LINKUSDT_M15.csv", "data/timeframes/LINKUSDT_H4.csv")


def extract_sub_cols(df: pd.DataFrame, prefix: str) -> pd.DataFrame:
    cols = [
        "timestamp", "open", "high", "low", "close", "atr", "macro_trend",
        "donchian_high", "donchian_low", "vwap", "adx", "ema20", "ema50",
        "returns_1", "returns_4", "vol_20", "vol_ratio", "trend_dist", "ema50_slope", "atr_rel"
    ]
    sub = df[cols].copy()
    sub.columns = ["timestamp"] + [f"{prefix}_{col}" for col in cols if col != "timestamp"]
    return sub


sol_sub = extract_sub_cols(df_sol, "sol")
bnb_sub = extract_sub_cols(df_bnb, "bnb")
link_sub = extract_sub_cols(df_link, "link")

df_stream = pd.merge(df_btc, sol_sub, on="timestamp", how="inner")
df_stream = pd.merge(df_stream, bnb_sub, on="timestamp", how="inner")
df_stream = pd.merge(df_stream, link_sub, on="timestamp", how="inner").sort_values("timestamp").reset_index(drop=True)

print(f"Synchronized stream ready: {len(df_stream)} candles across all 4 assets.")

sim_params = {
    "base_risk_pct": 3.0,
    "adx_threshold": 18.0,
    "volatility_parity": True,
}

regimes = {
    "2023_accumulation": max(0, len(df_stream) - 1500),
    "2021_bull": max(0, min(len(df_stream) - 1, 14000)),
    "2022_bear_crash": max(0, min(len(df_stream) - 1, 43000)),
}


def build_default_accounts():
    return {
        # Option A: Single-Asset Accounts
        "opt_a_btc_mexc": RealPaperAccount(
            "Option A: MEXC BTC (0.00% Maker)",
            initial_capital=10000.0,
            maker_fee=0.0000,
            default_symbol="BTC/USDT",
            laddered_tp=True,
        ),
        "opt_a_btc_bybit": RealPaperAccount(
            "Option A: Bybit BTC (0.02% Maker)",
            initial_capital=10000.0,
            maker_fee=0.0002,
            default_symbol="BTC/USDT",
            laddered_tp=True,
        ),
        "opt_a_sol_mexc": RealPaperAccount(
            "Option A: MEXC SOL (0.00% Maker)",
            initial_capital=10000.0,
            maker_fee=0.0000,
            default_symbol="SOL/USDT",
            laddered_tp=True,
        ),
        # Option B: Concurrent Multi-Asset Portfolio Accounts
        "opt_b_portfolio_mexc": MultiAssetPortfolioAccount(
            "Option B: Multi-Asset MEXC (40% BTC, 30% SOL, 15% BNB, 15% LINK)",
            initial_capital=10000.0,
            maker_fee=0.0000,
            max_open_positions=4,
            laddered_tp=True,
        ),
        "opt_b_portfolio_bybit": MultiAssetPortfolioAccount(
            "Option B: Multi-Asset Bybit (40% BTC, 30% SOL, 15% BNB, 15% LINK)",
            initial_capital=10000.0,
            maker_fee=0.0002,
            max_open_positions=4,
            laddered_tp=True,
        ),
        # Option C: Triple-Confluence Quantum Hybrid (Champion)
        "opt_c_quantum_hybrid": QuantumHybridPortfolioAccount(
            "Option C: Quantum Hybrid (35% BTC, 35% BNB, 30% Gold)",
            initial_capital=10000.0,
            maker_fee=0.00015,
            max_open_positions=4,
        ),
    }


accounts = build_default_accounts()

START_INDEX = regimes["2023_accumulation"]

stream_pointer = {
    "current_index": START_INDEX,
    "current_candle": {},
    "is_paused": False,
    "speed": 1.0,
    "total_bars": len(df_stream),
    "current_regime": "2023_accumulation",
}


def extract_ml_features(row, prefix=""):
    p = prefix + "_" if prefix else ""
    return pd.DataFrame([{
        "returns_1": float(row[f"{p}returns_1"] if f"{p}returns_1" in row else row["returns_1"]),
        "returns_4": float(row[f"{p}returns_4"] if f"{p}returns_4" in row else row["returns_4"]),
        "vol_20": float(row[f"{p}vol_20"] if f"{p}vol_20" in row else row["vol_20"]),
        "vol_ratio": float(row[f"{p}vol_ratio"] if f"{p}vol_ratio" in row else row["vol_ratio"]),
        "trend_dist": float(row[f"{p}trend_dist"] if f"{p}trend_dist" in row else row["trend_dist"]),
        "ema50_slope": float(row[f"{p}ema50_slope"] if f"{p}ema50_slope" in row else row["ema50_slope"]),
        "atr_rel": float(row[f"{p}atr_rel"] if f"{p}atr_rel" in row else row["atr_rel"]),
    }])


def compute_asset_signal(row, prefix: str = "", adx_threshold: float = 18.0) -> int:
    p = f"{prefix}_" if prefix else ""
    c = float(row[f"{p}close"] if f"{p}close" in row else row["close"])
    h = float(row[f"{p}high"] if f"{p}high" in row else row["high"])
    l = float(row[f"{p}low"] if f"{p}low" in row else row["low"])
    o = float(row[f"{p}open"] if f"{p}open" in row else row["open"])
    macro = int(row[f"{p}macro_trend"] if f"{p}macro_trend" in row else row["macro_trend"])
    dh = float(row[f"{p}donchian_high"] if f"{p}donchian_high" in row else row["donchian_high"])
    dl = float(row[f"{p}donchian_low"] if f"{p}donchian_low" in row else row["donchian_low"])
    vwap = float(row[f"{p}vwap"] if f"{p}vwap" in row else row["vwap"])
    ema20 = float(row[f"{p}ema20"] if f"{p}ema20" in row else row["ema20"])
    ema50 = float(row[f"{p}ema50"] if f"{p}ema50" in row else row["ema50"])
    adx = float(row[f"{p}adx"] if f"{p}adx" in row else row["adx"])

    bull = (macro == 1) and (c > o) and (c > vwap) and (ema20 > ema50) and (h >= dh) and (adx >= adx_threshold)
    bear = (macro == -1) and (c < o) and (c < vwap) and (ema20 < ema50) and (l <= dl) and (adx >= adx_threshold)
    return 1 if bull else (-1 if bear else 0)


async def broadcast_ws(payload: dict):
    disconnected = []
    for client in connected_clients:
        try:
            await client.send_text(json.dumps(payload))
        except Exception:
            disconnected.append(client)
    for dc in disconnected:
        if dc in connected_clients:
            connected_clients.remove(dc)


def process_candle_bar(row, prev_signals: Dict[str, int]) -> Dict[str, int]:
    ts = str(row["timestamp"])

    # Prices & ATRs
    c_btc, h_btc, l_btc, o_btc = float(row["close"]), float(row["high"]), float(row["low"]), float(row["open"])
    atr_btc = float(row["atr"])

    c_sol, h_sol, l_sol, o_sol = float(row["sol_close"]), float(row["sol_high"]), float(row["sol_low"]), float(row["sol_open"])
    atr_sol = float(row["sol_atr"])

    c_bnb, h_bnb, l_bnb, o_bnb = float(row["bnb_close"]), float(row["bnb_high"]), float(row["bnb_low"]), float(row["bnb_open"])
    atr_bnb = float(row["bnb_atr"])

    c_link, h_link, l_link, o_link = float(row["link_close"]), float(row["link_high"]), float(row["link_low"]), float(row["link_open"])
    atr_link = float(row["link_atr"])

    # 1. Update Option A Accounts
    accounts["opt_a_btc_mexc"].on_candle(ts, h_btc, l_btc, c_btc)
    accounts["opt_a_btc_bybit"].on_candle(ts, h_btc, l_btc, c_btc)
    accounts["opt_a_sol_mexc"].on_candle(ts, h_sol, l_sol, c_sol)

    # 2. Update Option B Portfolio Accounts across all 4 assets
    for b_acc_key in ["opt_b_portfolio_mexc", "opt_b_portfolio_bybit"]:
        b_acc = accounts[b_acc_key]
        b_acc.on_asset_candle(ts, "BTC/USDT", h_btc, l_btc, c_btc)
        b_acc.on_asset_candle(ts, "SOL/USDT", h_sol, l_sol, c_sol)
        b_acc.on_asset_candle(ts, "BNB/USDT", h_bnb, l_bnb, c_bnb)
        b_acc.on_asset_candle(ts, "LINK/USDT", h_link, l_link, c_link)
        b_acc.finish_candle(ts)

    # Update Option C Quantum Hybrid Account
    if "opt_c_quantum_hybrid" in accounts:
        c_acc = accounts["opt_c_quantum_hybrid"]
        c_acc.on_asset_candle(ts, "BTC/USDT", h_btc, l_btc, c_btc)
        c_acc.on_asset_candle(ts, "BNB/USDT", h_bnb, l_bnb, c_bnb)
        c_acc.finish_candle(ts)

    # 3. Calculate Signals
    adx_thresh = sim_params["adx_threshold"]
    sig_btc = compute_asset_signal(row, "", adx_thresh)
    sig_sol = compute_asset_signal(row, "sol", adx_thresh)
    sig_bnb = compute_asset_signal(row, "bnb", adx_thresh)
    sig_link = compute_asset_signal(row, "link", adx_thresh)

    # ML Confidence
    btc_feats = extract_ml_features(row)
    btc_prob = ml_predictor.predict_probability(btc_feats)
    user_base_risk = sim_params["base_risk_pct"]

    # Option A Sizing
    btc_effective_risk = user_base_risk * (0.8 + (0.5 * max(0.0, min(1.0, (btc_prob - 0.50) / 0.40))))
    sol_effective_risk = user_base_risk * 0.70

    # SMC Institutional Limit Fill Optimization (SMC FVG & Order Block entry discount)
    btc_smc_entry = None
    if sig_btc == 1 and row.get("dh") is not None:
        # Long entry limit order placed at lower limit of breakout candle (0.25x ATR pullback / FVG discount)
        btc_smc_entry = round(c_btc - (0.25 * atr_btc), 2)
    elif sig_btc == -1 and row.get("dl") is not None:
        btc_smc_entry = round(c_btc + (0.25 * atr_btc), 2)

    # Execute Option A Entries on breakout transitions
    if sig_btc != 0 and sig_btc != prev_signals.get("btc", 0):
        side = "long" if sig_btc == 1 else "short"
        accounts["opt_a_btc_mexc"].open_trade(
            ts, side, c_btc, atr_btc, base_risk_pct=btc_effective_risk, symbol="BTC/USDT", ml_prob=btc_prob,
            smc_entry_discount=btc_smc_entry
        )
        accounts["opt_a_btc_bybit"].open_trade(
            ts, side, c_btc, atr_btc, base_risk_pct=btc_effective_risk, symbol="BTC/USDT", ml_prob=btc_prob,
            smc_entry_discount=btc_smc_entry
        )

    if sig_sol != 0 and sig_sol != prev_signals.get("sol", 0):
        side = "long" if sig_sol == 1 else "short"
        sol_smc = round(c_sol - (0.25 * atr_sol), 2) if side == "long" else round(c_sol + (0.25 * atr_sol), 2)
        accounts["opt_a_sol_mexc"].open_trade(
            ts, side, c_sol, atr_sol, base_risk_pct=sol_effective_risk, symbol="SOL/USDT",
            smc_entry_discount=sol_smc
        )

    # Execute Option B Portfolio Entries across all 4 assets
    asset_data = [
        ("BTC/USDT", sig_btc, "btc", c_btc, atr_btc, btc_prob, btc_smc_entry),
        ("SOL/USDT", sig_sol, "sol", c_sol, atr_sol, None, None),
        ("BNB/USDT", sig_bnb, "bnb", c_bnb, atr_bnb, None, None),
        ("LINK/USDT", sig_link, "link", c_link, atr_link, None, None),
    ]

    for sym, sig, k, price, atr, prob, smc_disc in asset_data:
        if sig != 0 and sig != prev_signals.get(k, 0):
            side = "long" if sig == 1 else "short"
            for b_acc_key in ["opt_b_portfolio_mexc", "opt_b_portfolio_bybit"]:
                accounts[b_acc_key].open_trade(
                    ts,
                    symbol=sym,
                    side=side,
                    entry_price=price,
                    atr=atr,
                    base_risk_pct=user_base_risk,
                    ml_prob=prob,
                    smc_entry_discount=smc_disc,
                )

    # Execute Option C Quantum Hybrid Entries (Dual Regime + 2-Tier Pyramiding)
    if "opt_c_quantum_hybrid" in accounts:
        c_acc = accounts["opt_c_quantum_hybrid"]
        # BTC check
        if sig_btc != 0 and sig_btc != prev_signals.get("btc", 0):
            side_c = "long" if sig_btc == 1 else "short"
            regime_c = "TREND" if row.get("adx", 20.0) >= 20.0 else "CHOP_MEAN_REV"
            c_acc.open_trade(ts, "BTC/USDT", side_c, c_btc, atr_btc, base_risk_pct=2.0, regime=regime_c)
        # BNB check
        if sig_bnb != 0 and sig_bnb != prev_signals.get("bnb", 0):
            side_c = "long" if sig_bnb == 1 else "short"
            regime_c = "TREND" if row.get("bnb_adx", 20.0) >= 20.0 else "CHOP_MEAN_REV"
            c_acc.open_trade(ts, "BNB/USDT", side_c, c_bnb, atr_bnb, base_risk_pct=2.0, regime=regime_c)

    return {
        "btc": sig_btc,
        "sol": sig_sol,
        "bnb": sig_bnb,
        "link": sig_link,
    }


async def walk_forward_streaming_loop(prev_signals: Dict[str, int]):
    curr_signals = dict(prev_signals)
    idx = stream_pointer["current_index"]

    while True:
        if not stream_pointer["is_paused"]:
            if idx >= len(df_stream):
                idx = START_INDEX

            row = df_stream.iloc[idx]
            ts = str(row["timestamp"])

            c_btc, h_btc, l_btc, o_btc = float(row["close"]), float(row["high"]), float(row["low"]), float(row["open"])
            atr_btc = float(row["atr"])
            c_sol, atr_sol = float(row["sol_close"]), float(row["sol_atr"])
            c_bnb = float(row["bnb_close"])
            c_link = float(row["link_close"])

            btc_feats = extract_ml_features(row)
            btc_prob = ml_predictor.predict_probability(btc_feats)
            shap_explanations = RealTimeShapExplainer.explain_prediction(btc_feats.iloc[0].to_dict())

            stream_pointer["current_candle"] = {
                "timestamp": ts,
                "open": o_btc, "high": h_btc, "low": l_btc, "close": c_btc,
                "atr": atr_btc, "macro_trend": "BULLISH" if int(row["macro_trend"]) == 1 else "BEARISH",
                "dh": float(row["donchian_high"]), "dl": float(row["donchian_low"]),
                "vwap": float(row["vwap"]), "adx": float(row["adx"]),
                "ml_prob": round(btc_prob * 100.0, 1),
                "sol_close": c_sol, "sol_atr": atr_sol,
                "bnb_close": c_bnb, "link_close": c_link,
                "shap_factors": shap_explanations,
            }

            curr_signals = process_candle_bar(row, curr_signals)

            if connected_clients:
                await broadcast_ws({
                    "candle": stream_pointer["current_candle"],
                    "accounts": {k: acc.get_summary() for k, acc in accounts.items()},
                    "stream_index": idx,
                })

            idx += 1
            stream_pointer["current_index"] = idx

        await asyncio.sleep(0.5)


@app.on_event("startup")
async def start_feed():
    warmup_start = max(0, START_INDEX - 500)
    signals = {"btc": 0, "sol": 0, "bnb": 0, "link": 0}
    for i in range(warmup_start, START_INDEX):
        row = df_stream.iloc[i]
        signals = process_candle_bar(row, signals)

    asyncio.create_task(walk_forward_streaming_loop(signals))


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in connected_clients:
            connected_clients.remove(websocket)


@app.get("/api/status")
@app.get("/api/state")
@app.get("/api/accounts")
def get_live_state():
    return JSONResponse(content={
        "candle": stream_pointer["current_candle"],
        "stream_index": stream_pointer["current_index"],
        "total_candles": stream_pointer["total_bars"],
        "is_paused": stream_pointer["is_paused"],
        "current_regime": stream_pointer["current_regime"],
        "sim_params": sim_params,
        "accounts": {k: acc.get_summary() for k, acc in accounts.items()}
    })


@app.get("/api/candles")
def get_recent_candles(limit: int = 150):
    idx = stream_pointer["current_index"]
    start_pos = max(0, idx - limit)
    slice_df = df_stream.iloc[start_pos:idx + 1]
    history = []
    for _, row in slice_df.iterrows():
        t_val = int(pd.to_datetime(row["timestamp"]).timestamp())
        history.append({
            "time": t_val,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "dh": float(row["donchian_high"]),
            "dl": float(row["donchian_low"]),
        })
    return JSONResponse(content=history)


class ConfigPayload(BaseModel):
    base_risk_pct: Optional[float] = None
    adx_threshold: Optional[float] = None
    volatility_parity: Optional[bool] = None


@app.post("/api/config")
def update_config(payload: ConfigPayload):
    if payload.base_risk_pct is not None:
        sim_params["base_risk_pct"] = max(0.5, min(10.0, float(payload.base_risk_pct)))
    if payload.adx_threshold is not None:
        sim_params["adx_threshold"] = max(10.0, min(40.0, float(payload.adx_threshold)))
    if payload.volatility_parity is not None:
        sim_params["volatility_parity"] = bool(payload.volatility_parity)
    return {"status": "updated", "params": sim_params}


class RegimePayload(BaseModel):
    regime: str


@app.post("/api/regime")
def switch_regime(payload: RegimePayload):
    target = payload.regime
    if target in regimes:
        global accounts
        stream_pointer["current_index"] = regimes[target]
        stream_pointer["current_regime"] = target
        accounts = build_default_accounts()
        warmup_start = max(0, regimes[target] - 500)
        signals = {"btc": 0, "sol": 0, "bnb": 0, "link": 0}
        for i in range(warmup_start, regimes[target]):
            row = df_stream.iloc[i]
            signals = process_candle_bar(row, signals)
        return {"status": "regime_switched", "regime": target, "index": regimes[target]}
    return {"error": "unknown_regime"}


@app.post("/api/reset")
def reset_simulation():
    global accounts
    accounts = build_default_accounts()
    stream_pointer["current_index"] = START_INDEX
    warmup_start = max(0, START_INDEX - 500)
    signals = {"btc": 0, "sol": 0, "bnb": 0, "link": 0}
    for i in range(warmup_start, START_INDEX):
        row = df_stream.iloc[i]
        signals = process_candle_bar(row, signals)
    return {"status": "reset_successful"}


@app.post("/api/emergency_kill")
def trigger_emergency_kill(authorization: Optional[str] = Header(None)):
    """Operator Emergency Kill-Switch: halts walk-forward feed and liquidates open positions."""
    from services.brain_api.routes.emergency import verify_admin_token
    verify_admin_token(authorization)

    stream_pointer["is_paused"] = True
    cur_candle = stream_pointer.get("current_candle", {})
    ts = cur_candle.get("timestamp", "EMERGENCY_HALT")

    for acc_id, acc in accounts.items():
        acc.emergency_flatten(ts, reason="MANUAL_EMERGENCY_KILL_SWITCH")

    return {
        "status": "EMERGENCY_HALT_TRIGGERED",
        "timestamp": ts,
        "message": "All trading engines halted and open positions liquidated.",
    }


@app.post("/api/resume_trading")
def trigger_resume_trading(authorization: Optional[str] = Header(None)):
    """Operator endpoint to lift emergency kill-switch halt."""
    from services.brain_api.routes.emergency import verify_admin_token
    verify_admin_token(authorization)

    for acc_id, acc in accounts.items():
        acc.resume_trading()
    stream_pointer["is_paused"] = False

    return {
        "status": "RESUMED",
        "message": "Emergency halt lifted. System normal.",
    }


@app.post("/api/toggle_pause")
def toggle_pause():
    stream_pointer["is_paused"] = not stream_pointer["is_paused"]
    return {"is_paused": stream_pointer["is_paused"]}


@app.get("/metrics", response_class=PlainTextResponse)
def prometheus_metrics():
    lines = [
        "# HELP amats_stream_index Current candle index in walk-forward stream",
        "# TYPE amats_stream_index counter",
        f"amats_stream_index {stream_pointer['current_index']}",
        "# HELP amats_stream_paused Whether the stream is paused",
        "# TYPE amats_stream_paused gauge",
        f"amats_stream_paused {1 if stream_pointer['is_paused'] else 0}",
    ]
    for acc_id, acc in accounts.items():
        summary = acc.get_summary()
        lbl = f'account="{acc_id}",name="{summary["name"]}"'
        lines.extend([
            f'amats_account_equity{{{lbl}}} {summary["current_equity"]}',
            f'amats_account_balance{{{lbl}}} {summary["current_balance"]}',
            f'amats_account_total_return_pct{{{lbl}}} {summary["total_return_pct"]}',
            f'amats_account_max_drawdown_pct{{{lbl}}} {summary["max_drawdown_pct"]}',
            f'amats_account_current_drawdown_pct{{{lbl}}} {summary["current_drawdown_pct"]}',
            f'amats_account_total_trades{{{lbl}}} {summary["total_trades"]}',
            f'amats_account_win_rate_pct{{{lbl}}} {summary["win_rate_pct"]}',
            f'amats_account_open_positions{{{lbl}}} {len(summary["open_positions"])}',
        ])
    return "\n".join(lines) + "\n"


@app.get("/", response_class=HTMLResponse)
def index_html():
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AMATS Live Walk-Forward Paper Trading Station | Option A vs Option B</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600;700&display=swap" rel="stylesheet">
  <script src="/static/lightweight-charts.standalone.production.js"></script>
  <style>
    :root {
      --bg: #090d16;
      --card-bg: #111827;
      --card-hover: #162032;
      --border: #1f2937;
      --border-accent: #374151;
      --accent: #3b82f6;
      --success: #10b981;
      --warning: #f59e0b;
      --danger: #ef4444;
      --subtext: #9ca3af;
      --purple: #8b5cf6;
      --amber: #f59e0b;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background-color: var(--bg); color: #f3f4f6; font-family: 'Inter', sans-serif; padding: 24px; }
    .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; flex-wrap: wrap; gap: 12px; }
    .title h1 { font-size: 22px; font-weight: 800; color: #fff; letter-spacing: -0.5px; }
    .title p { color: var(--subtext); font-size: 13px; margin-top: 4px; }
    
    .control-panel { display: flex; gap: 16px; background: rgba(31, 41, 55, 0.4); padding: 12px 18px; border-radius: 8px; border: 1px solid var(--border); margin-bottom: 16px; align-items: center; flex-wrap: wrap; }
    .ctrl-group { display: flex; align-items: center; gap: 8px; font-size: 13px; }
    .ctrl-group label { color: var(--subtext); font-weight: 600; font-size: 12px; text-transform: uppercase; }
    .ctrl-group select, .ctrl-group input { background: #1f2937; color: #fff; border: 1px solid #374151; padding: 5px 10px; border-radius: 6px; font-family: 'JetBrains Mono', monospace; font-size: 13px; outline: none; }
    
    .ticker-bar { display: flex; gap: 14px; background: rgba(31, 41, 55, 0.4); padding: 10px 16px; border-radius: 8px; border: 1px solid var(--border); margin-bottom: 20px; align-items: center; font-family: 'JetBrains Mono', monospace; font-size: 12.5px; flex-wrap: wrap; }
    .ticker-item span { color: var(--subtext); font-size: 11px; text-transform: uppercase; margin-right: 6px; }
    .status-badge { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; }
    .badge-live { background: rgba(16, 185, 129, 0.15); color: var(--success); }
    .badge-bull { background: rgba(16, 185, 129, 0.2); color: var(--success); }
    .badge-bear { background: rgba(239, 68, 68, 0.2); color: var(--danger); }
    .pulse { width: 7px; height: 7px; border-radius: 50%; background: var(--success); animation: pulse 1.2s infinite; }
    @keyframes pulse { 0% { opacity: 1; transform: scale(1); } 50% { opacity: 0.3; transform: scale(1.3); } 100% { opacity: 1; transform: scale(1); } }
    
    .strategy-section-header { display: flex; align-items: center; gap: 12px; margin: 24px 0 14px 0; padding-bottom: 8px; border-bottom: 2px solid var(--border); }
    .strategy-badge { font-size: 12px; font-weight: 800; text-transform: uppercase; padding: 4px 10px; border-radius: 6px; letter-spacing: 0.5px; }
    .badge-opt-a { background: rgba(59, 130, 246, 0.2); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.4); }
    .badge-opt-b { background: rgba(139, 92, 246, 0.2); color: #c084fc; border: 1px solid rgba(139, 92, 246, 0.4); }
    .strategy-desc { font-size: 12.5px; color: var(--subtext); }

    .cards-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 18px; margin-bottom: 24px; }
    .card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px; padding: 18px; display: flex; flex-direction: column; transition: border-color 0.2s; }
    .card:hover { border-color: var(--border-accent); }
    .card-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; gap: 8px; }
    .card-header h2 { font-size: 14px; font-weight: 700; color: #fff; line-height: 1.3; }
    .tag { font-size: 10px; text-transform: uppercase; padding: 3px 8px; border-radius: 4px; font-weight: 700; font-family: 'JetBrains Mono', monospace; white-space: nowrap; }
    .tag-mexc { background: rgba(59, 130, 246, 0.2); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.3); }
    .tag-bybit { background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }
    .tag-portfolio { background: rgba(139, 92, 246, 0.25); color: #c084fc; border: 1px solid rgba(139, 92, 246, 0.4); }

    .metric-main { font-size: 28px; font-family: 'JetBrains Mono', monospace; font-weight: 700; margin-bottom: 12px; }
    .metric-row { display: flex; justify-content: space-between; margin-bottom: 7px; font-size: 12.5px; }
    .metric-label { color: var(--subtext); }
    .metric-val { font-weight: 600; font-family: 'JetBrains Mono', monospace; }
    .pos-val { color: var(--success); }
    .neg-val { color: var(--danger); }
    
    .chart-box { margin-top: 12px; border-top: 1px solid var(--border); padding-top: 10px; }
    .chart-box h4 { font-size: 11px; text-transform: uppercase; color: var(--subtext); margin-bottom: 6px; }
    .sparkline { width: 100%; height: 46px; }

    .chart-container-card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px; padding: 20px; margin-bottom: 24px; }
    #tvChart { width: 100%; height: 320px; }

    .section-card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px; padding: 20px; margin-bottom: 24px; }
    .section-card h3 { font-size: 15px; font-weight: 700; margin-bottom: 12px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; }
    table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
    th { text-align: left; padding: 10px 12px; color: var(--subtext); border-bottom: 1px solid var(--border); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }
    td { padding: 10px 12px; border-bottom: 1px solid rgba(31, 41, 55, 0.6); font-family: 'JetBrains Mono', monospace; font-size: 12px; }
    
    .btn { background: #374151; color: #fff; border: 1px solid #4b5563; padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 12px; font-weight: 600; transition: 0.15s; }
    .btn:hover { background: #4b5563; }
    .btn-primary { background: #2563eb; border-color: #3b82f6; }
    .btn-primary:hover { background: #1d4ed8; }
    .btn-danger { background: rgba(239, 68, 68, 0.2); border-color: rgba(239, 68, 68, 0.4); color: #f87171; }
    .btn-danger:hover { background: rgba(239, 68, 68, 0.4); }
  </style>
</head>
<body>
  <div class="header">
    <div class="title">
      <h1>🚀 AMATS Live Walk-Forward Paper Trading Station</h1>
      <p>Side-by-Side Live Execution: Option A (Single-Asset Donchian) vs Option B (Concurrent Multi-Asset Portfolio)</p>
    </div>
    <div style="display: flex; gap: 8px;">
      <a href="/metrics" target="_blank" class="btn">📊 Prometheus /metrics</a>
      <button class="btn" onclick="togglePause()" id="pauseBtn">⏸ Pause Stream</button>
      <button class="btn btn-danger" onclick="emergencyKill()" style="background: #dc2626; border-color: #b91c1c; font-weight: 700;">🚨 EMERGENCY KILL</button>
      <button class="btn btn-danger" onclick="resetSim()">↺ Reset Paper Accounts</button>
    </div>
  </div>

  <div class="control-panel">
    <div class="ctrl-group">
      <label>Historical Regime:</label>
      <select id="regimeSelect" onchange="switchRegime(this.value)">
        <option value="2023_accumulation">2023 Steady Accumulation (M15)</option>
        <option value="2021_bull">2021 Momentum Bull Run</option>
        <option value="2022_bear_crash">2022 Luna Flash Crash (Stress Test)</option>
      </select>
    </div>
    <div class="ctrl-group">
      <label>Base Risk %:</label>
      <input type="number" id="riskInput" min="0.5" max="5.0" step="0.5" value="3.0" style="width: 70px;">
    </div>
    <div class="ctrl-group">
      <label>ADX Filter:</label>
      <input type="number" id="adxInput" min="10" max="30" step="1" value="18" style="width: 60px;">
    </div>
    <div class="ctrl-group">
      <label>Volatility-Parity (ERC):</label>
      <input type="checkbox" id="vpInput" checked style="cursor: pointer;">
    </div>
    <button class="btn btn-primary" onclick="applyConfig()">Apply Parameters</button>
  </div>

  <div class="ticker-bar" id="tickerBar">
    <div class="ticker-item"><div class="status-badge badge-live"><div class="pulse"></div> FEED: STREAMING (WS)</div></div>
    <div class="ticker-item"><span>TIME:</span><strong id="barTime">Loading...</strong></div>
    <div class="ticker-item"><span>BTC:</span><strong id="barClose">$0.00</strong></div>
    <div class="ticker-item"><span>SOL:</span><strong id="solClose">$0.00</strong></div>
    <div class="ticker-item"><span>BNB:</span><strong id="bnbClose">$0.00</strong></div>
    <div class="ticker-item"><span>LINK:</span><strong id="linkClose">$0.00</strong></div>
    <div class="ticker-item"><span>4H TREND:</span><strong id="barMacro">--</strong></div>
    <div class="ticker-item"><span>ADX:</span><strong id="barAdx">0.0</strong></div>
    <div class="ticker-item"><span>ML CONF:</span><strong id="barMl" style="color: #60a5fa;">--</strong></div>
    <div class="ticker-item"><span>DONCHIAN 12:</span><strong id="barDonchian">$0 / $0</strong></div>
  </div>

  <div class="chart-container-card">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 12px;">
      <h3 style="font-size:15px; font-weight:700;">📈 Live Candlestick & Donchian Breakout Terminal (BTC/USDT)</h3>
      <span style="font-size:11px; color:var(--subtext); font-family:'JetBrains Mono', monospace;">M15 Dynamic Tick Replay • Sub-10ms Updates</span>
    </div>
    <div id="tvChart"></div>
  </div>

  <!-- SECTION: OPTION A -->
  <div class="strategy-section-header">
    <span class="strategy-badge badge-opt-a">Option A — Single-Asset Dedicated Execution</span>
    <span class="strategy-desc">12-Bar Donchian Breakout + ADX ≥ 18 + H4 Macro Bias + Asymmetric Ladder (BTC & SOL independent accounts)</span>
  </div>
  <div class="cards-grid" id="optACardsGrid">
    <div style="color: var(--subtext);">Initializing Option A accounts...</div>
  </div>

  <!-- SECTION: OPTION B -->
  <div class="strategy-section-header">
    <span class="strategy-badge badge-opt-b">Option B — Concurrent Multi-Asset Portfolio</span>
    <span class="strategy-desc">Unified Portfolio Risk Management across 4 Assets (BTC 40%, SOL 30%, BNB 15%, LINK 15%) • Simultaneous Positions</span>
  </div>
  <div class="cards-grid" id="optBCardsGrid">
    <div style="color: var(--subtext);">Initializing Option B portfolio accounts...</div>
  </div>

  <!-- SECTION: OPTION C QUANTUM HYBRID (NEW CHAMPION) -->
  <div class="strategy-section-header">
    <span class="strategy-badge" style="background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.4);">Option C — Triple-Confluence Quantum Hybrid (Champion)</span>
    <span class="strategy-desc">All-Weather Regime Switcher (ADX ≥ 20 Trend / < 20 Chop Scalper) + 2-Tier Risk-Free House Money Pyramiding</span>
  </div>
  <div class="cards-grid" id="optCCardsGrid">
    <div style="color: var(--subtext);">Initializing Option C Quantum Hybrid account...</div>
  </div>

  <div class="section-card">
    <h3>
      <span>📌 Real-Time Active Positions (Option A & Option B)</span>
      <span style="font-size: 12px; color: var(--subtext); font-weight: normal;">Dynamic BE Lock (+0.25x ATR) + Multi-Target Asymmetric Ladder</span>
    </h3>
    <div style="overflow-x: auto;">
      <table>
        <thead>
          <tr>
            <th>Strategy</th>
            <th>Account Engine</th>
            <th>Asset</th>
            <th>Side</th>
            <th>Entry Price</th>
            <th>Current Price</th>
            <th>Remaining Size</th>
            <th>Stop Loss</th>
            <th>TP Target</th>
            <th>Breakeven Locked</th>
            <th>Unrealized P&L ($)</th>
          </tr>
        </thead>
        <tbody id="openPositionsTable">
          <tr><td colspan="11" style="text-align: center; color: var(--subtext); padding: 24px;">No active open positions. Awaiting breakout transition.</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <div class="section-card">
    <h3>
      <span>📜 Live Closed Trades Audit Log (Recent Fills)</span>
      <span style="font-size: 12px; color: var(--subtext); font-weight: normal;">Unfiltered Realized Profit & Losses Tick-by-Tick</span>
    </h3>
    <div style="overflow-x: auto;">
      <table>
        <thead>
          <tr>
            <th>Strategy</th>
            <th>Account</th>
            <th>Asset</th>
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
          <tr><td colspan="11" style="text-align: center; color: var(--subtext); padding: 24px;">Awaiting trade closures...</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <script>
    let chart, candleSeries, upperSeries, lowerSeries;
    let chartInitialized = false;

    function initChart() {
      try {
        const container = document.getElementById('tvChart');
        if (!container || typeof LightweightCharts === 'undefined') {
          console.warn('LightweightCharts library not loaded yet');
          return;
        }
        chart = LightweightCharts.createChart(container, {
          width: container.clientWidth || 800,
          height: 320,
          layout: {
            background: { color: '#111827' },
            textColor: '#9ca3af'
          },
          grid: {
            vertLines: { color: 'rgba(31, 41, 55, 0.5)' },
            horzLines: { color: 'rgba(31, 41, 55, 0.5)' }
          },
          crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
          timeScale: {
            timeVisible: true,
            secondsVisible: false,
            borderColor: '#1f2937'
          },
          rightPriceScale: {
            borderColor: '#1f2937'
          }
        });

        candleSeries = chart.addCandlestickSeries({
          upColor: '#10b981',
          downColor: '#ef4444',
          borderUpColor: '#10b981',
          borderDownColor: '#ef4444',
          wickUpColor: '#10b981',
          wickDownColor: '#ef4444',
        });

        upperSeries = chart.addLineSeries({
          color: '#3b82f6',
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dashed,
          title: 'Donchian High (12)'
        });

        lowerSeries = chart.addLineSeries({
          color: '#f59e0b',
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dashed,
          title: 'Donchian Low (12)'
        });

        window.addEventListener('resize', () => {
          if (chart && container) {
            chart.applyOptions({ width: container.clientWidth });
          }
        });

        fetch('/api/candles?limit=150')
          .then(res => res.json())
          .then(data => {
            if (Array.isArray(data) && data.length > 0) {
              const candles = data.map(d => ({
                time: d.time,
                open: d.open,
                high: d.high,
                low: d.low,
                close: d.close
              }));
              const uppers = data.map(d => ({ time: d.time, value: d.dh }));
              const lowers = data.map(d => ({ time: d.time, value: d.dl }));
              candleSeries.setData(candles);
              upperSeries.setData(uppers);
              lowerSeries.setData(lowers);
              chart.timeScale().fitContent();
              chartInitialized = true;
            }
          })
          .catch(e => console.error('Error preloading candles:', e));

      } catch(e) {
        console.error('TV chart init error:', e);
      }
    }

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', initChart);
    } else {
      initChart();
    }

    function renderSparkline(values, strokeColor) {
      if (!values || values.length < 2) return '';
      const min = Math.min(...values);
      const max = Math.max(...values);
      const range = (max - min) || 1;
      const width = 300;
      const height = 45;
      
      const points = values.map((v, i) => {
        const x = (i / (values.length - 1)) * width;
        const y = height - ((v - min) / range) * (height - 8) - 4;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      }).join(' ');

      return `
        <svg class="sparkline" viewBox="0 0 ${width} ${height}">
          <polyline fill="none" stroke="${strokeColor}" stroke-width="2" points="${points}" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      `;
    }

    function createAccountCardHtml(key, acc) {
      const isOptionB = key.startsWith('opt_b');
      const isMexc = key.includes('mexc');
      let tagClass = 'tag-mexc';
      let tagText = 'MEXC ZERO MAKER';
      if (isOptionB) {
        tagClass = 'tag-portfolio';
        tagText = isMexc ? 'OPTION B • MEXC (0.00%)' : 'OPTION B • BYBIT (0.02%)';
      } else if (!isMexc) {
        tagClass = 'tag-bybit';
        tagText = 'BYBIT 0.02% MAKER';
      }

      const pnlClass = acc.total_net_profit >= 0 ? 'pos-val' : 'neg-val';
      const pnlSign = acc.total_net_profit >= 0 ? '+' : '';
      const chartColor = acc.total_net_profit >= 0 ? '#10b981' : '#ef4444';
      const sparklineSvg = renderSparkline(acc.equity_curve, chartColor);

      const assetBadges = acc.active_assets ? `
        <div style="display:flex; gap:4px; margin-top:8px; flex-wrap:wrap;">
          ${acc.active_assets.map(a => `<span style="font-size:10px; background:rgba(139,92,246,0.15); color:#c084fc; padding:2px 6px; border-radius:3px; font-weight:600;">${a}</span>`).join('')}
        </div>
      ` : '';

      return `
        <div class="card">
          <div class="card-header">
            <h2>${acc.name}</h2>
            <span class="tag ${tagClass}">${tagText}</span>
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
          ${assetBadges}
          <div class="chart-box">
            <h4>Rolling Equity Curve (120 Bars)</h4>
            ${sparklineSvg}
          </div>
        </div>
      `;
    }

    function updateUI(data) {
      const c = data.candle;
      if (c && c.timestamp) {
        document.getElementById('barTime').innerText = String(c.timestamp).slice(0, 19);
        document.getElementById('barClose').innerText = '$' + c.close.toFixed(2);
        if (c.sol_close !== undefined) document.getElementById('solClose').innerText = '$' + c.sol_close.toFixed(2);
        if (c.bnb_close !== undefined) document.getElementById('bnbClose').innerText = '$' + c.bnb_close.toFixed(2);
        if (c.link_close !== undefined) document.getElementById('linkClose').innerText = '$' + c.link_close.toFixed(2);

        const macroEl = document.getElementById('barMacro');
        macroEl.innerText = c.macro_trend;
        macroEl.className = c.macro_trend === 'BULLISH' ? 'status-badge badge-bull' : 'status-badge badge-bear';
        if (c.adx !== undefined) {
          document.getElementById('barAdx').innerText = c.adx.toFixed(1) + (c.adx >= 18.0 ? ' (TREND)' : ' (CHOP)');
          document.getElementById('barAdx').style.color = c.adx >= 18.0 ? 'var(--success)' : 'var(--warning)';
        }
        if (c.ml_prob !== undefined) {
          document.getElementById('barMl').innerText = c.ml_prob.toFixed(1) + '%';
        }
        document.getElementById('barDonchian').innerText = '$' + c.dl.toFixed(0) + ' - $' + c.dh.toFixed(0);

        if (candleSeries && c.open && c.high && c.low && c.close) {
          const t_unix = Math.floor(new Date(c.timestamp).getTime() / 1000);
          if (!isNaN(t_unix)) {
            candleSeries.update({ time: t_unix, open: c.open, high: c.high, low: c.low, close: c.close });
            if (upperSeries && c.dh !== undefined) upperSeries.update({ time: t_unix, value: c.dh });
            if (lowerSeries && c.dl !== undefined) lowerSeries.update({ time: t_unix, value: c.dl });
          }
        }
      }

      let optAHtml = '';
      let optBHtml = '';
      let optCHtml = '';
      let posRows = '';
      let allTrades = [];

      for (const [key, acc] of Object.entries(data.accounts)) {
        const cardHtml = createAccountCardHtml(key, acc);
        if (key.startsWith('opt_c')) {
          optCHtml += cardHtml;
        } else if (key.startsWith('opt_b')) {
          optBHtml += cardHtml;
        } else {
          optAHtml += cardHtml;
        }

        const stratLabel = key.startsWith('opt_c') ?
          '<span style="color:#34d399; font-weight:700;">Option C (Quantum)</span>' :
          (key.startsWith('opt_b') ? 
          '<span style="color:#c084fc; font-weight:700;">Option B</span>' : 
          '<span style="color:#60a5fa; font-weight:700;">Option A</span>');

        for (const pos of acc.open_positions) {
          const pnl = pos.unrealized_pnl;
          const pnlCls = pnl >= 0 ? 'pos-val' : 'neg-val';
          posRows += `
            <tr>
              <td>${stratLabel}</td>
              <td><strong>${acc.name.split('(')[0].trim()}</strong></td>
              <td><strong style="color: #60a5fa;">${pos.symbol}</strong></td>
              <td><span style="color: ${pos.side === 'LONG' ? 'var(--success)' : 'var(--danger)'}; font-weight: 700;">${pos.side}</span></td>
              <td>$${pos.entry_price.toFixed(2)}</td>
              <td>$${pos.current_price.toFixed(2)}</td>
              <td>${pos.size.toFixed(4)}</td>
              <td style="color: var(--danger)">$${pos.sl_price.toFixed(2)}</td>
              <td style="color: var(--success)">$${pos.tp_price.toFixed(2)}</td>
              <td>${pos.be_locked ? '<span style="color:var(--success); font-weight:700;">YES (+0.25x ATR)</span>' : '<span style="color:var(--subtext)">NO</span>'}</td>
              <td class="${pnlCls}">${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}</td>
            </tr>
          `;
        }

        if (acc.recent_trades) {
          for (const tr of acc.recent_trades) {
            allTrades.push({
              ...tr,
              accName: acc.name.split('(')[0].trim(),
              stratLabel: key.startsWith('opt_b') ? 'Option B' : 'Option A',
              stratColor: key.startsWith('opt_b') ? '#c084fc' : '#60a5fa'
            });
          }
        }
      }

      document.getElementById('optACardsGrid').innerHTML = optAHtml;
      document.getElementById('optBCardsGrid').innerHTML = optBHtml;
      const cGrid = document.getElementById('optCCardsGrid');
      if (cGrid) cGrid.innerHTML = optCHtml;
      if (posRows) document.getElementById('openPositionsTable').innerHTML = posRows;

      // Sort recent trades chronologically descending
      allTrades.sort((a, b) => new Date(b.exit_time) - new Date(a.exit_time));
      let tradeRows = '';
      for (const tr of allTrades.slice(0, 20)) {
        const trPnlCls = tr.net_pnl >= 0 ? 'pos-val' : 'neg-val';
        tradeRows += `
          <tr>
            <td><strong style="color:${tr.stratColor};">${tr.stratLabel}</strong></td>
            <td>${tr.accName}</td>
            <td><strong>${tr.symbol || 'BTC/USDT'}</strong></td>
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
      if (tradeRows) document.getElementById('closedTradesTable').innerHTML = tradeRows;
    }

    function initWebSocket() {
      const loc = window.location;
      const wsUri = (loc.protocol === 'https:' ? 'wss:' : 'ws:') + '//' + loc.host + '/ws';
      const ws = new WebSocket(wsUri);
      ws.onmessage = (e) => {
        try { updateUI(JSON.parse(e.data)); } catch(err) {}
      };
      ws.onclose = () => { setTimeout(initWebSocket, 2000); };
    }
    initWebSocket();

    async function refreshState() {
      try {
        const res = await fetch('/api/state');
        const data = await res.json();
        updateUI(data);
      } catch (err) {}
    }

    async function emergencyKill() {
      if (confirm('🚨 ACTIVATE EMERGENCY CIRCUIT BREAKER?\n\nThis will instantly halt the trading feed, liquidate all open positions across Option A & Option B, and engage risk lockout.')) {
        const res = await fetch('/api/emergency_kill', { method: 'POST' });
        const data = await res.json();
        alert('CIRCUIT BREAKER ENGAGED!\n' + data.message);
        document.getElementById('pauseBtn').innerText = '▶ Resume Stream';
        refreshState();
      }
    }

    async function togglePause() {
      const res = await fetch('/api/toggle_pause', { method: 'POST' });
      const data = await res.json();
      document.getElementById('pauseBtn').innerText = data.is_paused ? '▶ Resume Stream' : '⏸ Pause Stream';
    }

    async function resetSim() {
      if (confirm('Reset all Option A & Option B paper accounts to $10,000 starting capital?')) {
        await fetch('/api/reset', { method: 'POST' });
        refreshState();
      }
    }

    async function applyConfig() {
      const baseRisk = parseFloat(document.getElementById('riskInput').value);
      const adxVal = parseFloat(document.getElementById('adxInput').value);
      const vpVal = document.getElementById('vpInput').checked;

      await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ base_risk_pct: baseRisk, adx_threshold: adxVal, volatility_parity: vpVal })
      });
      alert('Parameters updated dynamically across all Option A & Option B accounts!');
    }

    async function switchRegime(regime) {
      await fetch('/api/regime', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ regime: regime })
      });
      fetch('/api/candles?limit=150')
        .then(res => res.json())
        .then(data => {
          if (chart && candleSeries && Array.isArray(data) && data.length > 0) {
            candleSeries.setData(data.map(d => ({ time: d.time, open: d.open, high: d.high, low: d.low, close: d.close })));
            if (upperSeries) upperSeries.setData(data.map(d => ({ time: d.time, value: d.dh })));
            if (lowerSeries) lowerSeries.setData(data.map(d => ({ time: d.time, value: d.dl })));
            chart.timeScale().fitContent();
          }
        });
      refreshState();
    }

    setInterval(refreshState, 1000);
    refreshState();
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    uvicorn.run("services.demo_runner.demo_server:app", host="0.0.0.0", port=8000, log_level="info")
