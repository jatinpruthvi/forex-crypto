import urllib.request, json, base64, os

os.makedirs("data/timeframes", exist_ok=True)
os.makedirs("data/forex", exist_ok=True)

def fetch_file(repo_path, out_path):
    if os.path.exists(out_path) and os.path.getsize(out_path) > 10000:
        print(f"[EXIST] {out_path}")
        return
    api_url = f"https://api.github.com/repos/{repo_path}"
    req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "content" in data:
                content = base64.b64decode(data["content"]).decode("utf-8")
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(content)
                print(f"[OK] Downloaded {out_path} ({len(content.splitlines())} lines)")
    except Exception as e:
        print(f"[ERR] Failed {repo_path}: {e}")

def fetch_blob(blob_url, out_path):
    if os.path.exists(out_path) and os.path.getsize(out_path) > 10000:
        print(f"[EXIST] {out_path}")
        return
    req = urllib.request.Request(blob_url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = base64.b64decode(data["content"]).decode("utf-8")
            lines = content.splitlines()
            header = lines[0].replace("Date", "timestamp")
            processed = [header] + lines[1:]
            with open(out_path, "w", encoding="utf-8") as f:
                f.write("\n".join(processed))
            print(f"[OK] Downloaded {out_path} ({len(lines)} lines)")
    except Exception as e:
        print(f"[ERR] Failed blob {blob_url}: {e}")

# Crypto 4h and 1d files
coins = ["BTC", "BNB", "ETH", "LINK", "ADA", "DOGE", "LTC", "MATIC", "XRP"]
for c in coins:
    repo = f"StephanAkkerman/crypto-forecasting-benchmark/contents/data/coins/{c}/{c}USDT_4h.csv"
    if c == "BTC":
        out = "data/timeframes/BTCUSD_H4.csv"
    else:
        out = f"data/timeframes/{c}USDT_H4.csv"
    fetch_file(repo, out)

fetch_file("StephanAkkerman/crypto-forecasting-benchmark/contents/data/coins/BTC/BTCUSDT_1d.csv", "data/timeframes/BTC_1d.csv")

# Forex H4 blobs
forex_blobs = [
    ("https://api.github.com/repos/ejtraderLabs/historical-data/git/blobs/c18671cf823d0873cef4eb9f7a9f2bf7c96a63bf", "data/forex/XAUUSD_H4.csv"),
    ("https://api.github.com/repos/ejtraderLabs/historical-data/git/blobs/9a5cc928bc4e33fd3ac8d642d1a6b44836f50a85", "data/forex/EURUSD_H4.csv"),
    ("https://api.github.com/repos/ejtraderLabs/historical-data/git/blobs/51b797a0791d45cf3ca721948ca6a00dd87bd3e4", "data/forex/GBPUSD_H4.csv"),
    ("https://api.github.com/repos/ejtraderLabs/historical-data/git/blobs/e319da9fc89439b27e22c0fedc421d75e356faa0", "data/forex/EURJPY_H4.csv"),
]

for b_url, out in forex_blobs:
    fetch_blob(b_url, out)

# Data-honesty fix: the EURJPY blob labelled "H4" actually contains H1 candles
# (verified earlier: ~1h median bar interval). Resample to genuine 4h bars so the
# file name matches its content and downstream 4h backtests are not run on H1 bars.
_eurjpy = "data/forex/EURJPY_H4.csv"
if os.path.exists(_eurjpy):
    import pandas as pd
    _df = pd.read_csv(_eurjpy)
    _tscol = "timestamp" if "timestamp" in _df.columns else _df.columns[0]
    _df[_tscol] = pd.to_datetime(_df[_tscol])
    _df = _df.sort_values(_tscol).set_index(_tscol)
    _median_h = (_df.index.to_series().diff().median()).total_seconds() / 3600.0
    if _median_h is not None and _median_h < 2.0:
        _ohlc = {"open": "first", "high": "max", "low": "min", "close": "last"}
        if "volume" in _df.columns:
            _ohlc["volume"] = "sum"
        _df4 = _df.resample("4h").agg(_ohlc).dropna()
        _df4 = _df4.reset_index()
        _df4.to_csv(_eurjpy, index=False)
        print(f"[FIX] {_eurjpy}: source was ~{_median_h:.1f}h bars - resampled to true 4h ({len(_df4)} bars)")
    else:
        print(f"[OK] {_eurjpy}: already ~{_median_h:.1f}h bars")

