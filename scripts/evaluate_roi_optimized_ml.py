import json
import pandas as pd

with open(".agent/ml_experiments_ledger.json") as f:
    data = json.load(f)

df_exp = pd.DataFrame(data)

# Filter for experiments where Monthly ROI >= 15%
high_roi = df_exp[df_exp["monthly_roi"] >= 15.0].sort_values(by=["calmar", "monthly_roi"], ascending=False)
print("Experiments with Monthly ROI >= 15%:")
print(high_roi[["model", "label_config", "sizing_mode", "monthly_roi", "max_dd", "win_rate", "pf", "calmar"]].head(15).to_string())

# Filter for best sizing mode
print("\nGrouped by Sizing Mode:")
print(df_exp.groupby("sizing_mode")[["monthly_roi", "max_dd", "win_rate", "pf", "calmar"]].mean())
