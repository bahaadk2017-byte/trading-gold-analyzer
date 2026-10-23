"""Is the reported history depth real? Checks the cap, contiguity and old bars.

Finding that shaped this script: terminal_info().maxbars is 100000, and asking
for more than that returns 0 bars rather than an error or a truncated series.
Every request here therefore stays under the cap.
"""

from __future__ import annotations

import collections
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import MetaTrader5 as mt5

from fxcore.clock import ServerClock, is_fx_market_closed

UTC = timezone.utc

mt5.initialize()
MAXBARS = getattr(mt5.terminal_info(), "maxbars", 0)
SAFE = MAXBARS - 1000  # stay clear of the silent-zero cliff
print(f"TERMINAL maxbars = {MAXBARS}  -> requesting {SAFE} per call")

mt5.symbol_select("EURUSDm#", True)
clock = ServerClock.measure(mt5.symbol_info_tick("EURUSDm#").time, datetime.now(UTC))


def bars(sym: str, tf: int, n: int) -> list:
    r = mt5.copy_rates_from_pos(sym, tf, 0, n)
    return [] if r is None else list(r)


print("\n--- 1) THE CAP IS A CLIFF, NOT A CEILING (EURUSDm# M15) ---")
for n in (SAFE, MAXBARS, MAXBARS + 1, 200_000):
    print(f"  request {n:>7} -> {len(bars('EURUSDm#', mt5.TIMEFRAME_M15, n)):>7} bars")

print("\n--- 2) EURUSDm# H1 BARS PER YEAR (contiguous would be ~6000/yr) ---")
h1 = bars("EURUSDm#", mt5.TIMEFRAME_H1, SAFE)
per_year = collections.Counter(clock.to_utc(int(b[0])).year for b in h1)
print(f"  total {len(h1)} bars across {len(per_year)} years")
for y in sorted(per_year):
    print(f"    {y}  {per_year[y]:>6}  {'#' * (per_year[y] // 150)}")

print("\n--- 3) USDJPYm# H4 OLDEST BARS (the table claimed 1971) ---")
mt5.symbol_select("USDJPYm#", True)
h4 = bars("USDJPYm#", mt5.TIMEFRAME_H4, SAFE)
print(f"  total {len(h4)} bars")
for b in h4[:6]:
    print(
        f"    {clock.to_utc(int(b[0]))}  o={b[1]} h={b[2]} l={b[3]} c={b[4]} "
        f"ticks={int(b[5])}"
    )
h4_years = collections.Counter(clock.to_utc(int(b[0])).year for b in h4)
sparse = sorted(y for y in h4_years if h4_years[y] < 500)
dense = sorted(y for y in h4_years if h4_years[y] >= 500)
print(f"  years with <500 H4 bars (contiguous would be ~1500): {sparse}")
print(f"  years with >=500: {dense[0] if dense else None}..{dense[-1] if dense else None}")

print("\n--- 4) UNEXPLAINED GAPS, EURUSDm# H1, LAST 2 YEARS ---")
cut = datetime.now(UTC) - timedelta(days=730)
times = [t for t in (clock.to_utc(int(b[0])) for b in h1) if t >= cut]
weekend = unexplained = 0
worst: list[tuple[int, datetime]] = []
for a, c in zip(times, times[1:]):
    gap = round((c - a).total_seconds() / 3600) - 1
    if gap <= 0:
        continue
    if is_fx_market_closed(a + timedelta(hours=1)):
        weekend += gap
    else:
        unexplained += gap
        worst.append((gap, a))
print(f"  bars={len(times)}  weekend-explained={weekend}  UNEXPLAINED={unexplained}")
for gap, after in sorted(worst, reverse=True)[:8]:
    print(f"    {gap:>4} bars missing after {after.isoformat()}")

mt5.shutdown()
