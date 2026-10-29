"""
MICRO_ACCOUNT_MODE tests: SizingViabilityGate + Dual-Slot engine integration.

Verifies that on small ($100-$500) accounts the engine auto-rejects pairs whose
exchange lot-step would distort the 1.5%-risk sizing math by more than 5%, and
trades only the pairs that fit — matching real Bybit/MEXC order constraints.
"""
import pytest

from core.execution.live_adapter import SizingViabilityGate
from services.demo_runner.dual_slot_paper_engine import DualSlotSharedPoolAccount


# Representative Oct-2026 prices / H4 ATR (2.0-2.5% majors, 3.0-3.5% alts)
BTC = dict(price=110000.0, atr=2420.0)   # 2.2%
ETH = dict(price=3900.0, atr=97.5)       # 2.5%
BNB = dict(price=1050.0, atr=23.1)       # 2.2%
DOGE = dict(price=0.22, atr=0.0077)      # 3.5%
XRP = dict(price=2.60, atr=0.078)        # 3.0%
ADA = dict(price=0.85, atr=0.0272)       # 3.2%
LTC = dict(price=125.0, atr=3.25)        # 2.6%
LINK = dict(price=21.0, atr=0.63)        # 3.0%

ALL_PAIRS = [
    ("BTC/USDT", BTC), ("ETH/USDT", ETH), ("BNB/USDT", BNB), ("DOGE/USDT", DOGE),
    ("XRP/USDT", XRP), ("ADA/USDT", ADA), ("LTC/USDT", LTC), ("LINK/USDT", LINK),
]


# ---------- SizingViabilityGate unit tests ----------

def test_gate_rejects_btc_below_min_lot_at_100():
    r = SizingViabilityGate.check("BTC/USDT", equity=100.0, venue="mexc", **BTC)
    assert r["viable"] is False
    assert "below min_qty" in r["reason"]
    assert r["ideal_qty"] < 0.001  # 0.000826 BTC — under one lot


def test_gate_rejects_bnb_rounding_error_at_100():
    # ideal 0.0866 BNB -> stepped 0.08 => -7.6% distortion > 5%
    r = SizingViabilityGate.check("BNB/USDT", equity=100.0, venue="mexc", **BNB)
    assert r["viable"] is False
    assert "rounding error" in r["reason"]
    assert abs(r["worst_error_pct"]) > 5.0


def test_gate_accepts_fine_lot_alts_at_100():
    for sym, px in [("DOGE/USDT", DOGE), ("XRP/USDT", XRP), ("LTC/USDT", LTC), ("ETH/USDT", ETH)]:
        r = SizingViabilityGate.check(sym, equity=100.0, venue="mexc", **px)
        assert r["viable"] is True, f"{sym} should be viable at $100 on MEXC: {r['reason']}"
        assert abs(r["worst_error_pct"]) <= 5.0


def test_gate_all_8_pairs_viable_at_500():
    for sym, px in ALL_PAIRS:
        r = SizingViabilityGate.check(sym, equity=500.0, venue="mexc", **px)
        assert r["viable"] is True, f"{sym} should be viable at $500: {r['reason']}"
        assert abs(r["worst_error_pct"]) <= 2.0  # worst case BNB tier-2 add: -1.8%


def test_gate_all_8_pairs_faithful_at_1000():
    for sym, px in ALL_PAIRS:
        r = SizingViabilityGate.check(sym, equity=1000.0, venue="mexc", **px)
        assert r["viable"] is True
        assert abs(r["worst_error_pct"]) <= 1.0  # backtest-faithful sizing


def test_gate_bybit_coarse_lots_reject_btc_at_200():
    # Bybit lot step 0.001 BTC: ideal 0.001653 -> 0.001 = -39.5% distortion
    r = SizingViabilityGate.check("BTC/USDT", equity=200.0, venue="bybit", **BTC)
    assert r["viable"] is False
    assert r["stages"]["initial"]["rounding_error_pct"] < -30.0


