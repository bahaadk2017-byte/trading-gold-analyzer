"""Official-source news ingestion. Every item is untrusted data.

Two rules drive this module.

First, an item without a trustworthy URL and a publication time is rejected.
Without a publication time there is no way to know whether the information
existed at decision time, so it cannot enter a backtest or a decision.

Second, everything fetched is data, never instruction. A feed is third-party
content that may try to steer a financial decision by impersonating a command.
Items are flagged, never obeyed, and never reach an agent with execution
authority.

Sources are official central banks and statistics offices only. Certificate
verification stays on; a feed that fails it is recorded as unavailable rather
than fetched insecurely.
"""

from __future__ import annotations

import re
import ssl
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc
USER_AGENT = "fxcore-news/0.1 (FX research; non-commercial)"

# Measured 2026-10-23: these feeds returned parsable entries with both a link
# and a publication time. SNB (404) and RBNZ (403) did not — see UNAVAILABLE.
FEEDS: dict[str, dict[str, str]] = {
    "fed_monetary": {
        "url": "https://www.federalreserve.gov/feeds/press_monetary.xml",
        "institution": "Federal Reserve",
        "currency": "USD",
    },
    "fed_all": {
        "url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "institution": "Federal Reserve",
        "currency": "USD",
    },
    "ecb_press": {
        "url": "https://www.ecb.europa.eu/rss/press.html",
        "institution": "European Central Bank",
        "currency": "EUR",
    },
    "ecb_statpress": {
        "url": "https://www.ecb.europa.eu/rss/statpress.html",
        "institution": "European Central Bank",
        "currency": "EUR",
    },
    "boe_news": {
        "url": "https://www.bankofengland.co.uk/rss/news",
        "institution": "Bank of England",
        "currency": "GBP",
    },
    "boj_news": {
        "url": "https://www.boj.or.jp/en/rss/whatsnew.xml",
        "institution": "Bank of Japan",
        "currency": "JPY",
    },
    "boc_press": {
        "url": "https://www.bankofcanada.ca/content_type/press-releases/feed/",
        "institution": "Bank of Canada",
        "currency": "CAD",
    },
}

# Currencies we trade but have no working official feed for. Event risk on these
# is unmonitored, and that must be stated rather than quietly ignored.
#
# All three reject this client. A browser user-agent would likely get through,
# but impersonating one to defeat a server's own access decision is exactly the
# circumvention this project does not do. These stay unmonitored until there is
# a documented, permitted route.
UNAVAILABLE: dict[str, str] = {
    "CHF": "SNB feed returned 404 on 2026-10-23; no working URL found",
    "NZD": "RBNZ feed returned 403 on 2026-10-23; rejects this client",
    "AUD": "RBA feed returned 403 on 2026-10-23; rejects this client",
}

# Phrases that would be instructions if this text were trusted. Their presence
# does not make an item malicious, but it is flagged for the reader.
_INJECTION_PATTERNS = (
    r"ignore (?:all |any |the )?(?:previous|prior|above)",
    r"disregard (?:all |any |the )?(?:previous|prior|above)",
    r"you are now",
    r"new instructions?",
    r"system prompt",
    r"</?(?:system|assistant|instructions?)>",
    r"\bbuy now\b",
    r"\bsell now\b",
    r"execute (?:the )?(?:trade|order)",
)
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.I)


@dataclass(frozen=True)
class NewsItem:
    """One sourced fact. `trusted` is deliberately absent — nothing here is."""

    title: str
    url: str
    published_at_utc: datetime
    institution: str
    currency: str
    feed_id: str
    retrieved_at_utc: datetime
    injection_flags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def classification(self) -> str:
        return "untrusted"

    @property
    def age_hours(self) -> float:
        return (datetime.now(UTC) - self.published_at_utc).total_seconds() / 3600

    def available_at(self, decision_time_utc: datetime) -> bool:
        """Whether this item existed at a given decision time (anti-lookahead)."""
        return self.published_at_utc <= decision_time_utc


@dataclass(frozen=True)
class FetchResult:
    items: tuple[NewsItem, ...]
    rejected: tuple[str, ...]  # why each dropped item was dropped
    failed_feeds: tuple[str, ...]


