"""
Hyperliquid live-integration tests (offline — network mocked via fake client):
credentials (wallet auth), symbol mapping, data source, live executor order
routing, and the $25 smoke-check gate report.
"""
import os
import pytest

from core.execution.live_adapter import ExchangeCredentialManager, SizingViabilityGate
from core.execution.hyperliquid_executor import HyperliquidLiveExecutor
from services.data_collector.sources.hyperliquid import (
    HyperliquidSource,
    to_hyperliquid_symbol,
    SYMBOL_MAP,
)


class FakeHyperliquidClient:
    """Records order calls; serves canned market data."""

    def __init__(self):
        self.orders = []
        self._sandbox = False

    def set_sandbox_mode(self, enabled):
        self._sandbox = enabled

    def create_order(self, symbol, type, side, amount, price=None, params=None):
        self.orders.append({"symbol": symbol, "type": type, "side": side,
                            "amount": amount, "price": price, "params": params or {}})
        return {"id": f"HL-{len(self.orders)}", "status": "open"}

    def fetch_balance(self):
        return {"USDC": {"free": 23.4, "used": 1.6, "total": 25.0}}

    def fetch_ticker(self, symbol):
        return {"last": 0.22, "info": {"openInterest": "123456"}}

    def fetch_funding_rate(self, symbol):
        return {"fundingRate": 0.0000123}

    def fetch_ohlcv(self, symbol, timeframe="4h", limit=10):
        return [[1700000000000 + i * 14400000, 1.0, 1.1, 0.9, 1.05, 1000.0] for i in range(limit)]


# ---------- Credentials (wallet auth) ----------

def test_hyperliquid_credentials_fail_fast_without_env(monkeypatch):
    monkeypatch.delenv("HYPERLIQUID_API_KEY", raising=False)
    monkeypatch.delenv("HYPERLIQUID_API_SECRET", raising=False)
    with pytest.raises(ValueError, match="FATAL: Missing required live API credentials"):
        ExchangeCredentialManager.get_credentials("hyperliquid", live_mode=True)


def test_hyperliquid_build_ccxt_config_wallet_auth(monkeypatch):
    monkeypatch.setenv("HYPERLIQUID_API_KEY", "0xWALLET")
    monkeypatch.setenv("HYPERLIQUID_API_SECRET", "0xPRIVATEKEY")
    cfg = ExchangeCredentialManager.build_ccxt_config("hyperliquid", live_mode=True)
    assert cfg["walletAddress"] == "0xWALLET"
    assert cfg["privateKey"] == "0xPRIVATEKEY"
    assert "apiKey" not in cfg  # wallet-based, not CEX key-based
    assert cfg["enableRateLimit"] is True


def test_ceex_build_ccxt_config_unchanged(monkeypatch):
    monkeypatch.setenv("BYBIT_API_KEY", "k")
    monkeypatch.setenv("BYBIT_API_SECRET", "s")
    cfg = ExchangeCredentialManager.build_ccxt_config("bybit", live_mode=True)
    assert cfg["apiKey"] == "k" and cfg["secret"] == "s"


# ---------- Symbol mapping ----------

def test_symbol_mapping_usdt_to_usdc():
    assert to_hyperliquid_symbol("BTC/USDT") == "BTC/USDC:USDC"
    assert to_hyperliquid_symbol("DOGE/USDT") == "DOGE/USDC:USDC"
    for sym in ["BTC/USDT", "ETH/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT", "LTC/USDT", "LINK/USDT"]:
        assert sym in SYMBOL_MAP


# ---------- Data source ----------

def test_hyperliquid_source_signals_and_candles():
    fake = FakeHyperliquidClient()
    src = HyperliquidSource(client=fake)
    sig = src.fetch_market_signals("DOGE/USDT")
    assert sig["funding_rate"] == pytest.approx(0.0000123)
    assert sig["open_interest"] == 123456.0
    candles = src.fetch_h4_candles("BTC/USDT", limit=10)
    assert len(candles) == 10
    assert {"timestamp", "open", "high", "low", "close", "volume"} <= set(candles[0].keys())


# ---------- Executor: sizing plans ----------