def test_gate_bybit_checks_pyramid_tier2_stage():
    # At $500 the initial BTC lot fits (-3.2%) but the Tier-2 add (0.8x) rounds to
    # -9.3% on Bybit's coarse 0.001 step => the gate must reject on the tier stage.
    r = SizingViabilityGate.check("BTC/USDT", equity=500.0, venue="bybit", **BTC)
    assert r["viable"] is False
    assert r["stages"]["initial"]["ok"] is True
    assert r["stages"]["tier2"]["ok"] is False
    assert "tier2" in r["reason"]


def test_gate_bybit_btc_viable_at_3000():
    r = SizingViabilityGate.check("BTC/USDT", equity=3000.0, venue="bybit", **BTC)
    assert r["viable"] is True
    assert r["worst_error_pct"] <= 5.0


# ---------- Hyperliquid venue: fine lots, $10 min-notional ----------

def test_gate_hyperliquid_all_8_pairs_viable_at_25():
    # Hyperliquid's fine szDecimals lots + $10 min-notional make even $25 work
    for sym, px in ALL_PAIRS:
        r = SizingViabilityGate.check(sym, equity=25.0, venue="hyperliquid", **px)
        assert r["viable"] is True, f"{sym} should be viable at $25 on Hyperliquid: {r['reason']}"
        assert abs(r["worst_error_pct"]) <= 5.0


def test_gate_hyperliquid_btc_fine_lots_where_bybit_rejects():
    # Same $100 account: Bybit's 0.001 BTC lot distorts -19.3% (rejected);
    # Hyperliquid's 0.00001 BTC lot rounds to under 1% (accepted).
    hl = SizingViabilityGate.check("BTC/USDT", equity=100.0, venue="hyperliquid", **BTC)
    by = SizingViabilityGate.check("BTC/USDT", equity=100.0, venue="bybit", **BTC)
    assert hl["viable"] is True
    assert abs(hl["worst_error_pct"]) <= 1.0
    assert by["viable"] is False


def test_gate_hyperliquid_min_notional_blocks_tiny_accounts():
    # $10 account: DOGE initial notional ~$5.50 fails the $10 USDC floor
    r = SizingViabilityGate.check("DOGE/USDT", equity=10.0, venue="hyperliquid", **DOGE)
    assert r["viable"] is False
    assert "notional" in r["reason"]


def test_gate_hyperliquid_checks_tier2_min_notional():
    # $15 account: DOGE entry fits ($8.36 notional fails... use LTC where the
    # Tier-2 add alone drops below the $10 floor while entry passes).
    r = SizingViabilityGate.check("LTC/USDT", equity=15.0, venue="hyperliquid", **LTC)
    # entry: ideal 0.0923 LTC -> 0.09 ($11.25 >= $10 OK); tier2: 0.0738 -> 0.07 ($8.75 < $10)
    assert r["stages"]["initial"]["ok"] is True
    assert r["stages"]["tier2"]["ok"] is False
    assert r["viable"] is False
    assert "tier2" in r["reason"]


def test_gate_step_qty_and_rounding_error_helpers():
    assert SizingViabilityGate.step_qty(0.002066, 0.001) == 0.002
    assert SizingViabilityGate.step_qty(259.74, 1.0) == 259.0
    err = SizingViabilityGate.qty_rounding_error(0.002066, 0.001)
    assert err == pytest.approx((0.002 - 0.002066) / 0.002066 * 100.0, abs=0.01)
    assert SizingViabilityGate.qty_rounding_error(0.0, 0.001) == -100.0


def test_gate_respects_max_error_pct_threshold():
    # 3.2% BTC distortion on MEXC at $200: passes 5% gate, fails a 2% gate
    ok = SizingViabilityGate.check("BTC/USDT", equity=200.0, venue="mexc", max_error_pct=5.0, **BTC)
    strict = SizingViabilityGate.check("BTC/USDT", equity=200.0, venue="mexc", max_error_pct=2.0, **BTC)
    assert ok["viable"] is True
    assert strict["viable"] is False


# ---------- DualSlotSharedPoolAccount integration tests ----------