def _fetch_bytes(url: str, timeout: float = 20.0) -> bytes:
    """Download a feed with certificate verification ON, using certifi's bundle.

    We fetch rather than let feedparser do it: feedparser builds its own opener
    and ignores a globally installed one, so ECB and RBA failed verification
    against the system store. The fix is a correct CA bundle under our control,
    never disabling verification.
    """
    import certifi

    ctx = ssl.create_default_context(cafile=certifi.where())
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout, context=ctx) as response:
        return response.read()


def _to_utc(parsed: time.struct_time) -> datetime:
    return datetime(*parsed[:6], tzinfo=UTC)


def _flags(text: str) -> tuple[str, ...]:
    return tuple(sorted({m.group(0).lower() for m in _INJECTION_RE.finditer(text)}))


def fetch(
    feed_ids: list[str] | None = None, per_feed_limit: int = 20
) -> FetchResult:
    """Fetch official feeds and return only items that carry URL and timestamp."""
    import feedparser

    items: list[NewsItem] = []
    rejected: list[str] = []
    failed: list[str] = []
    now = datetime.now(UTC)

    for feed_id in feed_ids or list(FEEDS):
        meta = FEEDS.get(feed_id)
        if meta is None:
            failed.append(f"{feed_id}: not a configured feed")
            continue

        try:
            raw = _fetch_bytes(meta["url"])
        except Exception as exc:  # noqa: BLE001 - one bad feed must not stop the rest
            failed.append(f"{feed_id}: fetch failed ({type(exc).__name__}: {exc})")
            continue

        parsed = feedparser.parse(raw)
        if not parsed.entries:
            exc = getattr(parsed, "bozo_exception", None)
            failed.append(
                f"{feed_id}: parsed but no entries "
                f"({type(exc).__name__ if exc else 'no error'})"
            )
            continue

        for entry in parsed.entries[:per_feed_limit]:
            url = getattr(entry, "link", None)
            stamp = getattr(entry, "published_parsed", None) or getattr(
                entry, "updated_parsed", None
            )
            title = (getattr(entry, "title", "") or "").strip()

            # The hard rule: no URL or no publication time means rejected.
            if not url:
                rejected.append(f"{feed_id}: {title[:50]!r} has no URL")
                continue
            if not stamp:
                rejected.append(f"{feed_id}: {title[:50]!r} has no publication time")
                continue
            if not title:
                rejected.append(f"{feed_id}: an entry had no title")
                continue

            published = _to_utc(stamp)
            if published > now:
                rejected.append(
                    f"{feed_id}: {title[:40]!r} is stamped in the future "
                    f"({published.isoformat()})"
                )
                continue

            # The two Fed feeds overlap, so the same release arrives twice.
            if any(existing.url == url for existing in items):
                continue

            summary = getattr(entry, "summary", "") or ""
            items.append(
                NewsItem(
                    title=title,
                    url=url,
                    published_at_utc=published,
                    institution=meta["institution"],
                    currency=meta["currency"],
                    feed_id=feed_id,
                    retrieved_at_utc=now,
                    injection_flags=_flags(f"{title} {summary}"),
                )
            )

    items.sort(key=lambda i: i.published_at_utc, reverse=True)
    return FetchResult(tuple(items), tuple(rejected), tuple(failed))


def relevant_to(items: tuple[NewsItem, ...], pair: str) -> tuple[NewsItem, ...]:
    """Items bearing on either leg of a pair, e.g. EURUSD -> EUR or USD."""
    pair = pair.upper()
    if len(pair) < 6:
        raise ValueError(f"expected a 6-letter pair, got {pair!r}")
    legs = {pair[:3], pair[3:6]}
    return tuple(i for i in items if i.currency in legs)


def unmonitored_currencies(pairs: list[str]) -> dict[str, str]:
    """Which traded currencies have no working official feed, and why."""
    legs = {leg for p in pairs for leg in (p[:3].upper(), p[3:6].upper())}
    return {c: why for c, why in UNAVAILABLE.items() if c in legs}
