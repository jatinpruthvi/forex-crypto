"""
Hyperliquid $25 Live-Testing Smoke Check (100% READ-ONLY):
==========================================================
Validates that everything needed to run the champion Dual-Slot strategy live on
Hyperliquid from $25 is in place. This script NEVER places an order.

Checks:
  1. Credentials present (HYPERLIQUID_API_KEY = wallet, _API_SECRET = signing key)
  2. Public market connectivity + H4 candles for the 8-pair universe
  3. MICRO_ACCOUNT_MODE sizing gate report at target equity (default $25)
  4. Dry-run entry-plan preview for the top candidate

Usage:
  python scripts/run_hyperliquid_live_smoke.py                # full check (needs internet)
  python scripts/run_hyperliquid_live_smoke.py --offline      # gate report only (no network)
  python scripts/run_hyperliquid_live_smoke.py --equity 50    # check a $50 account
  python scripts/run_hyperliquid_live_smoke.py --testnet      # point at Hyperliquid testnet
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.execution.live_adapter import ExchangeCredentialManager, SizingViabilityGate

UNIVERSE = [
    ("BTC/USDT", 110000.0, 2420.0),
    ("ETH/USDT", 3900.0, 97.5),
    ("BNB/USDT", 1050.0, 23.1),
    ("XRP/USDT", 2.60, 0.078),
    ("ADA/USDT", 0.85, 0.0272),
    ("DOGE/USDT", 0.22, 0.0077),
    ("LTC/USDT", 125.0, 3.25),
    ("LINK/USDT", 21.0, 0.63),
]


def check_credentials() -> dict:
    present = {
        "HYPERLIQUID_API_KEY (wallet 0x...)": bool(os.getenv("HYPERLIQUID_API_KEY")),
        "HYPERLIQUID_API_SECRET (signing key)": bool(os.getenv("HYPERLIQUID_API_SECRET")),
    }
    return {"ok": all(present.values()), "details": present}


def gate_report(equity: float, live_prices: dict = None) -> list:
    """Run the MICRO_ACCOUNT_MODE viability gate for every pair at `equity`."""
    rows = []
    for symbol, fallback_price, fallback_atr in UNIVERSE:
        price = (live_prices or {}).get(symbol, {}).get("price", fallback_price)
        atr = (live_prices or {}).get(symbol, {}).get("atr", fallback_atr)
        r = SizingViabilityGate.check(
            symbol, equity=equity, price=price, atr=atr, venue="hyperliquid"
        )
        rows.append({
            "symbol": symbol,
            "viable": r["viable"],
            "ideal_qty": r["ideal_qty"],
            "stepped_qty": r["stepped_qty"],
            "notional": r["stages"]["initial"]["notional"],
            "worst_error_pct": r["worst_error_pct"],
            "reason": r["reason"],
        })
    return rows


def connectivity_check(testnet: bool) -> dict:
    """Public market data check: fetch a ticker + H4 candles per pair."""
    from services.data_collector.sources.hyperliquid import HyperliquidSource
    src = HyperliquidSource(testnet=testnet)
    results = {}
    for symbol, _, _ in UNIVERSE:
        try:
            candles = src.fetch_h4_candles(symbol, limit=10)
            results[symbol] = {"ok": len(candles) > 0, "candles": len(candles)}
        except Exception as e:
            results[symbol] = {"ok": False, "error": str(e)[:120]}
    return results


def main():
    ap = argparse.ArgumentParser(description="Hyperliquid $25 live-testing smoke check (read-only)")
    ap.add_argument("--equity", type=float, default=25.0, help="account equity to validate (default 25)")
    ap.add_argument("--offline", action="store_true", help="skip all network calls")
    ap.add_argument("--testnet", action="store_true", help="use Hyperliquid testnet")
    args = ap.parse_args()

    print("=" * 78)
    print(f"HYPERLIQUID LIVE-TEST SMOKE CHECK (equity ${args.equity:.0f}, READ-ONLY — no orders)")
    print("=" * 78)

    # 1. Credentials
    creds = check_credentials()
    print("\n[1] CREDENTIALS")
    for k, v in creds["details"].items():
        print(f"    {'✅' if v else '❌'} {k}")
    if not creds["ok"]:
        print("    → Set both env vars before going live (wallet auth). Dry-run works without them.")

    # 2. Connectivity
    if args.offline:
        print("\n[2] CONNECTIVITY — skipped (--offline)")
    else:
        print(f"\n[2] CONNECTIVITY ({'testnet' if args.testnet else 'mainnet'} H4 candles)")
        try:
            conn = connectivity_check(args.testnet)
            ok_n = sum(1 for v in conn.values() if v["ok"])
            for sym, v in conn.items():
                mark = "✅" if v["ok"] else "❌"
                detail = f"{v.get('candles', 0)} candles" if v["ok"] else v.get("error", "")
                print(f"    {mark} {sym:<10} {detail}")
            print(f"    → {ok_n}/8 pairs reachable")
        except Exception as e:
            print(f"    ❌ connectivity check failed: {e}")

    # 3. MICRO_ACCOUNT_MODE gate report
    print(f"\n[3] MICRO_ACCOUNT_MODE GATE @ ${args.equity:.0f} (venue=hyperliquid, max 5% sizing error)")
    rows = gate_report(args.equity)
    print(f"    {'Symbol':<10} {'Ideal Qty':>12} {'Stepped':>12} {'Notional':>10} {'Err%':>7}  Status")
    viable = []
    for r in rows:
        status = "TRADE" if r["viable"] else f"SKIP ({r['reason']})"
        if r["viable"]:
            viable.append(r)
        print(f"    {r['symbol']:<10} {r['ideal_qty']:>12.5f} {r['stepped_qty']:>12.5f} "
              f"${r['notional']:>9.2f} {r['worst_error_pct']:>6.1f}%  {status}")
    print(f"    → {len(viable)}/8 pairs tradeable at ${args.equity:.0f}")

    # 4. Dry-run plan preview
    if viable:
        from core.execution.hyperliquid_executor import HyperliquidLiveExecutor
        ex = HyperliquidLiveExecutor(dry_run=True)
        top = viable[0]
        plan = ex.plan_entry(top["symbol"], "buy", args.equity, UNIVERSE[[u[0] for u in UNIVERSE].index(top["symbol"])][1], UNIVERSE[[u[0] for u in UNIVERSE].index(top["symbol"])][2])
        print(f"\n[4] DRY-RUN ENTRY PLAN PREVIEW ({top['symbol']})")
        if plan["accepted"]:
            ex.submit_entry(plan)
            ex.place_stop(top["symbol"], "buy", plan["qty"], plan["stop_price"])
            print(f"    ✅ entry {plan['side']} {plan['qty']} @ {plan['limit_price']} "
                  f"(notional ${plan['notional']}, stop {plan['stop_price']}, tp1 {plan['tp1_price']})")
            print(f"    ✅ reduce-only stop simulated at {plan['stop_price']}")
            print(f"    → {len(ex.order_log)} simulated orders logged (nothing sent)")
        else:
            print(f"    ❌ plan rejected: {plan['reason']}")

    print("\n" + "=" * 78)
    print("SMOKE CHECK COMPLETE — this script never places real orders.")
    print("Next: HyperliquidLiveExecutor(dry_run=False, testnet=True) rehearsal, then live.")
    print("=" * 78)


if __name__ == "__main__":
    main()
