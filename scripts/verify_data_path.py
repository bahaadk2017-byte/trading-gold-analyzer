"""End-to-end check of the read-only data path against the live terminal.

Proves the gates fire on real data. Places no orders and needs no credentials
beyond an already logged-in MT5 terminal.

Usage:  python -u scripts/verify_data_path.py [--depth]

`--depth` additionally probes how much history exists per pair and timeframe,
which takes several minutes because depth has to be discovered by doubling.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fxcore.quality import evaluate
from fxcore.sources.mt5_source import MT5Source

UTC = timezone.utc
PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD"]
TIMEFRAMES = ["M15", "H1", "H4", "D1"]
N_BARS = 200


def main() -> int:
    with MT5Source() as src:
        acct = src.account_summary()
        print("=" * 72)
        print("ACCOUNT")
        for k, v in acct.items():
            flag = ""
            if k == "is_real_account" and v:
                flag = "   <-- REAL MONEY"
            if k == "terminal_trade_allowed" and v:
                flag = "   <-- automated orders permitted by terminal"
            print(f"  {k:26} {v}{flag}")

        clock = src.measure_clock(src.resolve_broker_symbol("EURUSD"))
        print("\nCLOCK")
        print(f"  server offset              {clock.offset_hours:+.1f}h")
        print(f"  residue                    {clock.raw_residue_seconds:+.1f}s")
        print(f"  true UTC now               {datetime.now(UTC).isoformat()}")

        print("\nSYMBOL RESOLUTION  (analysis name -> tradable broker symbol)")
        resolved: dict[str, str] = {}
        for pair in PAIRS:
            try:
                resolved[pair] = src.resolve_broker_symbol(pair)
                print(f"  {pair:8} -> {resolved[pair]}")
            except Exception as exc:  # noqa: BLE001 - report, don't abort the sweep
                print(f"  {pair:8} -> UNRESOLVED: {exc}")

        print("\nGATE RESULTS")
        print(f"  {'pair':9} {'tf':4} {'bars':>5} {'spread':>7} {'margin':>8}  verdict")
        print("  " + "-" * 68)
        passed = failed = 0
        reasons: list[str] = []
        for pair, broker in resolved.items():
            for tf in TIMEFRAMES:
                snap = src.fetch(pair, tf, N_BARS, broker_symbol=broker)
                verdict = evaluate(
                    snap, src.clock, datetime.now(UTC), expected_bars=N_BARS
                )
                spread = (
                    f"{snap.quote.spread_price / snap.spec.pip_size:.1f}p"
                    if snap.quote
                    else "n/a"
                )
                margin = f"{snap.margin_required:.2f}" if snap.margin_required else "none"
                mark = "PASS" if verdict.tradable else "NO_TRADE"
                print(
                    f"  {pair:9} {tf:4} {len(snap.bars):>5} {spread:>7} {margin:>8}  {mark}"
                )
                if verdict.tradable:
                    passed += 1
                else:
                    failed += 1
                    reasons.append(f"{pair} {tf}: {verdict.reason}")

        print(f"\n  {passed} passed, {failed} NO_TRADE")
        if reasons:
            print("\nNO_TRADE REASONS")
            for r in reasons:
                print(f"  - {r}")

        if "--depth" in sys.argv:
            print("\nHISTORY DEPTH  (how much past actually exists)")
            print(f"  {'pair':9} {'tf':4} {'bars':>8}  oldest")
            print("  " + "-" * 56)
            for pair, broker in resolved.items():
                for tf in TIMEFRAMES:
                    d = src.history_depth(broker, tf)
                    oldest = d["oldest_utc"]
                    stamp = oldest.date().isoformat() if oldest else "none"
                    print(f"  {pair:9} {tf:4} {d['bars']:>8}  {stamp}")
        else:
            print("\nHISTORY DEPTH  skipped (pass --depth; takes several minutes)")

        print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
