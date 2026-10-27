import pytest
from services.demo_runner.real_paper_engine import RealPaperAccount
from services.demo_runner.multi_asset_engine import MultiAssetPortfolioAccount


def test_real_paper_engine_fee_accumulation():
    """Verify fee tracking across partial closes and exit."""
    acct = RealPaperAccount(
        name="Test Single",
        initial_capital=10000.0,
        maker_fee=0.0005,
        laddered_tp=True,
    )
    # Open long trade
    acct.open_trade(
        timestamp="2026-10-26 12:00:00",
        side="long",
        entry_price=100.0,
        atr=2.0,
        base_risk_pct=2.0,
    )
    pos = acct.position
    assert pos is not None
    initial_fee = pos["fee_paid"]
    assert initial_fee > 0.0

    # Trigger TP1 (entry + 1.5 * 2.0 = 103.0)
    acct.on_candle(
        timestamp="2026-10-26 12:15:00",
        high=103.5,
        low=99.5,
        close=103.0,
    )
    assert pos["tp1_taken"] is True
    assert pos["fee_paid"] > initial_fee
    fee_after_tp1 = pos["fee_paid"]

    # Trigger full exit via trailing stop
    acct.on_candle(
        timestamp="2026-10-26 12:30:00",
        high=103.2,
        low=100.0,
        close=100.2,
    )
    assert acct.position is None
    assert len(acct.closed_trades) == 1
    closed = acct.closed_trades[0]
    # Trade fee in closed record must reflect full life-cycle fees (open + TP1 + close)
    assert closed["fee"] >= fee_after_tp1


def test_multi_asset_engine_fee_accumulation():
    """Verify fee tracking across partial laddered exits in multi-asset account."""
    portfolio = MultiAssetPortfolioAccount(
        name="Test Multi",
        initial_capital=10000.0,
        maker_fee=0.0005,
        laddered_tp=True,
    )
    portfolio.open_trade(
        timestamp="2026-10-26 12:00:00",
        symbol="BTC/USDT",
        side="long",
        entry_price=50000.0,
        atr=500.0,
        base_risk_pct=2.0,
    )
    pos = portfolio.positions["BTC/USDT"]
    initial_fee = pos["fee_paid"]
    assert initial_fee > 0.0

    # Trigger TP1
    portfolio.on_asset_candle(
        timestamp="2026-10-26 12:15:00",
        symbol="BTC/USDT",
        high=51000.0,
        low=49800.0,
        close=50800.0,
    )
    assert pos["tp1_taken"] is True
    assert pos["fee_paid"] > initial_fee
    fee_after_tp1 = pos["fee_paid"]

    # Close remaining
    portfolio.on_asset_candle(
        timestamp="2026-10-26 12:30:00",
        symbol="BTC/USDT",
        high=50800.0,
        low=48000.0,
        close=48500.0,
    )
    assert "BTC/USDT" not in portfolio.positions
    assert len(portfolio.closed_trades) == 1
    assert portfolio.closed_trades[0]["fee"] >= fee_after_tp1
