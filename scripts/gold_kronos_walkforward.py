"""Experimental: does Kronos-small beat naive persistence on gold M5 bars?

Run from the repository root:
    .venv/kronos/Scripts/python.exe -I scripts/gold_kronos_walkforward.py --count 50

Walks the last `count` closed bars. At each step the context is the 512 bars
ending at that point, the model forecasts the next close, and the error is
compared against the naive baseline "next close = last close". Directional hit
rate is reported against the same baseline's implied coin flip.

This is the measurement the weight-0 verdict in docs/data-sources.md §5 says
Kronos needs before any output of it can carry decision weight.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fxcore.clock import ServerClock
from fxcore.contracts import Bar
from fxcore.enrichment import CONTEXT_BARS, KronosRunner

UTC = timezone.utc
SYMBOL = "GOLDm#"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--timeframe", default="M5")
    args = parser.parse_args()

    import MetaTrader5 as mt5

    if not mt5.initialize():
        raise SystemExit(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        mt5.symbol_select(SYMBOL, True)
        tick = mt5.symbol_info_tick(SYMBOL)
        clock = ServerClock.measure(tick.time, datetime.now(UTC))
        tf = getattr(mt5, f"TIMEFRAME_{args.timeframe}")
        seconds = {"M5": 300, "M15": 900, "H1": 3600}[args.timeframe]
        need = CONTEXT_BARS + args.count + 1
        rates = mt5.copy_rates_from_pos(SYMBOL, tf, 0, need + 10)
        if rates is None or len(rates) < need + 1:
            raise SystemExit(f"got {0 if rates is None else len(rates)} bars, need {need + 1}")
        bars = tuple(
            Bar(
                event_time_utc=clock.to_utc(int(r[0])),
                timeframe_seconds=seconds,
                open=float(r[1]),
                high=float(r[2]),
                low=float(r[3]),
                close=float(r[4]),
                tick_updates=int(r[5]),
            )
            for r in rates[:-1]  # newest bar is still forming
        )
    finally:
        mt5.shutdown()

    runner = KronosRunner(ROOT, device="cuda:0")
    kronos_abs = naive_abs = 0.0
    hits = flats = 0
    for i in range(args.count, 0, -1):
        end = len(bars) - i
        context = bars[end - CONTEXT_BARS : end]
        actual = bars[end]
        predicted = runner.predict_close(context)
        last = context[-1].close
        kronos_abs += abs(predicted - actual.close)
        naive_abs += abs(last - actual.close)
        real_move = actual.close - last
        pred_move = predicted - last
        if pred_move == 0 or real_move == 0:
            flats += 1
        elif (pred_move > 0) == (real_move > 0):
            hits += 1

    scored = args.count - flats
    print(f"symbol={SYMBOL} timeframe={args.timeframe} bars_scored={args.count}")
    print(f"window={bars[-args.count].event_time_utc.isoformat()} .. {bars[-1].event_time_utc.isoformat()}")
    print(f"kronos_mae_usd={kronos_abs / args.count:.3f}")
    print(f"naive_mae_usd={naive_abs / args.count:.3f}")
    print(f"skill_vs_naive={1 - (kronos_abs / naive_abs):+.1%}  (positive = Kronos better)")
    print(f"direction_hits={hits}/{scored} = {hits / scored:.1%}  flat_excluded={flats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
