"""Data quality gates. Default verdict is NO_TRADE.

Each gate below exists because the probe on 2026-10-23 produced the failure it
catches. Gates are pure functions so they are testable without a broker.

Reference: docs/audit/2026-10-23-state-and-sources.md section 3
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .clock import ServerClock, is_fx_market_closed
from .contracts import Bar, MarketSnapshot, MarketState, SymbolSpec


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class Verdict:
    """The decision. `NO_TRADE` is the default and needs no justification."""

    tradable: bool
    results: tuple[GateResult, ...]

    @property
    def failures(self) -> tuple[GateResult, ...]:
        return tuple(r for r in self.results if not r.passed)

    @property
    def reason(self) -> str:
        if self.tradable:
            return "all gates passed"
        return "NO_TRADE: " + "; ".join(f"{r.name}: {r.detail}" for r in self.failures)


# --- individual gates -------------------------------------------------------


def gate_clock_resolved(
    clock: ServerClock | None,
    now_utc: datetime,
    max_age: timedelta = timedelta(minutes=15),
    max_residue_seconds: float = 90.0,
) -> GateResult:
    """Defect 1: no trading while the server/UTC offset is unknown or stale."""
    name = "clock_resolved"
    if clock is None:
        return GateResult(name, False, "server/UTC offset never measured")
    age = clock.age(now_utc)
    if age > max_age:
        return GateResult(name, False, f"offset measured {age} ago, limit {max_age}")
    if abs(clock.raw_residue_seconds) > max_residue_seconds:
        return GateResult(
            name,
            False,
            f"offset residue {clock.raw_residue_seconds:.1f}s exceeds "
            f"{max_residue_seconds}s — clock drift unresolved",
        )
    return GateResult(name, True, f"offset {clock.offset_hours:+.1f}h, age {age}")


def gate_freshness(
    last_bar: Bar | None,
    now_utc: datetime,
    max_staleness_multiple: float = 2.5,
) -> GateResult:
    """Defect 3: the first read returned 2024-08-21 bars while ticks were live."""
    name = "freshness"
    if last_bar is None:
        return GateResult(name, False, "no bars returned")

    age = (now_utc - last_bar.info_available_at_utc).total_seconds()
    limit = last_bar.timeframe_seconds * max_staleness_multiple

    if age < -last_bar.timeframe_seconds:
        return GateResult(
            name, False, f"last bar closes {-age:.0f}s in the future — clock mismatch"
        )
    if age > limit and not is_fx_market_closed(now_utc):
        return GateResult(
            name,
            False,
            f"last bar {age / 3600:.1f}h old, limit {limit / 3600:.1f}h "
            f"(bar {last_bar.event_time_utc.isoformat()})",
        )
    return GateResult(name, True, f"last bar {age / 60:.1f}min old")


def gate_symbol_tradable(spec: SymbolSpec) -> GateResult:
    """Defect 2: plain EURUSD reports trade_mode DISABLED on this account."""
    name = "symbol_tradable"
    if not spec.is_tradable:
        return GateResult(
            name,
            False,
            f"{spec.broker_symbol} trade_mode={spec.trade_mode.name}, not FULL",
        )
    return GateResult(name, True, f"{spec.broker_symbol} tradable")


def gate_symbol_consistency(
    analysis_spec: SymbolSpec, execution_spec: SymbolSpec
) -> GateResult:
    """Defect 2: EURUSD contract_size 100_000 vs EURUSDm# 1_000 — a 100x error.

    If analysis and execution resolve to different specs, sizing is meaningless.
    """
    name = "symbol_consistency"
    mismatches = []
    if analysis_spec.broker_symbol != execution_spec.broker_symbol:
        mismatches.append(
            f"broker_symbol {analysis_spec.broker_symbol} != {execution_spec.broker_symbol}"
        )
    if analysis_spec.contract_size != execution_spec.contract_size:
        mismatches.append(
            f"contract_size {analysis_spec.contract_size} != {execution_spec.contract_size}"
        )
    if analysis_spec.digits != execution_spec.digits:
        mismatches.append(f"digits {analysis_spec.digits} != {execution_spec.digits}")
    if mismatches:
        return GateResult(name, False, "; ".join(mismatches))
    return GateResult(name, True, "analysis and execution specs agree")


def gate_completeness(
    n_actual: int, n_expected: int, min_ratio: float = 0.95
) -> GateResult:
    """Defects 1 and 6: silent truncation (16 bars for 120) and silent zero.

    copy_rates_range with UTC bounds returned 16 of ~120 bars with no error;
    requesting 100_000 D1 bars returned 0 with no error. Both pass a naive
    `if rates is not None` check.
    """
    name = "completeness"
    if n_expected <= 0:
        return GateResult(name, False, "expected bar count unknown")
    if n_actual == 0:
        return GateResult(name, False, f"zero bars returned, expected ~{n_expected}")
    ratio = n_actual / n_expected
    if ratio < min_ratio:
        return GateResult(
            name,
            False,
            f"{n_actual}/{n_expected} bars ({ratio:.0%}), minimum {min_ratio:.0%}",
        )
    return GateResult(name, True, f"{n_actual}/{n_expected} bars ({ratio:.0%})")


def gate_no_unexplained_gaps(bars: tuple[Bar, ...]) -> GateResult:
    """Gaps not covered by the weekend close must stop the analysis."""
    name = "no_unexplained_gaps"
    if len(bars) < 2:
        return GateResult(name, True, "too few bars to assess")

    tf = bars[0].timeframe_seconds
    if any(b.timeframe_seconds != tf for b in bars):
        return GateResult(name, False, "mixed timeframes in one series")

    unexplained = []
    for prev, cur in zip(bars, bars[1:]):
        delta = (cur.event_time_utc - prev.event_time_utc).total_seconds()
        if delta <= 0:
            return GateResult(
                name, False, f"non-monotonic bars at {cur.event_time_utc.isoformat()}"
            )
        missing = round(delta / tf) - 1
        if missing > 0 and not is_fx_market_closed(prev.info_available_at_utc):
            unexplained.append(
                f"{missing} bar(s) missing after {prev.event_time_utc.isoformat()}"
            )
    if unexplained:
        shown = "; ".join(unexplained[:3])
        more = f" (+{len(unexplained) - 3} more)" if len(unexplained) > 3 else ""
        return GateResult(name, False, shown + more)
    return GateResult(name, True, f"{len(bars)} bars contiguous or weekend-explained")


def gate_margin_known(margin_required: float | None) -> GateResult:
    """Defect 5: symbol_info.margin_initial reads 0.0, which is not the margin.

    Margin must come from order_calc_margin. A zero or missing value would imply
    unlimited position size.
    """
    name = "margin_known"
    if margin_required is None:
        return GateResult(name, False, "margin not computed via order_calc_margin")
    if margin_required <= 0:
        return GateResult(name, False, f"margin {margin_required} is not positive")
    return GateResult(name, True, f"margin {margin_required:.2f}")


def gate_source_approved(snapshot: MarketSnapshot) -> GateResult:
    """Context-only sources (TradingView, news) must never reach a decision."""
    name = "source_approved"
    p = snapshot.provenance
    if not p.approved_for_decisions:
        return GateResult(
            name, False, f"source {p.source!r} is context-only, not decision-grade"
        )
    return GateResult(name, True, f"source {p.source!r} approved ({p.license})")


def gate_quote_executable(
    quote: object | None, spec: SymbolSpec, max_spread_pips: float
) -> GateResult:
    """A decision needs a two-sided price and a spread within budget."""
    name = "quote_executable"
    if quote is None:
        return GateResult(name, False, "no bid/ask quote available")
    spread_pips = (quote.ask - quote.bid) / spec.pip_size  # type: ignore[attr-defined]
    if spread_pips > max_spread_pips:
        return GateResult(
            name,
            False,
            f"spread {spread_pips:.1f} pips exceeds budget {max_spread_pips:.1f}",
        )
    return GateResult(name, True, f"spread {spread_pips:.1f} pips")


# --- aggregation ------------------------------------------------------------


def evaluate(
    snapshot: MarketSnapshot,
    clock: ServerClock | None,
    now_utc: datetime,
    execution_spec: SymbolSpec | None = None,
    expected_bars: int | None = None,
    max_spread_pips: float = 3.0,
) -> Verdict:
    """Run every gate. Any failure yields NO_TRADE.

    `execution_spec` defaults to the snapshot's own spec; pass it explicitly when
    analysis and execution resolve symbols separately.
    """
    spec = snapshot.spec
    results = [
        gate_source_approved(snapshot),
        gate_clock_resolved(clock, now_utc),
        gate_freshness(snapshot.last_bar, now_utc),
        gate_symbol_tradable(spec),
        gate_symbol_consistency(spec, execution_spec or spec),
        gate_completeness(len(snapshot.bars), expected_bars or len(snapshot.bars) or -1),
        gate_no_unexplained_gaps(snapshot.bars),
        gate_margin_known(snapshot.margin_required),
        gate_quote_executable(snapshot.quote, spec, max_spread_pips),
    ]
    if snapshot.market_state is MarketState.UNKNOWN:
        results.append(GateResult("market_state", False, "market state unknown"))

    return Verdict(tradable=all(r.passed for r in results), results=tuple(results))
