import pytest
import os
import time
from core.execution.live_adapter import (
    ExchangeCredentialManager,
    OrderExecutionSanitizer,
    LiveOrderStateMachine,
    HeartbeatWatchdog,
    CandleTimeAligner,
)
from services.demo_runner.real_paper_engine import RealPaperAccount
from services.demo_runner.multi_asset_engine import MultiAssetPortfolioAccount


def test_exchange_credential_manager():
    # Test safe development mode fallback
    creds = ExchangeCredentialManager.get_credentials("binance", live_mode=False)
    assert "apiKey" in creds
    assert "secret" in creds

    # Test live mode fail-fast validation
    os.environ.pop("BINANCE_API_KEY", None)
    os.environ.pop("BINANCE_API_SECRET", None)
    with pytest.raises(ValueError, match="FATAL: Missing required live API credentials"):
        ExchangeCredentialManager.get_credentials("binance", live_mode=True)


def test_order_execution_sanitizer():
    # Test valid BTC order
    res = OrderExecutionSanitizer.sanitize_order("BTC/USDT", "BUY", qty=0.123456, price=80123.456)
    assert res["valid"] is True
    assert res["qty"] == 0.1234
    assert res["price"] == 80123.5
    assert res["notional"] > 5.0

    # Test failing min notional ($0.50 < $5.00 min)
    res_small = OrderExecutionSanitizer.sanitize_order("BTC/USDT", "BUY", qty=0.00001, price=100.0)
    assert res_small["valid"] is False
    assert "below" in res_small["error"]


def test_live_order_state_machine():
    sm = LiveOrderStateMachine(timeout_seconds=2)
    ord_info = sm.register_order("ORD_101", "BTC/USDT", "BUY", qty=1.0, price=50000.0)
    assert ord_info["status"] == "NEW"

    # Partial fill
    sm.update_fill("ORD_101", 0.4)
    assert sm.orders["ORD_101"]["status"] == "PARTIALLY_FILLED"

    # Complete fill
    sm.update_fill("ORD_101", 1.0)
    assert sm.orders["ORD_101"]["status"] == "FILLED"

    # Stale order check
    sm.register_order("ORD_102", "ETH/USDT", "SELL", qty=2.0, price=3000.0)
    time.sleep(2.1)
    stale = sm.check_stale_orders()
    assert any(o["order_id"] == "ORD_102" for o in stale)


def test_heartbeat_watchdog():
    wd = HeartbeatWatchdog(max_silence_seconds=1.0)
    assert wd.is_feed_healthy("binance_ws") is False

    wd.record_tick("binance_ws")
    assert wd.is_feed_healthy("binance_ws") is True

    time.sleep(1.1)
    assert wd.is_feed_healthy("binance_ws") is False


def test_candle_time_aligner():
    aligner = CandleTimeAligner(["BTC", "SOL", "BNB", "LINK"])
    ts = "2026-10-26T12:00:00Z"

    # Arriving partially
    assert aligner.add_candle(ts, "BTC", {"close": 80000.0}) is None
    assert aligner.add_candle(ts, "SOL", {"close": 100.0}) is None
    assert aligner.add_candle(ts, "BNB", {"close": 700.0}) is None

    # Complete
    full = aligner.add_candle(ts, "LINK", {"close": 11.5})
    assert full is not None
    assert len(full) == 4
    assert full["BTC"]["close"] == 80000.0
    assert full["LINK"]["close"] == 11.5


def test_emergency_kill_circuit_breaker():
    # Test Option A Single Asset Account liquidation
    acct_a = RealPaperAccount("Test Kill A", initial_capital=10000.0)
    acct_a.open_trade("2026-10-26 12:00:00", "long", 80000.0, atr=500.0)
    assert acct_a.position is not None

    acct_a.emergency_flatten("2026-10-26 12:05:00", reason="MANUAL_KILL")
    assert acct_a.position is None
    assert acct_a.emergency_halt is True

    # After emergency halt, new orders must be blocked
    acct_a.open_trade("2026-10-26 12:10:00", "long", 80100.0, atr=500.0)
    assert acct_a.position is None

    # Resume trading
    acct_a.resume_trading()
    assert acct_a.emergency_halt is False
    acct_a.open_trade("2026-10-26 12:15:00", "long", 80100.0, atr=500.0)
    assert acct_a.position is not None

    # Test Option B Multi-Asset Portfolio liquidation
    acct_b = MultiAssetPortfolioAccount("Test Kill B", initial_capital=10000.0)
    acct_b.open_trade("2026-10-26 12:00:00", "BTC/USDT", "long", 80000.0, atr=500.0)
    acct_b.open_trade("2026-10-26 12:00:00", "SOL/USDT", "long", 100.0, atr=2.0)
    assert len(acct_b.positions) == 2

    acct_b.emergency_flatten("2026-10-26 12:05:00")
    assert len(acct_b.positions) == 0
    assert acct_b.emergency_halt is True
