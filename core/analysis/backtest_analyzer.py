"""
Backtest Results and Tearsheet Generator:
Parses FreqTrade backtest JSON output, computes summary metrics,
and saves HTML tear-sheet using QuantStats if available.
"""
import json
import os
from typing import Dict, Any, List
import pandas as pd
import numpy as np


class BacktestAnalyzer:
    def __init__(self, backtest_json_path: str):
        self.backtest_json_path = backtest_json_path

    def load_data(self) -> Dict[str, Any]:
        if not os.path.exists(self.backtest_json_path):
            return {}
        with open(self.backtest_json_path, "r") as f:
            return json.load(f)

    def extract_metrics(self) -> Dict[str, Any]:
        data = self.load_data()
        strategy_data = data.get("strategy", {})
        if not strategy_data:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "max_drawdown": 0.0,
                "sharpe": 0.0,
            }

        first_key = list(strategy_data.keys())[0]
        strat = strategy_data[first_key]

        total_trades = strat.get("total_trades", 0)
        wins = strat.get("wins", 0)
        win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0
        profit_factor = strat.get("profit_factor", 0.0)
        max_drawdown = strat.get("max_drawdown_account", 0.0) * 100.0
        sharpe = strat.get("sharpe", 0.0)

        return {
            "total_trades": total_trades,
            "wins": wins,
            "losses": strat.get("losses", 0),
            "win_rate": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "sharpe": round(sharpe, 2),
        }

    def generate_html_report(self, output_html: str = "report.html") -> bool:
        try:
            import quantstats as qs
            metrics = self.extract_metrics()
            if metrics["total_trades"] == 0:
                with open(output_html, "w") as f:
                    f.write("<html><body><h1>No trades in backtest to generate report</h1></body></html>")
                return True
            # Build report template
            html_content = f"""<!DOCTYPE html>
<html>
<head><title>Backtest Report - AMATS</title><style>body {{ font-family: sans-serif; padding: 20px; }} table {{ border-collapse: collapse; width: 50%; }} td, th {{ border: 1px solid #ddd; padding: 8px; }}</style></head>
<body>
<h2>AMATS Strategy Tearsheet Summary</h2>
<table>
  <tr><th>Metric</th><th>Value</th></tr>
  <tr><td>Total Trades</td><td>{metrics['total_trades']}</td></tr>
  <tr><td>Win Rate</td><td>{metrics['win_rate']}%</td></tr>
  <tr><td>Profit Factor</td><td>{metrics['profit_factor']}</td></tr>
  <tr><td>Max Drawdown</td><td>{metrics['max_drawdown_pct']}%</td></tr>
  <tr><td>Sharpe Ratio</td><td>{metrics['sharpe']}</td></tr>
</table>
</body></html>"""
            with open(output_html, "w") as f:
                f.write(html_content)
            return True
        except Exception:
            return False
