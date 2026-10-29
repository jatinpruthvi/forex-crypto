"""
Emergency Actions Route:
Emergency Kill-Switch and position liquidation endpoint.
Supports Bearer token authentication, order book purge, and account engine halt.
"""
from fastapi import APIRouter, Header, HTTPException, status
from datetime import datetime, timezone
import os
from typing import Optional, Dict, Any

from services.brain_api.models.response import SignalResponse
from core.risk.kill_switch import KillSwitchManager

router = APIRouter()
kill_switch_manager = KillSwitchManager()

# Admin secret token for emergency actions. When the env var is unset we
# generate a per-process random secret instead of shipping a known default —
# a published fallback token is an open door on any non-dev deployment.
EMERGENCY_ADMIN_TOKEN = os.getenv("EMERGENCY_ADMIN_TOKEN", "")
if not EMERGENCY_ADMIN_TOKEN:
    import secrets as _secrets
    EMERGENCY_ADMIN_TOKEN = _secrets.token_urlsafe(32)

# Global emergency state
emergency_state = {
    "kill_switch_engaged": False,
    "last_kill_timestamp": None,
    "kill_reason": None,
}


def verify_admin_token(authorization: Optional[str] = Header(None)) -> bool:
    """Verifies operator authorization token for high-risk actions."""
    if not authorization:
        # Check if running in development mode
        dev_mode = os.getenv("AMATS_ENV", "development").lower() == "development"
        if dev_mode:
            return True
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header for emergency operation",
        )

    token = authorization.replace("Bearer ", "").strip()
    if token != EMERGENCY_ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid emergency authorization token",
        )
    return True


@router.post("/close_all", response_model=SignalResponse)
async def emergency_close_all(authorization: Optional[str] = Header(None)):
    verify_admin_token(authorization)

    now_iso = datetime.now(timezone.utc).isoformat()
    emergency_state["kill_switch_engaged"] = True
    emergency_state["last_kill_timestamp"] = now_iso
    emergency_state["kill_reason"] = "Manual Emergency Close Triggered"

    return SignalResponse(
        action="CLOSE_ALL",
        symbol="ALL",
        lots=0.0,
        sl=0.0,
        tp=0.0,
        confidence=0,
        reason="Manual Emergency Close Triggered: All positions marked for liquidation and order queues purged.",
        regime="CRISIS",
        risk={"manual_override": True, "kill_switch_active": True},
        expiry_seconds=0,
        timestamp=now_iso,
    )


@router.post("/resume")
async def resume_trading(authorization: Optional[str] = Header(None)):
    """Operator endpoint to lift the emergency kill-switch halt."""
    verify_admin_token(authorization)
    emergency_state["kill_switch_engaged"] = False
    emergency_state["kill_reason"] = None
    return {
        "status": "RESUMED",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": "Emergency halt lifted. System returned to standard risk guards.",
    }


@router.get("/status")
async def get_emergency_status():
    return {
        "kill_switch_engaged": emergency_state["kill_switch_engaged"],
        "last_kill_timestamp": emergency_state["last_kill_timestamp"],
        "kill_reason": emergency_state["kill_reason"],
    }
