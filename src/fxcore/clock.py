"""Broker server clock vs true UTC.

Audit defect 1, measured 2026-10-23: an MT5 tick epoch read as UTC gave
18:57:16 while true UTC was 15:57:16 — the broker stamps server time, +3h.
Passing true-UTC bounds into copy_rates_range truncated the window silently
(16 H1 bars over 5 days instead of ~120, newest 15:00 instead of 18:00).

The offset is measured at runtime, never hardcoded: brokers shift it on DST.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# Brokers set server time to whole or half hours; a fractional residue means we
# measured during a network stall, not a real offset.
_OFFSET_QUANTUM_SECONDS = 1800
_MAX_PLAUSIBLE_OFFSET_HOURS = 14


@dataclass(frozen=True)
class ServerClock:
    """A measured server-to-UTC offset, with the time it was measured."""

    offset: timedelta
    measured_at_utc: datetime
    raw_residue_seconds: float  # how far off the nearest half hour we landed

    @classmethod
    def measure(cls, server_epoch: int, true_utc: datetime) -> ServerClock:
        """Derive the offset from one live tick.

        `server_epoch` is the broker's epoch as returned by MT5, which encodes
        server wall-clock rather than real UTC. `true_utc` must come from the
        local clock, not from the broker.
        """
        if true_utc.tzinfo is None:
            raise ValueError("true_utc must be timezone-aware")
        true_utc = true_utc.astimezone(timezone.utc)

        server_as_if_utc = datetime.fromtimestamp(server_epoch, timezone.utc)
        raw = (server_as_if_utc - true_utc).total_seconds()

        snapped = round(raw / _OFFSET_QUANTUM_SECONDS) * _OFFSET_QUANTUM_SECONDS
        if abs(snapped) > _MAX_PLAUSIBLE_OFFSET_HOURS * 3600:
            raise ValueError(
                f"implausible server offset {snapped / 3600:.1f}h — refusing to guess"
            )
        return cls(
            offset=timedelta(seconds=snapped),
            measured_at_utc=true_utc,
            raw_residue_seconds=raw - snapped,
        )

    @property
    def offset_hours(self) -> float:
        return self.offset.total_seconds() / 3600

    def to_utc(self, server_epoch: int) -> datetime:
        """Convert a broker timestamp into true UTC."""
        return datetime.fromtimestamp(server_epoch, timezone.utc) - self.offset

    def to_server_naive(self, utc: datetime) -> datetime:
        """Build the naive server-time datetime that MT5 range calls expect.

        MT5 interprets datetimes handed to copy_rates_range as server time. Pass
        a UTC datetime directly and the window silently shifts by the offset.
        """
        if utc.tzinfo is None:
            raise ValueError("utc must be timezone-aware")
        return (utc.astimezone(timezone.utc) + self.offset).replace(tzinfo=None)

    def age(self, now_utc: datetime) -> timedelta:
        return now_utc.astimezone(timezone.utc) - self.measured_at_utc


# The broker's week boundary moves with DST: its server runs UTC+2 in winter and
# UTC+3 in summer, so the Friday close lands at 21:00 or 20:00 UTC depending on
# the season. Measured on EURUSDm# H1 over two years, a hardcoded 21:00 boundary
# misclassified 530 of 12386 bars (4.3%) as missing across DST weekends. The
# window below spans both cases: it tolerates up to an hour of genuinely absent
# data at each week edge rather than raise hundreds of false alarms.
_FRIDAY_CLOSE_HOUR_UTC = 20
_SUNDAY_OPEN_HOUR_UTC = 22


def is_fx_market_closed(when_utc: datetime) -> bool:
    """Conservative FX weekend closure in UTC.

    Deliberately approximate and broker-specific: the real schedule is the
    broker's, varies by symbol, and shifts with DST. Used only to decide whether
    a bar gap needs explaining — never to authorise a trade.
    """
    when_utc = when_utc.astimezone(timezone.utc)
    weekday, hour = when_utc.weekday(), when_utc.hour  # Mon=0, Sun=6
    if weekday == 5:  # Saturday
        return True
    if weekday == 4 and hour >= _FRIDAY_CLOSE_HOUR_UTC:
        return True
    if weekday == 6 and hour < _SUNDAY_OPEN_HOUR_UTC:
        return True
    return False
