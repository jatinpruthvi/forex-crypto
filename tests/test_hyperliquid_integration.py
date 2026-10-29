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


# ---------- Regression: Hyperliquid tick/price validity rules ----------

def test_executor_plan_prices_honor_hyperliquid_tick_rules():
    """Hyperliquid rejects prices with > (6-szDecimals) decimals or > 5 sig figs
    (BTC allows max 1 decimal). Every planned price must satisfy the rules."""
    ex = HyperliquidLiveExecutor(dry_run=True, client=FakeHyperliquidClient())

    def decimals_of(x):
        s = f"{x:.10f}".rstrip("0")
        return len(s.split(".")[1]) if "." in s else 0

    # BTC: 2-decimal input must be rounded to an exchange-valid price
    plan = ex.plan_entry("BTC/USDT", "buy", 25.0, 110000.55, 2420.0)
    assert plan["accepted"] is True
    for key in ("limit_price", "stop_price", "tp1_price"):
        px = plan[key]
        assert px == int(px) or decimals_of(px) <= 1, f"{key}={px} violates BTC 1-decimal rule"
    # 5-sig-fig rounding for >=100k prices lands on an integer (always valid on HL)
    assert plan["limit_price"] == 110001.0

    # ETH (max 2 decimals): sig-fig rule applies to non-integers
    plan_eth = ex.plan_entry("ETH/USDT", "buy", 25.0, 3900.1234, 97.5)
    assert plan_eth["accepted"] is True
    assert decimals_of(plan_eth["limit_price"]) <= 2

    # DOGE (max 6 decimals): fine prices must survive with precision intact
    plan_doge = ex.plan_entry("DOGE/USDT", "buy", 25.0, 0.2203, 0.0077)
    assert plan_doge["accepted"] is True
    assert plan_doge["limit_price"] == 0.2203  # NOT crushed to 0.22 by a fake 0.01 tick


def test_round_price_for_venue_rules():
    from core.execution.live_adapter import SizingViabilityGate as G
    assert G.round_price_for_venue(110000.55, "BTC/USDT", "hyperliquid") == 110001.0
    assert G.round_price_for_venue(97000.55, "BTC/USDT", "hyperliquid") == 97001.0
    assert G.round_price_for_venue(0.22023456, "DOGE/USDT", "hyperliquid") == 0.22023  # 5 sig figs
    assert G.round_price_for_venue(2.600043, "XRP/USDT", "hyperliquid") == 2.6
    assert G.round_price_for_venue(110000.0, "BTC/USDT", "hyperliquid") == 110000.0  # integer passthrough


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


    def test_plan_entry_accepts_engine_side_names(self):
        """'long'/'short' (Dual-Slot engine vocabulary) must map to buy/sell
        with the CORRECT stop/tp1 side — not silently flip the branch."""
        ex = HyperliquidLiveExecutor(dry_run=True, client=object())
        long_plan = ex.plan_entry("DOGE/USDT", "long", 25.0, 0.22, 0.0077)
        assert long_plan["accepted"] is True
        assert long_plan["side"] == "buy"
        assert long_plan["stop_price"] < long_plan["limit_price"] < long_plan["tp1_price"]

        short_plan = ex.plan_entry("DOGE/USDT", "short", 25.0, 0.22, 0.0077)
        assert short_plan["accepted"] is True
        assert short_plan["side"] == "sell"
        assert short_plan["tp1_price"] < short_plan["limit_price"] < short_plan["stop_price"]

    def test_plan_entry_invalid_side_raises(self):
        ex = HyperliquidLiveExecutor(dry_run=True, client=object())
        with pytest.raises(ValueError):
            ex.plan_entry("DOGE/USDT", "hodl", 25.0, 0.22, 0.0077)

    def test_plan_entry_rejects_zero_atr_no_size_explosion(self):
        """atr=0 must never inflate the order (regression: risk/~0 stop dist)."""
        ex = HyperliquidLiveExecutor(dry_run=True, client=object())
        plan = ex.plan_entry("DOGE/USDT", "buy", 25.0, 0.22, 0.0)
        assert plan["accepted"] is False
        assert "atr" in plan["reason"]

    def test_gate_rejects_degenerate_inputs(self):
        base = dict(symbol="DOGE/USDT", equity=25.0, price=0.22, atr=0.0077,
                    venue="hyperliquid")
        assert SizingViabilityGate.check(**{**base, "atr": 0.0})["viable"] is False
        assert SizingViabilityGate.check(**{**base, "price": 0.0})["viable"] is False
        assert SizingViabilityGate.check(**{**base, "equity": 0.0})["viable"] is False
        # absurdly tight stop (< 0.05% of price) -> size explosion guard
        assert SizingViabilityGate.check(**{**base, "atr": 1e-7})["viable"] is False

    def test_fetch_equity_dry_run_behavior(self):
        ex = HyperliquidLiveExecutor(dry_run=True, client=object())
        with pytest.raises(RuntimeError):
            ex.fetch_equity()  # no silent 0.0 that zeros replay sizing
        ex2 = HyperliquidLiveExecutor(dry_run=True, client=object(), dry_run_equity=25.0)
        assert ex2.fetch_equity() == 25.0
