"""Run one deterministic Kronos-small forecast on broker H1 data.

Run from the repository root with the isolated environment:
    .venv/kronos/Scripts/python.exe -I scripts/kronos_smoke.py

The external checkout and model revisions are pinned for reproducibility. This is
only an installation smoke test; it cannot give Kronos decision weight.
"""

from __future__ import annotations

import argparse
import sys
from datetime import timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fxcore.contracts import Bar
from fxcore.enrichment import CONTEXT_BARS, KronosRunner


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair", default="EURUSD")
    parser.add_argument("--device", default="cuda:0")
    args = parser.parse_args()

    import pandas as pd

    path = ROOT / "data" / "h1" / f"{args.pair}.csv"
    df = pd.read_csv(path, parse_dates=["timestamps"])
    if len(df) < CONTEXT_BARS + 1:
        raise ValueError(f"{path} needs at least {CONTEXT_BARS + 1} bars")

    context_df = df.iloc[-(CONTEXT_BARS + 1) : -1]
    context = tuple(
        Bar(
            event_time_utc=row.timestamps.to_pydatetime().replace(tzinfo=timezone.utc),
            timeframe_seconds=3600,
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            tick_updates=int(row.tick_updates),
        )
        for row in context_df.itertuples()
    )
    target = df.iloc[-1]
    predicted = KronosRunner(ROOT, device=args.device).predict_close(context)
    actual = float(target["close"])
    print(f"pair={args.pair} device={args.device}")
    print(f"forecast_close={predicted:.5f} actual_close={actual:.5f}")
    print("status=SMOKE_PASS weight=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
