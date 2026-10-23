"""Unified entry point: validated data -> gates -> multi-timeframe analysis.

One command for the whole read-only pipeline. Every pair either produces an
interpretable analysis with confidence and limits, or a NO_TRADE with the
reason. Writes an immutable run record under runs/.

Usage:
    python -u scripts/analyze.py                      # all default pairs
    python -u scripts/analyze.py EURUSD GBPUSD        # specific pairs
    python -u scripts/analyze.py --json               # machine-readable
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fxcore.analysis import Bias, analyse
from fxcore.quality import evaluate
from fxcore.sources.mt5_source import MT5Source

UTC = timezone.utc
DEFAULT_PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD"]
TIMEFRAMES = ["M15", "H1", "H4", "D1"]
BARS = 200
MAX_SPREAD_PIPS = 3.0


def run(pairs: list[str]) -> dict:
    started = datetime.now(UTC)
    results: list[dict] = []

    with MT5Source() as src:
        account = src.account_summary()
        src.measure_clock(src.resolve_broker_symbol(pairs[0]))
        clock = src.clock
        assert clock is not None

        for pair in pairs:
            entry: dict = {"pair": pair}
            try:
                broker = src.resolve_broker_symbol(pair)
            except Exception as exc:  # noqa: BLE001 - one bad pair must not stop the run
                results.append({**entry, "decision": "NO_TRADE", "reason": str(exc)})
                continue

            entry["broker_symbol"] = broker
            bars_by_tf: dict[str, tuple] = {}
            blocking: list[str] = []
            snapshot = None

            for tf in TIMEFRAMES:
                snap = src.fetch(pair, tf, BARS, broker_symbol=broker)
                verdict = evaluate(
                    snap,
                    clock,
                    datetime.now(UTC),
                    expected_bars=BARS,
                    max_spread_pips=MAX_SPREAD_PIPS,
                )
                if verdict.tradable:
                    bars_by_tf[tf] = snap.bars
                    snapshot = snap
                else:
                    blocking.append(f"{tf}: {verdict.reason}")

            if not bars_by_tf:
                results.append(
                    {**entry, "decision": "NO_TRADE", "reason": " | ".join(blocking)}
                )
                continue

            assert snapshot is not None
            analysis = analyse(pair, broker, bars_by_tf, snapshot.spec)
            entry.update(
                decision="ANALYSED",
                bias=analysis.bias.value,
                confidence=analysis.confidence,
                spread_pips=round(snapshot.spec.spread_pips, 1),
                timeframes={
                    r.timeframe: {
                        "bias": r.bias.value,
                        "slope_pips_per_bar": round(r.slope_pips_per_bar, 3),
                        "atr_pips": round(r.atr_pips, 1),
                        "range_position": round(r.range_position, 3),
                        "structure": r.structure,
                        "evidence": list(r.evidence),
                    }
                    for r in analysis.reads
                },
                conflicts=list(analysis.conflicts),
                limits=list(analysis.limits),
                gates_blocked=blocking,
                data_fingerprint=snapshot.fingerprint,
            )
            results.append(entry)

    return {
        "started_utc": started.isoformat(),
        "finished_utc": datetime.now(UTC).isoformat(),
        "server_offset_hours": clock.offset_hours,
        "account": {k: v for k, v in account.items() if k != "login"},
        "execution_enabled": False,  # no order code exists in this system
        "results": results,
    }


def print_report(report: dict) -> None:
    acct = report["account"]
    print("=" * 74)
    print(f"  FX ANALYSIS RUN   {report['started_utc']}")
    print(
        f"  source: {acct['server']}   offset: {report['server_offset_hours']:+.1f}h"
        f"   real account: {acct['is_real_account']}"
    )
    print(f"  execution: DISABLED (no order code exists)")
    print("=" * 74)

    analysed = [r for r in report["results"] if r["decision"] == "ANALYSED"]
    blocked = [r for r in report["results"] if r["decision"] == "NO_TRADE"]

    if analysed:
        print(f"\n  {'pair':8} {'bias':6} {'conf':>5} {'spread':>7}  {'M15 H1  H4  D1':16}")
        print("  " + "-" * 60)
        for r in analysed:
            tfs = r["timeframes"]
            marks = " ".join(
                {"up": " ^ ", "down": " v ", "flat": " - "}[tfs[tf]["bias"]]
                if tf in tfs
                else " ? "
                for tf in TIMEFRAMES
            )
            print(
                f"  {r['pair']:8} {r['bias']:6} {r['confidence']:>5.2f} "
                f"{r['spread_pips']:>6.1f}p  {marks}"
            )

        for r in analysed:
            if r["conflicts"] or r["gates_blocked"]:
                print(f"\n  {r['pair']}:")
                for c in r["conflicts"]:
                    print(f"    conflict: {c}")
                for g in r["gates_blocked"]:
                    print(f"    gate blocked {g}")

    if blocked:
        print("\n  NO_TRADE")
        for r in blocked:
            print(f"    {r['pair']}: {r['reason']}")

    print("\n  LIMITS ON EVERY NUMBER ABOVE")
    for limit in (analysed[0]["limits"] if analysed else []):
        print(f"    - {limit}")
    print("=" * 74)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    pairs = [a.upper() for a in args] or DEFAULT_PAIRS

    report = run(pairs)

    runs = ROOT / "runs"
    runs.mkdir(exist_ok=True)
    stamp = report["started_utc"].replace(":", "").replace("-", "")[:15]
    path = runs / f"analysis_{stamp}.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    if "--json" in sys.argv:
        print(json.dumps(report, indent=2, default=str))
    else:
        print_report(report)
        print(f"\n  run record: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
