import pytest
import os
import pandas as pd
from core.analysis.vbt_scanner import VectorBTScanner
from core.analysis.roi_ledger import ROILedger

def test_vbt_scanner_grid_execution(tmp_path):
    # Verify VectorBT scanner executes on sample dataframe
    csv_file = os.path.join(tmp_path, "sample_btc.csv")
    dates = pd.date_range("2024-01-01", periods=100, freq="4h")
    price = 40000.0 + (pd.Series(range(100)) * 50.0).values
    df = pd.DataFrame({
        "timestamp": dates,
        "open": price,
        "high": price + 100.0,
        "low": price - 100.0,
        "close": price + 20.0,
        "volume": [1000.0] * 100
    })
    df.to_csv(csv_file, index=False)

    test_ledger_path = os.path.join(tmp_path, "test_ledger.json")
    ledger = ROILedger(ledger_path=test_ledger_path)
    scanner = VectorBTScanner(ledger=ledger)

    results = scanner.run_grid_scan(
        asset_csv_path=csv_file,
        asset_name="BTC/USDT",
        timeframe="4H",
        lookback_range=[5, 10],
        vwap_windows=[10],
        ema_fast_slow_pairs=[(5, 15)]
    )

    assert len(results) == 2  # 2 lookbacks * 1 vwap * 1 ema pair
    assert "sharpe_ratio" in results.columns
    assert "monthly_roi_pct" in results.columns
    assert "total_return_pct" in results.columns

def test_vbt_scan_and_record_champion(tmp_path):
    csv_file = os.path.join(tmp_path, "sample_btc.csv")
    dates = pd.date_range("2024-01-01", periods=100, freq="4h")
    price = 40000.0 + (pd.Series(range(100)) * 50.0).values
    df = pd.DataFrame({
        "timestamp": dates,
        "open": price,
        "high": price + 100.0,
        "low": price - 100.0,
        "close": price + 20.0,
        "volume": [1000.0] * 100
    })
    df.to_csv(csv_file, index=False)

    test_ledger_path = os.path.join(tmp_path, "test_ledger.json")
    ledger = ROILedger(ledger_path=test_ledger_path)
    scanner = VectorBTScanner(ledger=ledger)

    champ = scanner.scan_and_record_champion(
        asset_csv_path=csv_file,
        asset_name="BTC/USDT",
        timeframe="4H",
        save_to_ledger=True
    )

    assert "config_label" in champ
    data = ledger.load_ledger()
    assert len(data["experiments"]) >= 1
    assert "SAVEPOINT_EXP-VBT-CHAMPION-BTC_USDT" in data["savepoints"]
