import json

tasks = [
    {
        "id": "9",
        "title": "P1: Regime-Adaptive Trailing Stops and Dynamic Profit-Taking",
        "priority": "P1",
        "passes": False,
        "description": "Implement regime-aware trailing multipliers (3.0x ATR for strong trends, 1.6x ATR for ranges) in fast_backtester.py and CombinedStrategy.py."
    },
    {
        "id": "10",
        "title": "P2: Continuous Walk-Forward Auto-Retraining Pipeline",
        "priority": "P1",
        "passes": False,
        "description": "Build automated rolling walk-forward learner with drift detection and safety fallback guards in core/ml/walk_forward_learner.py."
    },
    {
        "id": "11",
        "title": "P3: Microstructure Pressure Index (MPI) and Order Flow Sentiment Fusion",
        "priority": "P2",
        "passes": False,
        "description": "Integrate taker imbalance, open interest divergence, and funding exhaustion index into core/signals/fusion.py and brain_api."
    },
    {
        "id": "12",
        "title": "P4: Cross-Asset Covariance Deflation and Portfolio Volatility Parity",
        "priority": "P2",
        "passes": False,
        "description": "Integrate correlation matrix hedging and position deflation in core/risk/position_sizer.py to prevent concurrent multi-asset drawdowns."
    }
]

for t in tasks:
    with open(f".agent/tasks/TASK-{t['id']}.json", "w") as f:
        json.dump(t, f, indent=2)

with open(".agent/tasks.json", "r") as f:
    existing = json.load(f)

for t in tasks:
    existing.append(t)

with open(".agent/tasks.json", "w") as f:
    json.dump(existing, f, indent=2)

print("Registered Ralph tasks 9, 10, 11, 12.")
