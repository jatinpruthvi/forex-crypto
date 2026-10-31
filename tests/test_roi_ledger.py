import pytest
import os
import json
import pandas as pd
from core.analysis.roi_ledger import ROILedger

def test_roi_ledger_initialization(tmp_path):
    test_path = os.path.join(tmp_path, "test_ledger.json")
    ledger = ROILedger(ledger_path=test_path)
    data = ledger.load_ledger()
    assert data["version"] == "1.0"
    assert "experiments" in data
    assert "savepoints" in data
    assert len(data["experiments"]) == 0

def test_roi_ledger_record_and_restore(tmp_path):
    test_path = os.path.join(tmp_path, "test_ledger.json")
    ledger = ROILedger(ledger_path=test_path)

    exp_id = ledger.record_experiment(
        experiment_id="TEST-001",
        strategy_name="Donchian Test",
        asset="BTC/USDT",
        timeframe="4H",
        duration_desc="100 days",
        params={"risk_pct": 3.0, "sl_atr": 1.3},
        results={
            "initial_capital": 1000.0,
            "final_capital": 1250.0,
            "net_roi_total_pct": 25.0,
            "monthly_roi_pct": 7.5,
            "max_drawdown_pct": 6.2,
            "win_rate": 55.0,
            "total_trades": 20,
            "profit_factor": 1.4,
            "months_elapsed": 3.3
        },
        create_savepoint=True
    )

    assert exp_id == "TEST-001"
    sp = ledger.restore_savepoint("SAVEPOINT_TEST-001")
    assert sp is not None
    assert sp["target_monthly_roi"] == 7.5
    assert sp["parameters"]["risk_pct"] == 3.0

    df_summary = ledger.get_summary_table()
    assert len(df_summary) == 1
    assert df_summary["Asset"].iloc[0] == "BTC/USDT"
    assert df_summary["Monthly ROI (%)"].iloc[0] == 7.5


def test_record_experiment_accepts_duration_months_alias(tmp_path):
    """Benchmark scripts pass duration_months; the ledger must not zero it."""
    from core.analysis.roi_ledger import ROILedger
    ledger = ROILedger(ledger_path=str(tmp_path / "led.json"))
    ledger.record_experiment(
        experiment_id="TEST-DUR-001",
        strategy_name="Alias",
        asset="BTC/USDT",
        timeframe="4H",
        duration_desc="5.47 Months",
        params={},
        results={"monthly_roi_pct": 1.0, "duration_months": 5.47},
    )
    data = ledger.load_ledger()
    exp = next(e for e in data["experiments"] if e["experiment_id"] == "TEST-DUR-001")
    assert exp["metrics"]["months_elapsed"] == 5.47
