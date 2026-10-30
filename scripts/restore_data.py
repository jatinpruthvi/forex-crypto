"""Wipe-proof data restoration (workspace wipes deleted untracked data/ 4x).
Data CSVs are gitignored by repo convention -> re-download on demand via gh api.
Sources: olaxbt/ai-market-maker (panel, funding, macro), ojies/quantinaut (intraday).
Usage: python scripts/restore_data.py   (requires gh auth; ~25MB)"""
import subprocess, base64, io, os
import pandas as pd

def blob(repo, sha):
    out = subprocess.run(["gh", "api", f"repos/{repo}/git/blobs/{sha}", "--jq", ".content"],
                         capture_output=True, text=True)
    return base64.b64decode(out.stdout)

PANEL = {"ADA": "a8d4b8d625fe033c4438ab52312dc10ba4fc7be1",
         "ATOM": "92d0c92cf3e0b4caf6b91989a09a475a854fd908",
         "AVAX": "a56da097e56e2aa3f3bb786f14a49f0567b39d07",
         "BNB": "25c2fd59dc91ee54fd144319253816051390f26d",
         "BTC": "6ae76673dec66b7a0c2c2bafbc9b8f24a1b5a2ab",
         "DOGE": "d932420f6f0d52ccac712ff64369dbcebdb5c653",
         "DOT": "391b3dbab51a0a346203ab9a3f8f0fb31c0984f0",
         "ETH": "a45ad57554333a36122d530c9ed18e120fa3930e",
         "FIL": "24140688d7d26bdf766ca9f209f9ea6cef4ffa43",
         "LINK": "675567a0f977ad68be0d04a3f3e96b48e3049f29",
         "LTC": "057b9ebcd0052eba0d858504f46b267bedd4c7ce",
         "NEAR": "84240dd216aa5d53b0b3fb203eaf6c50454fa202",
         "SOL": "822f026d1cab17b402b26a4891f2f5a712cbc5f6",
         "UNI": "628a0d9f8edcaa38c63c465b6bdd5325686f6830",
         "XRP": "464c1e6c28c743f4fa9b116dddbea786417e36db"}
INTRADAY = {"btc_usdt_5m.csv.parquet": "503fc7ca6f622a509a0ff4f01b7600d6392188a3",
            "btc_usdt_15m.csv.parquet": "f05a1d71ae8f0fbd2e9526bf18426423e4c07a86",
            "btc_usdt_1h.csv.parquet": "dbaf84daec5c9f3fd69ae0b40ed7d3b1899e6d58",
            "btc_usdt_4h.csv": "fcf3772938a2c14f74699454b5f4a2a1a8824fe6",
            "eth_usdt_5m.csv.parquet": "e277dc05087d429dbfaa12c47546264342eab2da",
            "eth_usdt_15m.csv.parquet": "eff7668a928c90f3bba606aa6ab299c318cd0aea",
            "xrp_usdt_5m.csv.parquet": "26545f13ceeae59e95a05167cf23efb236df6607",
            "xrp_usdt_15m.csv.parquet": "3e54bb5d28ce7d2c04c61327c2f2638b235820c7"}

def main():
    os.makedirs("data/timeframes/1d_panel_5y", exist_ok=True)
    os.makedirs("data/intraday", exist_ok=True)
    os.makedirs("data/derivatives", exist_ok=True)
    os.makedirs("data/macro", exist_ok=True)
    for c, sha in PANEL.items():
        df = pd.read_csv(io.BytesIO(blob("olaxbt/ai-market-maker", sha)))
        df["date"] = pd.to_datetime(df["timestamp_ms"], unit="ms").dt.strftime("%Y-%m-%d")
        df[["date", "open", "high", "low", "close", "volume"]].to_csv(
            f"data/timeframes/1d_panel_5y/{c}USDT_1d.csv", index=False)
        print("panel", c)
    for fn, sha in INTRADAY.items():
        p = f"data/intraday/{fn}"
        if not os.path.exists(p):
            open(p, "wb").write(blob("ojies/quantinaut", sha))
            print("intraday", fn)
    open("data/derivatives/funding_all.csv", "wb").write(
        blob("olaxbt/ai-market-maker", "20d2b8fcd88aa9380ed45f0787acfc9a1c507f16"))
    open("data/macro/defillama_liquidity_daily.csv", "wb").write(
        blob("olaxbt/ai-market-maker", "2cc2aec9533af02ea066b9ce646caaec4ba28072"))
    print("done: panel 15 + intraday + funding + macro")

if __name__ == "__main__":
    main()
