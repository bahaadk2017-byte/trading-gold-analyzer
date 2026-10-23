"""Fetch official central-bank news as sourced, untrusted facts.

Usage:
    python -u scripts/news.py                  # all feeds
    python -u scripts/news.py EURUSD GBPUSD    # filter to these pairs
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fxcore.news import FEEDS, fetch, relevant_to, unmonitored_currencies


def main() -> int:
    pairs = [a.upper() for a in sys.argv[1:] if not a.startswith("--")]

    print(f"fetching {len(FEEDS)} official feeds (certificate verification ON)...")
    result = fetch()

    items = result.items
    if pairs:
        seen, filtered = set(), []
        for pair in pairs:
            for item in relevant_to(items, pair):
                if item.url not in seen:
                    seen.add(item.url)
                    filtered.append(item)
        items = tuple(sorted(filtered, key=lambda i: i.published_at_utc, reverse=True))

    print(f"\n{len(items)} items — ALL CLASSIFIED UNTRUSTED (data, never instruction)\n")
    for item in items[:30]:
        flag = f"  [FLAGGED: {', '.join(item.injection_flags)}]" if item.injection_flags else ""
        print(f"  {item.published_at_utc.strftime('%Y-%m-%d %H:%M')}Z  {item.currency}  "
              f"{item.institution}{flag}")
        print(f"    {item.title[:92]}")
        print(f"    {item.url}")

    if result.rejected:
        print(f"\nREJECTED ({len(result.rejected)}) — missing URL or publication time:")
        for reason in result.rejected[:10]:
            print(f"  - {reason}")

    if result.failed_feeds:
        print(f"\nFEEDS THAT FAILED ({len(result.failed_feeds)}):")
        for reason in result.failed_feeds:
            print(f"  - {reason}")

    gaps = unmonitored_currencies(pairs or ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD",
                                            "USDCAD", "USDCHF", "NZDUSD"])
    if gaps:
        print("\nUNMONITORED EVENT RISK — no working official feed:")
        for currency, why in gaps.items():
            print(f"  {currency}: {why}")

    print("\nNothing above is a recommendation. These are sourced facts only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
