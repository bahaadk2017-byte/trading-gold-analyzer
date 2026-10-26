"""Thin wrapper around src/fxcore/news.fetch() for the dashboard API.

Results are cached for `max_age_seconds` (default 300) to avoid hammering
the RSS feeds on every page load. Cache is in-process only — restarting the
server clears it.

Everything here is read-only and produces no trade signals.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fxcore.news import FetchResult, fetch, relevant_to, unmonitored_currencies

_cache: tuple[float, FetchResult] | None = None
_CACHE_TTL = 300.0  # seconds


def _get_cached() -> FetchResult:
    global _cache
    now = time.monotonic()
    if _cache is None or (now - _cache[0]) > _CACHE_TTL:
        result = fetch()
        _cache = (now, result)
    return _cache[1]


def fetch_all() -> dict:
    """Return all news items and metadata for the dashboard."""
    result = _get_cached()
    return {
        "items": [_item_dict(i) for i in result.items[:50]],
        "rejected_count": len(result.rejected),
        "failed_feeds": list(result.failed_feeds),
        "classification": "untrusted",  # every item, always
    }


def fetch_relevant(pairs: list[str]) -> dict:
    """Return news relevant to the given pairs, plus unmonitored-currency gaps."""
    result = _get_cached()
    seen: set[str] = set()
    filtered: list[dict] = []
    for pair in pairs:
        try:
            for item in relevant_to(result.items, pair):
                if item.url not in seen:
                    seen.add(item.url)
                    filtered.append(_item_dict(item))
        except ValueError:
            pass
    filtered.sort(key=lambda i: i["published_at_utc"], reverse=True)
    gaps = unmonitored_currencies(pairs)
    return {
        "items": filtered[:30],
        "unmonitored": [
            {"currency": c, "reason": r} for c, r in gaps.items()
        ],
        "failed_feeds": list(result.failed_feeds),
        "classification": "untrusted",
    }


def _item_dict(item: object) -> dict:
    return {
        "title": item.title,           # type: ignore[attr-defined]
        "url": item.url,
        "published_at_utc": item.published_at_utc.isoformat(),
        "institution": item.institution,
        "currency": item.currency,
        "feed_id": item.feed_id,
        "injection_flags": list(item.injection_flags),
        "classification": item.classification,  # always "untrusted"
    }
