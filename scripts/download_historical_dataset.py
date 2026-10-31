import urllib.request
import json
import base64
import os
import pandas as pd
import numpy as np

os.makedirs("data", exist_ok=True)
output_path = "data/btc_historical_1h.csv"

print("Downloading real historical candle series...")
coins = ["BTC", "ETH", "BNB", "SOL"]
dfs = []

# Fetch BTC 4h data from benchmark repo
blob_sha = "69d9bc15c1d9cf2e9d1cb9e0bdace38614d28fe2"
url = f"https://api.github.com/repos/StephanAkkerman/crypto-forecasting-benchmark/git/blobs/{blob_sha}"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

try:
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())
        raw_csv = base64.b64decode(data["content"]).decode("utf-8")
        from io import StringIO
        df_4h = pd.read_csv(StringIO(raw_csv))
        print("Fetched StephanAkkerman BTC 4h:", len(df_4h))
        # Keep relevant columns
        df_btc = df_4h[["date", "open", "high", "low", "close", "volume"]].copy()
        df_btc.rename(columns={"date": "timestamp"}, inplace=True)
        df_btc["timestamp"] = pd.to_datetime(df_btc["timestamp"])
        dfs.append(df_btc)
except Exception as e:
    print("Warning on benchmark fetch:", e)

# NOTE (data honesty): a close-only series (doduyquy/sgu-2026-datamining-timeseries)
# was previously expanded into OHLCV by synthesizing random high/low wicks and random
# volume. That FABRICATES market data and poisons any backtest built on this file, so
# it is no longer merged here. Only real OHLC sources are combined into the output.

if dfs:
    combined = pd.concat(dfs, ignore_index=True)
    combined.sort_values("timestamp", inplace=True)
    combined.drop_duplicates(subset=["timestamp"], inplace=True)
    combined.to_csv(output_path, index=False)
    print(f"Historical dataset successfully written to {output_path} ({len(combined)} rows).")
else:
    print("No datasets downloaded!")
