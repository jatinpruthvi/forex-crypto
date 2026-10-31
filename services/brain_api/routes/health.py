"""
Health, Status, and Regime Inspection Routes.
"""
from fastapi import APIRouter
from datetime import datetime, timezone
import time
import os

from services.brain_api.models.response import HealthResponse, StatusResponse
from services.brain_api.routes.signal import system_state, ml_predictor

router = APIRouter()
start_epoch = time.time()


@router.get("/health", response_model=HealthResponse)
async def get_health():
    uptime = time.time() - start_epoch
    return HealthResponse(
        status="alive",
        timestamp=datetime.now(timezone.utc).isoformat(),
        uptime_seconds=round(uptime, 1),
        version="1.0.0",
    )


@router.get("/status", response_model=StatusResponse)
async def get_status():
    uptime_hours = (time.time() - start_epoch) / 3600.0
    now_iso = datetime.now(timezone.utc).isoformat()

    db_mtime = "N/A"
    if os.path.exists("data/signals.db"):
        db_mtime = datetime.fromtimestamp(os.path.getmtime("data/signals.db"), tz=timezone.utc).isoformat()

    return StatusResponse(
        api_uptime_hours=round(uptime_hours, 2),
        last_signal=system_state.get("last_signal", {}),
        regimes=system_state.get("regimes", {}),
        data_freshness={
            "signals_db_last_update": db_mtime,
            "system_time": now_iso,
        },
        ml_model={
            "loaded": ml_predictor.model is not None,
            "model_path": ml_predictor.model_path,
        },
        dd_protocol={
            "starting_equity": system_state.get("starting_equity", 10000.0),
        },
    )


@router.get("/regime/{symbol}")
async def get_symbol_regime(symbol: str):
    reg = system_state.get("regimes", {}).get(symbol, "UNKNOWN")
    return {"symbol": symbol, "regime": reg}


@router.get("/ml_status")
async def get_ml_status():
    return {
        "model_loaded": ml_predictor.model is not None,
        "model_path": ml_predictor.model_path,
    }
