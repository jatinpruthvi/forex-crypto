"""EXP-046a (2026-10-30): GitHub strategy-repository miner.

User: "check for git repository of strategies... check is there any strategy we can adopt
so we can have higher results make sure you check at least 500 git repositories."

Phase 1: search GitHub across ~25 keyword families (crypto/quant trading strategies),
dedup, then fetch repo metadata + full file tree for EACH repo (>=500), classify by
strategy type from file paths. Output: reports/strategy_repo_mine.json catalog.
"""
import os
import re
import sys
import json
import time
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "reports", "strategy_repo_mine.json")

QUERIES = [
    "crypto trading strategy backtest", "binance trading bot strategy",
    "bitcoin trading strategy python", "quantitative trading strategies",
    "algorithmic trading crypto", "freqtrade strategy", "backtrader strategy",
    "vectorbt strategy", "grid trading bot crypto", "DCA bot crypto",
    "crypto momentum strategy", "mean reversion trading strategy",
    "pairs trading crypto", "funding rate arbitrage crypto",
    "market making bot crypto", "altcoin rotation strategy",
    "crypto scalping bot", "machine learning crypto trading",
    "reinforcement learning trading strategy", "trading strategies collection",
    "cryptocurrency trading algorithms", "bitcoin technical analysis strategy",
    "ethereum trading bot", "crypto arbitrage bot", "supertrend ichimoku strategy",
    "RSI MACD strategy python", "bollinger band strategy", "options strategy backtest",
    "futures trading strategy python", "crypto alpha factors",
]

TYPE_KEYWORDS = {
    "momentum_trend": ["momentum", "trend", "supertrend", "ichimoku", "macd", "cross",
                       "donchian", "aroon", "adx", "turtle", "breakout"],
    "mean_reversion": ["meanrev", "mean_rev", "reversion", "bollinger", "rsi", "stoch",
                       "oversold", "overbought", "zscore", "z_score", "pairs", "coint"],
    "grid_dca": ["grid", "dca", "accumulate"],
    "scalping_intraday": ["scalp", "intraday", "tick", "orderbook", "order_book", "hft",
                          "microstructure", "tape"],
    "market_making": ["market_mak", "marketmak", "liquidity", "mm_bot"],
    "arbitrage": ["arbitrage", "arb", "basis", "funding", "carry", "spread"],
    "ml_rl": ["lstm", "gru", "transformer", "reinforcement", "q_learn", "dqn", "ppo",
              "xgboost", "lightgbm", "random_forest", "neural", "deep", "rl_", "ml_"],
    "portfolio_rot": ["portfolio", "rotation", "allocation", "rebalance", "risk_parity",
                      "factor", "alpha"],
    "market_maker_mm": ["amm", "defi", "liquidity_pool"],
    "options_vol": ["option", "volatility", "straddle", "strangle", "iron", "theta",
                    "vix", "iv_"],
    "signal_collection": ["strategies", "signals", "collection", "library", "toolbox"],
}


def gh_json(args, retries=2):
    for i in range(retries + 1):
        try:
            out = subprocess.run(["gh", "api"] + args, capture_output=True, text=True, timeout=40)
            if out.returncode == 0 and out.stdout.strip():
                return json.loads(out.stdout)
        except Exception:
            pass
        time.sleep(1.0 + i)
    return None


def search_repos():
    seen = {}
    for q in QUERIES:
        for page in (1, 2):
            d = gh_json([f"search/repositories?q={q.replace(chr(32), '+')}&sort=stars&order=desc&per_page=100&page={page}"])
            if not d or "items" not in d:
                break
            for it in d["items"]:
                fn = it["full_name"]
                if fn not in seen:
                    seen[fn] = {"stars": it.get("stargazers_count", 0),
                                "desc": (it.get("description") or "")[:200],
                                "lang": it.get("language"), "query": q}
            if len(d["items"]) < 100:
                break
            time.sleep(2.2)          # search API rate limit 30/min
        print(f"  search '{q}': cum {len(seen)}", flush=True)
        time.sleep(2.2)
    return seen


def fetch_tree(full_name):
    meta = gh_json([f"repos/{full_name}"])
    if not meta:
        return full_name, None, []
    branch = meta.get("default_branch", "main")
    tree = gh_json([f"repos/{full_name}/git/trees/{branch}?recursive=1"])
    if not tree:
        return full_name, meta, []
    paths = [t["path"].lower() for t in tree.get("tree", []) if t.get("type") == "blob"]
    return full_name, meta, paths[:4000]


def classify(paths, desc):
    text = " ".join(paths) + " " + desc.lower()
    hits = {}
    for typ, kws in TYPE_KEYWORDS.items():
        c = sum(text.count(k) for k in kws)
        if c:
            hits[typ] = c
    return hits


SEARCH_CACHE = os.path.join(BASE, "reports", "_mine_search.json")


def main():
    if os.path.exists(SEARCH_CACHE):
        repos = json.load(open(SEARCH_CACHE))
        print(f"search cache loaded: {len(repos)} repos", flush=True)
    else:
        print("PHASE 1: searching GitHub...", flush=True)
        repos = search_repos()
        json.dump(repos, open(SEARCH_CACHE, "w"))
        print(f"unique repos collected: {len(repos)}", flush=True)
    # cap for tree-scan: take all if <=700 else highest stars
    items = sorted(repos.items(), key=lambda kv: -kv[1]["stars"])[:700]
    print(f"tree-scanning {len(items)} repos (>=500 required)...")

    catalog = {}
    done = 0
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(fetch_tree, fn): fn for fn, _ in items}
        for fut in as_completed(futs):
            fn, meta, paths = fut.result()
            done += 1
            if done % 25 == 0:
                print(f"  scanned {done}/{len(items)}", flush=True)
                _ck = {"date": "2026-10-30", "n_scanned": len(catalog), "partial": True,
                       "repos": catalog}
                json.dump(_ck, open(OUT, "w"), indent=1)
            if meta is None:
                continue
            info = repos.get(fn, {})
            types = classify(paths, info.get("desc", ""))
            strat_files = [p for p in paths if re.search(
                r"strateg|signal|backtest|indicators?\.py|strategy\.|_strategy|turtle|"
                r"supertrend|ichimoku|bollinger|momentum|meanrev|grid|dca|scalp|arb",
                p)][:12]
            catalog[fn] = {
                "stars": info.get("stars", meta.get("stargazers_count", 0)),
                "desc": info.get("desc", ""),
                "lang": info.get("lang") or meta.get("language"),
                "branch": meta.get("default_branch"),
                "types": types,
                "primary_type": max(types, key=types.get) if types else "other",
                "strategy_files": strat_files,
                "n_files": len(paths),
                "query": info.get("query", ""),
            }

    by_type = {}
    for fn, r in catalog.items():
        by_type[r["primary_type"]] = by_type.get(r["primary_type"], 0) + 1
    out = {"date": "2026-10-30", "n_scanned": len(catalog), "by_type": by_type,
           "queries": QUERIES, "repos": catalog}
    json.dump(out, open(OUT, "w"), indent=1)
    print(f"\nSCANNED {len(catalog)} repos. By primary type: "
          f"{json.dumps(by_type, indent=1)}")
    print("saved", OUT)


if __name__ == "__main__":
    main()
