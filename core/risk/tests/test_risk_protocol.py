import pytest
from core.risk.dd_protocol import DrawdownProtocol
from core.risk.kill_switch import KillSwitchManager


def test_drawdown_protocol_tiers():
    protocol = DrawdownProtocol()

    # 1. Green (0-3%)
    green = protocol.evaluate(10000.0, 9850.0)  # 1.5% DD
    assert green["level"] == "GREEN"
    assert green["size_multiplier"] == 1.0
    assert green["allow_new_trades"] is True

    # 2. Yellow (3-5%)
    yellow = protocol.evaluate(10000.0, 9600.0)  # 4.0% DD
    assert yellow["level"] == "YELLOW"
    assert yellow["size_multiplier"] == 0.50
    assert yellow["conviction_min"] >= 75.0

    # 3. Orange (5-7%)
    orange = protocol.evaluate(10000.0, 9400.0)  # 6.0% DD
    assert orange["level"] == "ORANGE"
    assert orange["size_multiplier"] == 0.25
    assert orange["conviction_min"] >= 85.0

    # 4. Red (7-8%)
    red = protocol.evaluate(10000.0, 9250.0)  # 7.5% DD
    assert red["level"] == "RED"
    assert red["allow_new_trades"] is False

    # 5. Black (>8% Kill Switch)
    black = protocol.evaluate(10000.0, 9100.0)  # 9.0% DD
    assert black["level"] == "BLACK"
    assert black["action"] == "CLOSE_ALL"


def test_kill_switch_catastrophe():
    ks = KillSwitchManager()
    # Single trade loss > 3% on $10,000 equity (>$300)
    assert ks.check_single_trade_loss(trade_loss_usd=-350.0, portfolio_equity=10000.0) is True
    assert ks.check_single_trade_loss(trade_loss_usd=-100.0, portfolio_equity=10000.0) is False

    # Flash crash > 5% single candle
    assert ks.check_flash_crash(candle_open=50000.0, candle_close=47000.0) is True  # 6% move
    assert ks.check_flash_crash(candle_open=50000.0, candle_close=49500.0) is False  # 1% move
