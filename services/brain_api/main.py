"""
FastAPI Brain Entry Point:
Microservice powering decision intelligence, signal fusion, regime detection,
and risk guard execution for both Bybit FreqTrade and MT5 MQL5 EA.
"""
import logging
import logging.handlers
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import os
from services.brain_api.routes import signal, health, emergency
from services.brain_api.middleware.logging import RequestLoggingMiddleware

# Configure logging
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler("logs/brain.log", maxBytes=10*1024*1024, backupCount=5, encoding="utf-8")
    ],
)
logger = logging.getLogger("brain_api")

app = FastAPI(
    title="AMATS Trading Brain API",
    version="1.0.0",
    description="Automated Multi-Asset Trading System REST Decision Bridge",
)

# CORS Middleware (allows MQL5 on VPS/External Broker to communicate)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RequestLoggingMiddleware)

# Attach routes
app.include_router(health.router, tags=["Health & Diagnostics"])
app.include_router(signal.router, tags=["Trading Signals"])
app.include_router(emergency.router, tags=["Emergency"])


@app.on_event("startup")
async def startup_event():
    logger.info("AMATS Brain API initialized and operational on port 8000.")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("services.brain_api.main:app", host="0.0.0.0", port=8000, reload=False)
