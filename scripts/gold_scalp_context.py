"""Experimental: Kronos-small forecasts on broker gold bars for scalp context.

Run from the repository root:
    .venv/kronos/Scripts/python.exe -I scripts/gold_scalp_context.py

Gold has never been through this system's quality gates, strategy specs or
backtests, and Kronos still carries weight=0 (docs/data-sources.md §5). This
script therefore produces CONTEXT ONLY and is not decision-grade output.

It deliberately bypasses SymbolSpec/MarketSnapshot, which are shaped for
six-letter FX pairs, and uses only ServerClock, Bar and KronosRunner.
"""

from __future__ import annotations

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
TIMEFRAMES = (("M5", 300), ("M15", 900), ("H1", 3600))


def atr(bars: tuple[Bar, ...], period: int = 14) -> float:
    """Average true range over the last `period` bars."""
    trs = [
        max(b.high - b.low, abs(b.high - p.close), abs(b.low - p.close))
        for p, b in zip(bars[-period - 1 : -1], bars[-period:])
    ]
    return sum(trs) / len(trs)


def main() -> int:
    import MetaTrader5 as mt5

    if not mt5.initialize():
        raise SystemExit(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        if not mt5.symbol_select(SYMBOL, True):
            raise SystemExit(f"cannot select {SYMBOL}: {mt5.last_error()}")
        tick = mt5.symbol_info_tick(SYMBOL)
        spec = mt5.symbol_info(SYMBOL)
        clock = ServerClock.measure(tick.time, datetime.now(UTC))

        series: dict[str, tuple[Bar, ...]] = {}
        for name, seconds in TIMEFRAMES:
            tf = getattr(mt5, f"TIMEFRAME_{name}")
            rates = mt5.copy_rates_from_pos(SYMBOL, tf, 0, CONTEXT_BARS + 60)
            if rates is None or len(rates) < CONTEXT_BARS + 1:
                raise SystemExit(f"{name}: got {0 if rates is None else len(rates)} bars")
            # The newest bar is still forming; a forecast may not read it.
            series[name] = tuple(
                Bar(
                    event_time_utc=clock.to_utc(int(r[0])),
                    timeframe_seconds=seconds,
                    open=float(r[1]),
                    high=float(r[2]),
                    low=float(r[3]),
                    close=float(r[4]),
                    tick_updates=int(r[5]),
                )
                for r in rates[:-1]
            )
    finally:
        mt5.shutdown()

    print(f"symbol={SYMBOL} digits={spec.digits} contract_size={spec.trade_contract_size}")
    print(f"bid={tick.bid} ask={tick.ask} spread_usd={tick.ask - tick.bid:.2f}")
    print(f"server_offset_hours={clock.offset_hours} residue_s={clock.raw_residue_seconds}")
    print(f"now_utc={datetime.now(UTC).isoformat()}")

    runner = KronosRunner(ROOT, device="cuda:0")
    for name, _ in TIMEFRAMES:
        bars = series[name]
        context = bars[-CONTEXT_BARS:]
        last = context[-1]
        forecast = runner.predict_close(context)
        move = forecast - last.close
        band = atr(bars)
        window = bars[-20:]
        print(
            f"\n[{name}] last_closed_bar={last.event_time_utc.isoformat()} "
            f"close={last.close:.2f}"
        )
        print(f"  kronos_forecast_next_close={forecast:.2f} move_usd={move:+.2f}")
        print(f"  move_in_spreads={move / (tick.ask - tick.bid):+.1f} atr14={band:.2f}")
        print(
            f"  last20_high={max(b.high for b in window):.2f} "
            f"last20_low={min(b.low for b in window):.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