def test_executor_plan_accepts_doge_at_25():
    ex = HyperliquidLiveExecutor(dry_run=True, client=FakeHyperliquidClient())
    plan = ex.plan_entry("DOGE/USDT", "buy", equity=25.0, price=0.22, atr=0.0077)
    assert plan["accepted"] is True
    assert plan["qty"] == 64.0            # ideal 64.94 -> stepped to whole DOGE
    assert plan["hl_symbol"] == "DOGE/USDC:USDC"
    assert plan["notional"] >= 10.0       # above Hyperliquid $10 min
    assert plan["stop_price"] < 0.22 < plan["tp1_price"]


def test_executor_plan_rejects_below_min_notional():
    ex = HyperliquidLiveExecutor(dry_run=True, client=FakeHyperliquidClient())
    plan = ex.plan_entry("DOGE/USDT", "buy", equity=8.0, price=0.22, atr=0.0077)
    assert plan["accepted"] is False
    assert "notional" in plan["reason"]


def test_executor_plan_rejects_on_gate_oversize_error():
    ex = HyperliquidLiveExecutor(dry_run=True, client=FakeHyperliquidClient())
    # $12 BTC: tier-2 pyramid add rounds > 5% on the 0.00001 lot -> gate rejects
    plan = ex.plan_entry("BTC/USDT", "buy", equity=12.0, price=110000.0, atr=2420.0)
    assert plan["accepted"] is False


# ---------- Executor: order routing ----------

def test_executor_dry_run_logs_simulated_orders():
    fake = FakeHyperliquidClient()
    ex = HyperliquidLiveExecutor(dry_run=True, client=fake)
    plan = ex.plan_entry("DOGE/USDT", "buy", 25.0, 0.22, 0.0077)
    entry = ex.submit_entry(plan)
    stop = ex.place_stop("DOGE/USDT", "buy", plan["qty"], plan["stop_price"])
    close = ex.close_position("DOGE/USDT", "buy", plan["qty"])
    assert entry["status"] == "DRY_FILLED"
    assert stop["status"] == "DRY_PLACED"
    assert close["status"] == "DRY_FILLED"
    assert fake.orders == []            # nothing hit the exchange
    assert len(ex.order_log) == 3


def test_executor_live_routes_postonly_entry_and_reduceonly_stop():
    fake = FakeHyperliquidClient()
    ex = HyperliquidLiveExecutor(dry_run=False, client=fake)
    plan = ex.plan_entry("DOGE/USDT", "buy", 25.0, 0.22, 0.0077)
    ex.submit_entry(plan)
    ex.place_stop("DOGE/USDT", "buy", plan["qty"], plan["stop_price"])

    entry_order = fake.orders[0]
    assert entry_order["symbol"] == "DOGE/USDC:USDC"
    assert entry_order["type"] == "limit"
    assert entry_order["params"]["postOnly"] is True        # maker-fee entry
    assert entry_order["amount"] == 64.0

    stop_order = fake.orders[1]
    assert stop_order["params"]["reduceOnly"] is True
    assert stop_order["params"]["tpsl"] == "sl"
    assert stop_order["side"] == "sell"                     # closes a long
    assert stop_order["params"]["triggerPrice"] == plan["stop_price"]


def test_executor_fetch_equity_and_h4():
    fake = FakeHyperliquidClient()
    ex = HyperliquidLiveExecutor(dry_run=False, client=fake)
    assert ex.fetch_equity() == 25.0
    assert len(ex.fetch_h4("BTC/USDT", limit=5)) == 5


# ---------- Smoke-check script (offline) ----------

def test_smoke_gate_report_all_8_at_25():
    from scripts.run_hyperliquid_live_smoke import gate_report, check_credentials
    rows = gate_report(25.0)
    assert len(rows) == 8
    assert all(r["viable"] for r in rows), {r["symbol"]: r["reason"] for r in rows if not r["viable"]}
    assert all(r["notional"] >= 10.0 for r in rows)


def test_smoke_credentials_check_flags_missing(monkeypatch):
    from scripts.run_hyperliquid_live_smoke import check_credentials
    monkeypatch.delenv("HYPERLIQUID_API_KEY", raising=False)
    monkeypatch.delenv("HYPERLIQUID_API_SECRET", raising=False)
    res = check_credentials()
    assert res["ok"] is False
    monkeypatch.setenv("HYPERLIQUID_API_KEY", "0xW")
    monkeypatch.setenv("HYPERLIQUID_API_SECRET", "0xK")
    assert check_credentials()["ok"] is True