def test_micro_mode_engine_skips_unviable_btc_at_100():
    acc = DualSlotSharedPoolAccount(initial_capital=100.0, micro_account_mode=True)
    opened = acc.open_trade("2026-01-01T00:00", "BTC/USDT", "long", BTC["price"], BTC["atr"])
    assert opened is False
    assert "BTC/USDT" in acc.skipped_symbols
    assert "below min_qty" in acc.skipped_symbols["BTC/USDT"]["reason"]
    assert acc.positions == {}


def test_micro_mode_engine_steps_size_to_lot_and_opens():
    acc = DualSlotSharedPoolAccount(initial_capital=100.0, micro_account_mode=True)
    opened = acc.open_trade("2026-01-01T00:00", "DOGE/USDT", "long", DOGE["price"], DOGE["atr"])
    assert opened is True
    pos = acc.positions["DOGE/USDT"]
    # ideal 259.74 DOGE -> stepped DOWN to whole DOGE lot: 259
    assert pos["size"] == 259.0
    assert pos["initial_size"] == 259.0


def test_micro_mode_disabled_by_default_preserves_legacy_sizing():
    acc = DualSlotSharedPoolAccount(initial_capital=100.0)
    assert acc.micro_account_mode is False
    opened = acc.open_trade("2026-01-01T00:00", "BTC/USDT", "long", BTC["price"], BTC["atr"])
    assert opened is True  # paper mode: no lot gating
    assert acc.positions["BTC/USDT"]["size"] == pytest.approx(0.0008264, abs=1e-5)
    assert acc.skipped_symbols == {}


def test_micro_mode_pyramid_tier_add_is_stepped():
    acc = DualSlotSharedPoolAccount(initial_capital=100.0, micro_account_mode=True)
    assert acc.open_trade("2026-01-01T00:00", "DOGE/USDT", "long", DOGE["price"], DOGE["atr"])
    pos = acc.positions["DOGE/USDT"]
    # Drive price to TP1 (+1.8x ATR = 0.23386) -> 40% partial + Tier-1 pyramid add
    acc.on_asset_candle("2026-01-01T04:00", "DOGE/USDT", high=0.2340, low=0.219, close=0.2339)
    assert pos["tp1_hit"] is True
    assert pos["pyramid_tier"] == 1
    # remaining 259*0.6 = 155.4 + stepped tier-1 add of 259 (ideal 259.74)
    assert pos["size"] == pytest.approx(155.4 + 259.0, abs=1e-6)


def test_micro_mode_pyramid_add_skipped_below_min_qty():
    acc = DualSlotSharedPoolAccount(initial_capital=100.0, micro_account_mode=True)
    assert acc.open_trade("2026-01-01T00:00", "ETH/USDT", "long", ETH["price"], ETH["atr"])
    pos = acc.positions["ETH/USDT"]
    assert pos["size"] == pytest.approx(0.020, abs=1e-9)  # stepped from 0.02051
    # Equity collapses: tier-1 add ideal (0.00513 ETH) now steps below min_qty 0.01
    acc.equity = 25.0
    acc.on_asset_candle("2026-01-01T04:00", "ETH/USDT", high=ETH["price"] + 1.8 * ETH["atr"], low=3890.0, close=4075.0)
    assert pos["tp1_hit"] is True
    assert pos["pyramid_tier"] == 1
    # Only the 40% partial-close resize (0.6x), no pyramid add
    assert pos["size"] == pytest.approx(0.020 * 0.6, abs=1e-9)


def test_micro_mode_summary_exposes_state():
    acc = DualSlotSharedPoolAccount(initial_capital=100.0, micro_account_mode=True, lot_venue="bybit")
    acc.open_trade("2026-01-01T00:00", "BTC/USDT", "long", BTC["price"], BTC["atr"])
    s = acc.get_summary()
    assert s["micro_account_mode"] is True
    assert s["max_sizing_error_pct"] == 5.0
    assert s["lot_venue"] == "bybit"
    assert "BTC/USDT" in s["skipped_symbols"]
