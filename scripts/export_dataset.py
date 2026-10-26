"""Export validated H1 bars for model evaluation, split by Kronos's publication date.

Kronos v1 was submitted 2025-08-02 and its paper never states the date range of
its 12-billion-record training corpus. Leakage therefore cannot be ruled out for
any earlier period, so only data after that date counts as out-of-sample. The
cutoff here is 2025-09-01, a month later, to allow for lag between submission
and the released weights.

Usage:  python -u scripts/export_dataset.py
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fxcore.quality import evaluate
from fxcore.sources.mt5_source import MT5Source

UTC = timezone.utc
PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD"]
TIMEFRAME = "H1"

# Kronos v1 on arXiv: 2025-08-02. One month of slack for the weights release.
OOS_START = datetime(2025, 9, 1, tzinfo=UTC)

# Usable contiguous H1 history begins 2019 across all seven pairs.
HISTORY_START = datetime(2019, 1, 1, tzinfo=UTC)

OUT = ROOT / "data" / "h1"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"out-of-sample cutoff: {OOS_START.date()} (Kronos v1 arXiv 2025-08-02)")

    summary = []
    with MT5Source() as src:
        src.measure_clock(src.resolve_broker_symbol(PAIRS[0]))
        clock = src.clock
        assert clock is not None
        request = src.max_bars - 1000

        for pair in PAIRS:
            broker = src.resolve_broker_symbol(pair)
            snap = src.fetch(pair, TIMEFRAME, request, broker_symbol=broker)

            verdict = evaluate(
                snap, clock, datetime.now(UTC), expected_bars=len(snap.bars) or 1
            )
            if not verdict.tradable:
                print(f"  {pair}: {verdict.reason} - skipped")
                continue

            bars = [b for b in snap.bars if b.event_time_utc >= HISTORY_START]
            if not bars:
                print(f"  {pair}: no bars after {HISTORY_START.date()} - skipped")
                continue

            path = OUT / f"{pair}.csv"
            with path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(
                    ["timestamps", "open", "high", "low", "close", "tick_updates"]
                )
                for b in bars:
                    writer.writerow(
                        [
                            b.event_time_utc.strftime("%Y-%m-%d %H:%M:%S"),
                            f"{b.open:.5f}",
                            f"{b.high:.5f}",
                            f"{b.low:.5f}",
                            f"{b.close:.5f}",
                            b.tick_updates,
                        ]
                    )

            oos = [b for b in bars if b.event_time_utc >= OOS_START]
            summary.append((pair, broker, len(bars), len(oos), bars[0], bars[-1]))
            print(
                f"  {pair:8} {broker:10} {len(bars):>6} bars  "
                f"{len(oos):>5} out-of-sample  "
                f"{bars[0].event_time_utc.date()} -> {bars[-1].event_time_utc.date()}  "
                "gates=PASS"
            )

    total_oos = sum(s[3] for s in summary)
    print(f"\n  {len(summary)} pairs, {total_oos} out-of-sample H1 bars in total")
    print(f"  written to {OUT.relative_to(ROOT)}")
    if total_oos < 5000:
        print("  WARNING: out-of-sample sample is small; conclusions will be weak")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
