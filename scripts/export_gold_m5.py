"""Export validated GOLDm# M5 bars for scalp-baseline backtesting.

Usage:  .venv/kronos/Scripts/python.exe -I scripts/export_gold_m5.py

Gold is NOT an approved instrument in this system: no strategy spec, no cost
model, no prior backtest. This export exists so a baseline can be measured on
frozen data rather than on a live stream. The bars themselves come from the
decision-approved source (MT5 / XM Global) through the same adapter and quality
gates as the FX pairs.

The train/test cutoff is declared here, before any strategy is run, and is
chronological: roughly 60% in-sample for selection, 40% held back.
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
ANALYSIS_SYMBOL = "GOLD"
TIMEFRAME = "M5"

# Declared 2026-10-26 before any baseline was run. Gold M5 history at this
# broker starts 2025-06-03, so this leaves ~10 months to select on and ~7
# months held back.
OOS_START = datetime(2026, 4, 1, tzinfo=UTC)

OUT = ROOT / "data" / "m5"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with MT5Source() as src:
        broker = src.resolve_broker_symbol(ANALYSIS_SYMBOL)
        src.measure_clock(broker)
        clock = src.clock
        assert clock is not None
        print(f"broker_symbol={broker} server_offset_hours={clock.offset_hours}")

        # Defect 6: asking for the full maxbars returns zero, not an error.
        request = src.max_bars - 1000
        snap = src.fetch(ANALYSIS_SYMBOL, TIMEFRAME, request, broker_symbol=broker)
        spec = snap.spec
        print(
            f"digits={spec.digits} point={spec.point} pip_size={spec.pip_size} "
            f"contract_size={spec.contract_size} spread_points={spec.spread_points} "
            f"spread_float={spec.spread_float}"
        )
        print(f"swap_long={spec.swap_long} swap_short={spec.swap_short}")

        verdict = evaluate(
            snap, clock, datetime.now(UTC), expected_bars=len(snap.bars) or 1
        )
        print(f"quality_tradable={verdict.tradable} reason={verdict.reason}")

        # The newest bar is still forming and may never be read as complete.
        bars = snap.bars[:-1]
        if not bars:
            raise SystemExit("no bars returned")

        path = OUT / "GOLD.csv"
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["timestamps", "open", "high", "low", "close", "tick_updates"])
            for b in bars:
                writer.writerow(
                    [
                        b.event_time_utc.strftime("%Y-%m-%d %H:%M:%S"),
                        b.open,
                        b.high,
                        b.low,
                        b.close,
                        b.tick_updates,
                    ]
                )

    is_count = sum(1 for b in bars if b.event_time_utc < OOS_START)
    print(f"wrote {path} bars={len(bars)}")
    print(f"range={bars[0].event_time_utc.isoformat()} .. {bars[-1].event_time_utc.isoformat()}")
    print(f"oos_cutoff={OOS_START.date()} in_sample={is_count} out_of_sample={len(bars) - is_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
