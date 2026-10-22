"""
Emergency Actions Route:
Emergency Kill-Switch and position liquidation endpoint.
"""
from fastapi import APIRouter
from datetime import datetime, timezone
from services.brain_api.models.response import SignalResponse

router = APIRouter()


@router.post("/close_all", response_model=SignalResponse)
async def emergency_close_all():
    return SignalResponse(
        action="CLOSE_ALL",
        symbol="ALL",
        lots=0.0,
        sl=0.0,
        tp=0.0,
        confidence=0,
        reason="Manual Emergency Close Triggered",
        regime="CRISIS",
        risk={"manual_override": True},
        expiry_seconds=0,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
