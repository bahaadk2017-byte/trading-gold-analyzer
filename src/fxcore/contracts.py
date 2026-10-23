"""Unified data contract for FX pairs.

Every value that can reach a trading decision carries its provenance. The field
names here are deliberate: see `Bar.tick_updates`, which is NOT volume.

Reference: docs/audit/2026-10-23-state-and-sources.md
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum

CONTRACT_VERSION = "0.1.0"


class TradeMode(Enum):
    """MT5 SYMBOL_TRADE_MODE_*. Audit defect 2: plain `EURUSD` is DISABLED."""

    DISABLED = 0
    LONG_ONLY = 1
    SHORT_ONLY = 2
    CLOSE_ONLY = 3
    FULL = 4


class MarketState(Enum):
    OPEN = "open"
    CLOSED = "closed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Provenance:
    """Where a number came from, and whether we may act on it."""

    source: str  # e.g. "mt5:XMGlobal-MT5 12"
    license: str  # right-to-use, e.g. "broker-account-data"
    retrieved_at_utc: datetime
    latency_ms: int | None  # None = unmeasured, NOT zero
    completeness: float  # actual/expected bars, 0.0-1.0
    approved_for_decisions: bool
    contract_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_utc(self.retrieved_at_utc, "retrieved_at_utc")
        if not 0.0 <= self.completeness <= 1.0:
            raise ValueError(f"completeness out of range: {self.completeness}")


@dataclass(frozen=True)
class SymbolSpec:
    """Execution-side truth for one instrument.

    Audit defect 2: `EURUSD` (contract_size 100_000, DISABLED) and `EURUSDm#`
    (contract_size 1_000, FULL) quote near-identically. Sizing against the wrong
    one is a 100x risk error, so analysis and broker symbols are separate fields
    and `gate_symbol_consistency` refuses to let them diverge silently.
    """

    analysis_symbol: str  # what humans/agents reason about, e.g. "EURUSD"
    broker_symbol: str  # what orders would name, e.g. "EURUSDm#"
    digits: int
    point: float
    contract_size: float
    volume_min: float
    volume_max: float
    volume_step: float
    trade_mode: TradeMode
    spread_points: int
    spread_float: bool
    swap_long: float
    swap_short: float
    currency_profit: str
    currency_margin: str
    stops_level_points: int

    @property
    def pip_size(self) -> float:
        """A pip is 10 points on fractional-pip quotes (5-digit FX, 3-digit JPY)."""
        return self.point * 10 if self.digits in (3, 5) else self.point

    @property
    def spread_pips(self) -> float:
        return self.spread_points * self.point / self.pip_size

    @property
    def is_tradable(self) -> bool:
        return self.trade_mode is TradeMode.FULL

    def price_to_pips(self, price_delta: float) -> float:
        return price_delta / self.pip_size


@dataclass(frozen=True)
class Bar:
    """One OHLC bar, in true UTC.

    `tick_updates` is the broker's count of price updates (MT5 `tick_volume`).
    Audit defect 4 measured tick_updates~4006 against real_volume=8 and
    session_deals=0 on EURUSDm#: FX has no central volume. This is NOT volume
    and NOT order flow. `broker_real_volume` stays None for FX by policy.
    """

    event_time_utc: datetime  # bar OPEN time
    timeframe_seconds: int
    open: float
    high: float
    low: float
    close: float
    tick_updates: int
    broker_real_volume: None = None

    def __post_init__(self) -> None:
        _require_utc(self.event_time_utc, "event_time_utc")
        if self.timeframe_seconds <= 0:
            raise ValueError("timeframe_seconds must be positive")
        if not (self.low <= self.open <= self.high and self.low <= self.close <= self.high):
            raise ValueError(
                f"inconsistent OHLC at {self.event_time_utc}: "
                f"o={self.open} h={self.high} l={self.low} c={self.close}"
            )

    @property
    def info_available_at_utc(self) -> datetime:
        """When this bar became knowable: at its close, never at its open.

        This is the anti-lookahead field. A decision stamped at time T may only
        read bars whose info_available_at_utc <= T.
        """
        from datetime import timedelta

        return self.event_time_utc + timedelta(seconds=self.timeframe_seconds)


@dataclass(frozen=True)
class Quote:
    """Executable two-sided price. Mid prices are not executable."""

    bid: float
    ask: float
    event_time_utc: datetime

    def __post_init__(self) -> None:
        _require_utc(self.event_time_utc, "event_time_utc")
        if self.ask < self.bid:
            raise ValueError(f"crossed quote: bid={self.bid} ask={self.ask}")

    @property
    def spread_price(self) -> float:
        return self.ask - self.bid

    @property
    def info_available_at_utc(self) -> datetime:
        return self.event_time_utc


@dataclass(frozen=True)
class MarketSnapshot:
    """What one source returned for one symbol at one moment, with its origin."""

    spec: SymbolSpec
    provenance: Provenance
    market_state: MarketState
    bars: tuple[Bar, ...] = ()
    quote: Quote | None = None
    margin_required: float | None = None  # from order_calc_margin, never a read field
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def fingerprint(self) -> str:
        """Stable SHA-256 over the payload, for the immutable audit log."""
        return _fingerprint(
            {
                "spec": _jsonable(self.spec),
                "provenance": _jsonable(self.provenance),
                "market_state": self.market_state.value,
                "bars": [_jsonable(b) for b in self.bars],
                "quote": _jsonable(self.quote) if self.quote else None,
                "margin_required": self.margin_required,
            }
        )

    @property
    def last_bar(self) -> Bar | None:
        return self.bars[-1] if self.bars else None


def _require_utc(value: datetime, name: str) -> None:
    """Audit defect 1: MT5 returns server time (measured UTC+3). Naive datetimes
    are rejected outright so an unconverted server stamp cannot enter the system.
    """
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware UTC, got naive: {value!r}")
    if value.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError(f"{name} must be UTC, got offset {value.utcoffset()}")


def _jsonable(obj: object) -> object:
    def convert(v: object) -> object:
        if isinstance(v, datetime):
            return v.isoformat()
        if isinstance(v, Enum):
            return v.value
        if isinstance(v, dict):
            return {k: convert(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [convert(x) for x in v]
        return v

    return convert(asdict(obj))  # type: ignore[call-overload]


def _fingerprint(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
