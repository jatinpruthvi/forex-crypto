from pydantic import BaseModel
from typing import Optional, Dict, Any


class SignalResponse(BaseModel):
    action: str  # "BUY", "SELL", "HOLD", "CLOSE_ALL"
    symbol: str
    lots: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    limit_price: Optional[float] = None  # Maker post-only limit price
    confidence: int = 0
    reason: str = ""
    regime: str = "UNKNOWN"
    regime_detail: Dict[str, Any] = {}
    ml_probability: float = 0.50
    conviction_breakdown: Dict[str, Any] = {}
    risk: Dict[str, Any] = {}
    expiry_seconds: int = 3600
    timestamp: str = ""


class HealthResponse(BaseModel):
    status: str = "alive"
    timestamp: str
    uptime_seconds: float
    version: str = "1.0.0"


class StatusResponse(BaseModel):
    api_uptime_hours: float
    last_signal: Dict[str, Any]
    regimes: Dict[str, str]
    data_freshness: Dict[str, str]
    ml_model: Dict[str, Any]
    dd_protocol: Dict[str, Any]
