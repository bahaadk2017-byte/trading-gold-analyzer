"""Phase 2 report: from when is each pair/timeframe actually usable?

Answers the question the backtest design depends on — whether walk-forward is
possible at all, and over what span. Read-only.

Usage:  python -u scripts/report_history_usability.py
"""

from __future__ import annotations

import collections
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fxcore.clock import is_fx_market_closed
from fxcore.sources.mt5_source import MT5Source

UTC = timezone.utc
PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD"]
TIMEFRAMES = ["M15", "H1", "H4", "D1"]

# FX trades ~24h x 5 days, so ~6240 market hours per year.
EXPECTED_PER_YEAR = {"M15": 24_960, "H1": 6_240, "H4": 1_560, "D1": 260}
DENSITY_THRESHOLD = 0.90


def main() -> int:
    with MT5Source() as src:
        src.measure_clock(src.resolve_broker_symbol("EURUSD"))
        clock = src.clock
        assert clock is not None
        print(f"terminal max_bars = {src.max_bars}  (requests stay below it)")
        print(f"true UTC now      = {datetime.now(UTC).isoformat()}")
        print(f"server offset     = {clock.offset_hours:+.1f}h\n")

        header = (
            f"{'pair':8} {'tf':4} {'bars':>7} {'oldest':>11} {'usable from':>12} "
            f"{'flat%':>6} {'gaps/2y':>8}  cap"
        )
        print(header)
        print("-" * len(header))

        rows = []
        for pair in PAIRS:
            broker = src.resolve_broker_symbol(pair)
            for tf in TIMEFRAMES:
                d = src.history_depth(broker, tf)
                if not d["bars"]:
                    print(f"{pair:8} {tf:4} {'0':>7}  no data")
                    continue

                rates = src._mt5.copy_rates_from_pos(  # noqa: SLF001 - reporting tool
                    broker, src._tf_const(tf), 0, src.max_bars - 1000
                )
                times = [clock.to_utc(int(r[0])) for r in rates]
                flat = sum(1 for r in rates if r[2] == r[3] and int(r[5]) <= 1)

                # earliest year whose bar count reaches the density threshold
                per_year = collections.Counter(t.year for t in times)
                expected = EXPECTED_PER_YEAR[tf]
                this_year = datetime.now(UTC).year
                usable = next(
                    (
                        y
                        for y in sorted(per_year)
                        if y < this_year and per_year[y] >= expected * DENSITY_THRESHOLD
                    ),
                    None,
                )

                cut = datetime.now(UTC) - timedelta(days=730)
                recent = [t for t in times if t >= cut]
                step = {"M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}[tf]
                unexplained = 0
                for a, c in zip(recent, recent[1:]):
                    gap = round((c - a).total_seconds() / step) - 1
                    if gap > 0 and not is_fx_market_closed(a + timedelta(seconds=step)):
                        unexplained += gap

                oldest = d["oldest_utc"]
                print(
                    f"{pair:8} {tf:4} {d['bars']:>7} "
                    f"{oldest.date().isoformat():>11} "
                    f"{str(usable or 'NONE'):>12} "
                    f"{100 * flat / len(rates):>5.1f}% {unexplained:>8}  "
                    f"{'YES' if d['cap_limited'] else '-'}"
                )
                rows.append((pair, tf, usable, unexplained))

        print("\nSUMMARY")
        for tf in TIMEFRAMES:
            usable_years = [r[2] for r in rows if r[1] == tf and r[2]]
            gaps = [r[3] for r in rows if r[1] == tf]
            if usable_years:
                print(
                    f"  {tf:4} usable from {max(usable_years)} across all pairs; "
                    f"unexplained gaps/2y: min {min(gaps)}, max {max(gaps)}"
                )
            else:
                print(f"  {tf:4} no pair reaches {DENSITY_THRESHOLD:.0%} density")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
