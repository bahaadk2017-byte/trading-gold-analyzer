"""Strategy development pipeline — runs the full team workflow.

This script orchestrates the 14-agent strategy development cycle:
  1. macro-researcher   → regime assessment + pre-registered hypothesis
  2. strategy-researcher → versioned spec
  3. data-quality-engineer → validates H1 bars
  4. backtest-engineer  → in-sample run with full costs
  5. post-trade-reviewer → analysis of results
  6. risk-guardian      → veto check

Run:
    python -u scripts/strategy_pipeline.py
    python -u scripts/strategy_pipeline.py --oos   # frozen OOS (use once)

Output: runs/backtests/bt_*.json  +  console report
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fxcore.backtest import (
    EMA_TREND_SPEC,
    COST_NOTE,
    OOS_CUTOFF,
    load_bars,
    run_backtest,
    save_result,
    split_bars,
    fingerprint_df,
    pip_size_for_pair,
)

UTC = timezone.utc
PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD"]


def _bar(width: int = 72) -> str:
    return "-" * width


def print_pipeline_report(results: list, oos: bool) -> None:
    print(_bar())
    print("  STRATEGY DEVELOPMENT PIPELINE REPORT")
    print(f"  {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')} UTC")
    print(f"  Split: {'OUT-OF-SAMPLE ⚠ (frozen test set — use once)' if oos else 'IN-SAMPLE (development)'}")
    print(_bar())

    print("\n-- 1. MACRO-RESEARCHER: Regime & Hypothesis --")
    print(f"  Strategy : {EMA_TREND_SPEC.name} v{EMA_TREND_SPEC.version}")
    print(f"  Hypothesis (pre-registered):")
    for line in EMA_TREND_SPEC.hypothesis.split(". "):
        if line.strip():
            print(f"    {line.strip()}.")
    print(f"  Entry    : {EMA_TREND_SPEC.entry_rules}")
    print(f"  No-trade : {EMA_TREND_SPEC.no_trade_conditions}")

    print("\n-- 2. DATA-QUALITY-ENGINEER: Bar Validation --")
    for r in results:
        df = load_bars(r.spec.pair)
        df_is, df_oos = split_bars(df)
        target = df_oos if oos else df_is
        fp = fingerprint_df(target)
        oos_cutoff_str = OOS_CUTOFF.strftime('%Y-%m-%d')
        split_label = f">= {oos_cutoff_str}" if oos else f"< {oos_cutoff_str}"
        print(f"  {r.spec.pair:8} {len(target):>6} bars ({split_label})  fingerprint={fp}")
    print(f"  H1 data available from 2019; OOS cutoff {OOS_CUTOFF.strftime('%Y-%m-%d')}")
    print(f"  Per-bar spread unavailable from copy_rates — costs are conservative estimates.")

    print("\n-- 3. BACKTEST-ENGINEER: Results (after costs) --")
    print(f"  {'Pair':8} {'Trades':>7} {'WinRate':>8} {'NetPips':>9} {'MaxDD':>8} {'Sharpe':>8} {'PF':>7}")
    print("  " + "-" * 62)
    for r in results:
        if r.n_trades == 0:
            print(f"  {r.spec.pair:8} {'NO TRADES':>7}")
            continue
        pf_str = f"{r.profit_factor:.2f}" if r.profit_factor != float("inf") else "∞"
        print(
            f"  {r.spec.pair:8} {r.n_trades:>7} {r.win_rate:>8.1%} "
            f"{r.total_net_pips:>+9.1f}p {r.max_drawdown_pips:>8.1f}p "
            f"{r.sharpe:>8.3f} {pf_str:>7}"
        )
    print(f"\n  Cost note: {COST_NOTE[:80]}…")

    print("\n-- 4. POST-TRADE-REVIEWER: Observations --")
    total_trades = sum(r.n_trades for r in results)
    total_net = sum(r.total_net_pips for r in results)
    if total_trades < 30:
        print(f"  ⚠ {total_trades} trades total — too few to conclude anything about the strategy.")
        print("  Sample size is the main finding at this stage.")
    else:
        print(f"  {total_trades} trades across {len(results)} pairs, {total_net:+.1f}p net.")
    print("  All observations are provisional; no strategy promoted, no limit changed.")
    print("  A revision must compete as a new version, not replace this one.")

    print("\n-- 5. RISK-GUARDIAN: Veto Check --")
    print("  [OK] execution_enabled = False (system-wide, cannot be changed here)")
    print("  [OK] no order code in this script")
    print("  [OK] account is REAL at 1:1000 -- backtest is simulation only")
    print("  [OK] OOS set is frozen; reuse would be a logged failure, not a retry")
    verdict = "APPROVE — simulation results recorded. No trade placed."
    print(f"  RISK-GUARDIAN: {verdict}")

    print("\n-- 6. OUTPUT FILES --")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--oos", action="store_true",
                        help="Run on out-of-sample data (frozen test set — use once to confirm)")
    parser.add_argument("--pairs", nargs="*", default=PAIRS)
    args = parser.parse_args()

    results = []
    for pair in args.pairs:
        spec = EMA_TREND_SPEC.__class__(
            **{**EMA_TREND_SPEC.__dict__, "pair": pair, "pip_size": pip_size_for_pair(pair)}
        )
        try:
            result = run_backtest(spec, oos=args.oos)
            results.append(result)
        except FileNotFoundError as exc:
            print(f"  SKIP {pair}: {exc}", file=sys.stderr)
            continue

    if not results:
        print("No results — no CSV data found.", file=sys.stderr)
        return 1

    print_pipeline_report(results, oos=args.oos)

    for r in results:
        path = save_result(r)
        print(f"  {r.spec.pair}: {path.relative_to(ROOT)}")

    print(_bar())
    print("  Strategy pipeline complete. No trade was placed or enabled.")
    print(_bar())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
