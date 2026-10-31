"""
Unit Tests for Real Paper Trading Engine, Webhook Bridge, and Position Sizer Volatility Parity
"""
import pytest
from services.demo_runner.real_paper_engine import RealPaperAccount
from services.monitoring.webhook_notifier import WebhookNotifier
from core.risk.position_sizer import PositionSizer


def test_paper_account_trade_lifecycle():
    account = RealPaperAccount("Test Account", initial_capital=10000.0, maker_fee=0.0002, laddered_tp=False)

    account.open_trade(
        timestamp="2023-01-01 00:00:00",
        side="long",
        entry_price=20000.0,
        atr=100.0,
        base_risk_pct=3.0,
        symbol="BTC/USDT",
        ml_prob=0.85,
    )
    assert account.position is not None
    assert account.position["side"] == "long"
    assert account.position["entry_price"] == 20000.0
    assert account.position["sl_price"] == 20000.0 - 130.0
    assert account.position["tp_price"] == 20000.0 + 200.0

    account.on_candle("2023-01-01 00:15:00", high=20120.0, low=20050.0, close=20110.0)
    assert account.position is not None
    assert account.position["be_locked"] is True
    assert account.position["sl_price"] == 20000.0 + 25.0

    account.on_candle("2023-01-01 00:30:00", high=20210.0, low=20100.0, close=20205.0)
    assert account.position is None
    assert len(account.closed_trades) == 1
    assert account.closed_trades[0]["exit_reason"] == "take_profit_2x_atr"
    assert account.closed_trades[0]["net_pnl"] > 0
    assert account.equity > 10000.0
    assert len(account.equity_curve) >= 2


def test_paper_account_drawdown_throttle():
    account = RealPaperAccount("DD Test", initial_capital=10000.0)
    assert account.get_dd_multiplier() == 1.0

    account.current_drawdown_pct = 4.0
    assert account.get_dd_multiplier() == 0.75

    account.current_drawdown_pct = 6.0
    assert account.get_dd_multiplier() == 0.50

    account.current_drawdown_pct = 7.5
    assert account.get_dd_multiplier() == 0.25

    account.current_drawdown_pct = 9.0
    assert account.get_dd_multiplier() == 0.0


def test_webhook_notifier_fallback():
    notifier = WebhookNotifier()
    assert not notifier.is_configured()
    assert notifier.send_notification("Test Title", "Test Description") is True
    assert notifier.notify_order_opened("TestAcc", "BTC/USDT", "long", 25000.0, 0.5, 24800.0, 25400.0, 80.0) is True
    assert notifier.notify_breakeven_locked("TestAcc", "BTC/USDT", "long", 25050.0) is True
    assert notifier.notify_order_closed("TestAcc", "BTC/USDT", "long", 25400.0, "take_profit", 150.0, 3.5) is True


def test_volatility_parity_weights():
    sizer = PositionSizer()
    vols = {
        "BTC": 0.015,
        "SOL": 0.045,
    }
    weights = sizer.calculate_volatility_parity_weights(vols, target_total_risk_pct=4.0)
    
    assert "BTC" in weights and "SOL" in weights
    assert weights["BTC"] > weights["SOL"]
    assert pytest.approx(weights["BTC"] + weights["SOL"], abs=0.01) == 4.0
