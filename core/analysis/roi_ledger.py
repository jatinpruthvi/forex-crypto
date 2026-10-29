"""
ROI Progress & Backtest Experiment Ledger:
Tracks all backtest runs, parameters, savepoint states, regime analytics, and decision milestones.
Supports point-in-time state restoration and quantitative progression auditing.
"""
import os
import json
import time
from typing import Dict, Any, Optional
import pandas as pd

LEDGER_FILE = "reports/roi_progress_ledger.json"

# Canonical result keys accepted by record_experiment, with the caller-side
# aliases that historically caused silent data loss (e.g. months_elapsed stored
# as 0.0 because callers passed duration_months). Normalize at the boundary.
RESULT_KEY_ALIASES = {
    "months_elapsed": ("months_elapsed", "months", "duration_months"),
    "win_rate_pct": ("win_rate_pct", "win_rate"),
    "net_total_roi_pct": ("net_roi_total_pct", "total_return_pct", "net_total_roi_pct"),
    "monthly_roi_pct": ("monthly_roi_pct", "monthly_roi"),
    "max_drawdown_pct": ("max_drawdown_pct",),
    "profit_factor": ("profit_factor",),
    "total_trades": ("total_trades",),
    "initial_capital": ("initial_capital",),
    "final_capital": ("final_capital",),
}


def normalize_results(results: Dict[str, Any]) -> Dict[str, Any]:
    """Map caller result dicts onto the canonical metric keys."""
    out = {}
    for canonical, aliases in RESULT_KEY_ALIASES.items():
        for key in aliases:
            if key in results:
                out[canonical] = results[key]
                break
        else:
            out[canonical] = 0.0
    return out

class ROILedger:
    def __init__(self, ledger_path: str = LEDGER_FILE):
        self.ledger_path = ledger_path
        os.makedirs(os.path.dirname(ledger_path) or ".", exist_ok=True)
        if not os.path.exists(ledger_path):
            self.save_empty_ledger()

    def save_empty_ledger(self):
        initial_data = {
            "version": "1.0",
            "description": "Comprehensive Historical & Multi-Asset Backtest Progress Tracker",
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "champion_savepoint": None,
            "experiments": [],
            "savepoints": {}
        }
        with open(self.ledger_path, "w") as f:
            json.dump(initial_data, f, indent=2)

    def load_ledger(self) -> Dict[str, Any]:
        if not os.path.exists(self.ledger_path):
            self.save_empty_ledger()
        with open(self.ledger_path, "r") as f:
            return json.load(f)

    def record_experiment(
        self,
        experiment_id: str,
        strategy_name: str,
        asset: str,
        timeframe: str,
        duration_desc: str,
        params: Dict[str, Any],
        results: Dict[str, Any],
        notes: str = "",
        tag: str = "BENCHMARK",
        create_savepoint: bool = False
    ) -> str:
        data = self.load_ledger()
        data.setdefault("experiments", [])
        data.setdefault("savepoints", {})

        entry = {
            "experiment_id": experiment_id,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "strategy_name": strategy_name,
            "asset": asset,
            "timeframe": timeframe,
            "duration": duration_desc,
            "parameters": params,
            "metrics": normalize_results(results),
            "tag": tag,
            "notes": notes
        }

        # Update or append
        existing_idx = None
        for i, exp in enumerate(data["experiments"]):
            if exp["experiment_id"] == experiment_id:
                existing_idx = i
                break

        if existing_idx is not None:
            data["experiments"][existing_idx] = entry
        else:
            data["experiments"].append(entry)

        if create_savepoint:
            savepoint_key = f"SAVEPOINT_{experiment_id}"
            data["savepoints"][savepoint_key] = {
                "experiment_id": experiment_id,
                "strategy_name": strategy_name,
                "parameters": params,
                "target_monthly_roi": results.get("monthly_roi_pct", 0.0),
                "max_drawdown": results.get("max_drawdown_pct", 0.0),
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
            }
            if data["champion_savepoint"] is None or results.get("monthly_roi_pct", 0.0) > data["savepoints"].get(data["champion_savepoint"], {}).get("target_monthly_roi", -100):
                data["champion_savepoint"] = savepoint_key

        data["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())

        with open(self.ledger_path, "w") as f:
            json.dump(data, f, indent=2)

        return experiment_id

    def get_summary_table(self) -> pd.DataFrame:
        data = self.load_ledger()
        rows = []
        for exp in data["experiments"]:
            m = exp["metrics"]
            rows.append({
                "ID": exp["experiment_id"],
                "Strategy": exp["strategy_name"],
                "Asset": exp["asset"],
                "TF": exp["timeframe"],
                "Duration": exp["duration"],
                "Monthly ROI (%)": m["monthly_roi_pct"],
                "Total Net (%)": m["net_total_roi_pct"],
                "Max DD (%)": m["max_drawdown_pct"],
                "Win Rate (%)": m["win_rate_pct"],
                "Trades": m["total_trades"],
                "PF": m["profit_factor"],
                "Tag": exp["tag"]
            })
        return pd.DataFrame(rows)

    def restore_savepoint(self, savepoint_key: str) -> Optional[Dict[str, Any]]:
        data = self.load_ledger()
        if savepoint_key in data["savepoints"]:
            sp = data["savepoints"][savepoint_key]
            print(f"[ROILedger] Restored savepoint '{savepoint_key}':")
            print(f"  Strategy: {sp['strategy_name']}")
            print(f"  Parameters: {sp['parameters']}")
            print(f"  Target Monthly ROI: +{sp['target_monthly_roi']}%/mo (Max DD: {sp['max_drawdown']}%)")
            return sp
        print(f"[ROILedger] Savepoint '{savepoint_key}' not found.")
        return None
