"""Gate tests built from the numbers measured on 2026-10-23.

Each test names the audit defect it pins down, so a regression points straight
at the real-world failure it would reintroduce.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fxcore.clock import ServerClock, is_fx_market_closed
from fxcore.contracts import (
    Bar,
    MarketSnapshot,
    MarketState,
    Provenance,
    Quote,
    SymbolSpec,
    TradeMode,
)
from fxcore.quality import (
    evaluate,
    gate_bar_resolution,
    gate_clock_resolved,
    gate_completeness,
    gate_freshness,
    gate_margin_known,
    gate_no_unexplained_gaps,
    gate_symbol_consistency,
    gate_symbol_tradable,
)

UTC = timezone.utc

# Measured on the live account, 2026-10-23.
TRUE_UTC = datetime(2026, 10, 23, 15, 57, 16, tzinfo=UTC)
SERVER_EPOCH = 1792781836  # reads as 18:57:16 if mistaken for UTC


def make_spec(**overrides) -> SymbolSpec:
    """EURUSDm#, the tradable micro symbol, as measured."""
    base = dict(
        analysis_symbol="EURUSD",
        broker_symbol="EURUSDm#",
        digits=5,
        point=1e-05,
        contract_size=1_000.0,
        volume_min=0.1,
        volume_max=100.0,
        volume_step=0.01,
        trade_mode=TradeMode.FULL,
        spread_points=10,
        spread_float=True,
        swap_long=-7.48,
        swap_short=1.23,
        currency_profit="USD",
        currency_margin="EUR",
        stops_level_points=0,
    )
    return SymbolSpec(**{**base, **overrides})


def make_bars(n: int, end: datetime, tf: int = 3600) -> tuple[Bar, ...]:
    return tuple(
        Bar(
            event_time_utc=end - timedelta(seconds=tf * (n - 1 - i)),
            timeframe_seconds=tf,
            open=1.1195,
            high=1.1205,
            low=1.1190,
            close=1.1200,
            tick_updates=4006,
        )
        for i in range(n)
    )


def make_snapshot(**overrides) -> MarketSnapshot:
    bars = overrides.pop("bars", make_bars(50, datetime(2026, 10, 23, 15, 0, tzinfo=UTC)))
    base = dict(
        spec=make_spec(),
        provenance=Provenance(
            source="mt5:XMGlobal-MT5 12",
            license="broker-account-data",
            retrieved_at_utc=TRUE_UTC,
            latency_ms=12,
            completeness=1.0,
            approved_for_decisions=True,
        ),
        market_state=MarketState.OPEN,
        bars=bars,
        quote=Quote(bid=1.11988, ask=1.11998, event_time_utc=TRUE_UTC),
        margin_required=112.0,
    )
    return MarketSnapshot(**{**base, **overrides})


# --- defect 1: server time is not UTC --------------------------------------


class TestClockOffset:
    def test_measures_the_plus_three_hour_offset(self):
        clock = ServerClock.measure(SERVER_EPOCH, TRUE_UTC)
        assert clock.offset_hours == pytest.approx(3.0)

    def test_converts_a_server_stamp_back_to_true_utc(self):
        clock = ServerClock.measure(SERVER_EPOCH, TRUE_UTC)
        assert clock.to_utc(SERVER_EPOCH) == TRUE_UTC

    def test_range_bounds_are_shifted_into_server_time(self):
        """Passing true UTC to copy_rates_range truncated 120 bars to 16."""
        clock = ServerClock.measure(SERVER_EPOCH, TRUE_UTC)
        assert clock.to_server_naive(TRUE_UTC) == datetime(2026, 10, 23, 18, 57, 16)

    def test_rejects_an_implausible_offset(self):
        with pytest.raises(ValueError, match="implausible"):
            ServerClock.measure(SERVER_EPOCH + 20 * 3600, TRUE_UTC)

    def test_unmeasured_clock_blocks_trading(self):
        assert not gate_clock_resolved(None, TRUE_UTC).passed

    def test_stale_offset_blocks_trading(self):
        clock = ServerClock.measure(SERVER_EPOCH, TRUE_UTC - timedelta(hours=2))
        assert not gate_clock_resolved(clock, TRUE_UTC).passed

    def test_naive_datetime_is_refused_at_the_contract_boundary(self):
        with pytest.raises(ValueError, match="must be timezone-aware UTC"):
            Bar(
                event_time_utc=datetime(2026, 10, 23, 18, 0),  # naive server time
                timeframe_seconds=3600,
                open=1.12,
                high=1.12,
                low=1.12,
                close=1.12,
                tick_updates=1,
            )


# --- defect 2: symbol mismatch ---------------------------------------------


class TestSymbolGates:
    def test_plain_eurusd_is_rejected_as_untradable(self):
        spec = make_spec(
            broker_symbol="EURUSD", trade_mode=TradeMode.DISABLED, contract_size=100_000.0
        )
        result = gate_symbol_tradable(spec)
        assert not result.passed
        assert "DISABLED" in result.detail

    def test_tradable_micro_symbol_passes(self):
        assert gate_symbol_tradable(make_spec()).passed

    def test_hundredfold_contract_size_mismatch_is_caught(self):
        analysis = make_spec(broker_symbol="EURUSD", contract_size=100_000.0)
        execution = make_spec()  # EURUSDm#, contract_size 1_000
        result = gate_symbol_consistency(analysis, execution)
        assert not result.passed
        assert "contract_size" in result.detail

    def test_matching_specs_pass(self):
        assert gate_symbol_consistency(make_spec(), make_spec()).passed

    def test_pip_size_is_ten_points_on_five_digit_quotes(self):
        assert make_spec().pip_size == pytest.approx(1e-04)

    def test_pip_size_is_ten_points_on_three_digit_jpy(self):
        spec = make_spec(broker_symbol="USDJPYm#", digits=3, point=0.001)
        assert spec.pip_size == pytest.approx(0.01)


# --- defect 3: stale data on first read ------------------------------------


class TestFreshness:
    def test_two_year_old_bar_is_rejected(self):
        """The first read returned 2024-08-21 H1 bars while ticks were live."""
        stale = make_bars(1, datetime(2024, 8, 21, 4, 0, tzinfo=UTC))[-1]
        result = gate_freshness(stale, TRUE_UTC)
        assert not result.passed
        assert "2024-08-21" in result.detail

    def test_current_bar_passes(self):
        fresh = make_bars(1, datetime(2026, 10, 23, 15, 0, tzinfo=UTC))[-1]
        assert gate_freshness(fresh, TRUE_UTC).passed

    def test_no_bars_blocks_trading(self):
        assert not gate_freshness(None, TRUE_UTC).passed

    def test_future_bar_is_rejected_as_clock_mismatch(self):
        """A server stamp mistaken for UTC lands 3h in the future."""
        future = make_bars(1, datetime(2026, 10, 23, 18, 0, tzinfo=UTC))[-1]
        result = gate_freshness(future, TRUE_UTC)
        assert not result.passed
        assert "future" in result.detail

    def test_weekend_staleness_is_tolerated(self):
        friday_close = datetime(2026, 10, 23, 20, 0, tzinfo=UTC)  # Friday
        saturday = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
        assert is_fx_market_closed(saturday)
        assert gate_freshness(make_bars(1, friday_close)[-1], saturday).passed


# --- defects 1 and 6: silent truncation and silent zero --------------------


class TestCompleteness:
    def test_sixteen_of_one_hundred_twenty_bars_is_rejected(self):
        """copy_rates_range with UTC bounds returned 16 bars for a 5-day window."""
        result = gate_completeness(n_actual=16, n_expected=120)
        assert not result.passed
        assert "13%" in result.detail

    def test_zero_bars_is_rejected(self):
        """Requesting 100_000 D1 bars returned 0 with no error."""
        result = gate_completeness(n_actual=0, n_expected=100_000)
        assert not result.passed
        assert "zero bars" in result.detail

    def test_full_series_passes(self):
        assert gate_completeness(n_actual=120, n_expected=120).passed

    def test_unknown_expectation_blocks_trading(self):
        assert not gate_completeness(n_actual=50, n_expected=0).passed


# --- defect 5: margin reads zero -------------------------------------------


class TestMargin:
    def test_zero_margin_is_rejected(self):
        """symbol_info.margin_initial reads 0.0; taken literally it means
        unlimited position size."""
        assert not gate_margin_known(0.0).passed

    def test_missing_margin_is_rejected(self):
        assert not gate_margin_known(None).passed

    def test_computed_margin_passes(self):
        assert gate_margin_known(112.0).passed


# --- gaps -------------------------------------------------------------------


class TestGaps:
    def test_contiguous_bars_pass(self):
        assert gate_no_unexplained_gaps(make_bars(24, TRUE_UTC)).passed

    def test_midweek_hole_is_rejected(self):
        bars = make_bars(10, datetime(2026, 10, 21, 12, 0, tzinfo=UTC))
        holed = bars[:4] + bars[7:]  # Wednesday, market open
        result = gate_no_unexplained_gaps(holed)
        assert not result.passed
        assert "missing" in result.detail

    def test_weekend_hole_is_explained(self):
        friday = Bar(
            event_time_utc=datetime(2026, 10, 23, 20, 0, tzinfo=UTC),
            timeframe_seconds=3600,
            open=1.12, high=1.12, low=1.12, close=1.12, tick_updates=100,
        )
        monday = Bar(
            event_time_utc=datetime(2026, 10, 26, 0, 0, tzinfo=UTC),
            timeframe_seconds=3600,
            open=1.12, high=1.12, low=1.12, close=1.12, tick_updates=100,
        )
        assert gate_no_unexplained_gaps((friday, monday)).passed

    def test_non_monotonic_bars_are_rejected(self):
        bars = make_bars(5, TRUE_UTC)
        assert not gate_no_unexplained_gaps((bars[2], bars[1])).passed


# --- fabricated low-resolution history -------------------------------------


class TestBarResolution:
    def test_flat_single_tick_bars_are_rejected(self):
        """USDJPYm# H4 back to 1971: o==h==l==c==357.73 with tick_updates==1,
        i.e. daily closes stuffed into H4 slots."""
        fake = tuple(
            Bar(
                event_time_utc=datetime(1971, 1, 3, tzinfo=UTC) + timedelta(days=i),
                timeframe_seconds=14400,
                open=357.73, high=357.73, low=357.73, close=357.73,
                tick_updates=1,
            )
            for i in range(20)
        )
        result = gate_bar_resolution(fake)
        assert not result.passed
        assert "flat single-tick" in result.detail

    def test_genuine_bars_pass(self):
        assert gate_bar_resolution(make_bars(100, TRUE_UTC)).passed

    def test_a_few_quiet_bars_are_tolerated(self):
        """A genuinely still bar at a holiday edge should not block trading."""
        real = list(make_bars(100, TRUE_UTC))
        real[0] = Bar(
            event_time_utc=real[0].event_time_utc,
            timeframe_seconds=3600,
            open=1.12, high=1.12, low=1.12, close=1.12,
            tick_updates=1,
        )
        assert gate_bar_resolution(tuple(real)).passed

    def test_empty_series_is_rejected(self):
        assert not gate_bar_resolution(()).passed


# --- DST weekend boundary ---------------------------------------------------


class TestWeekendBoundary:
    def test_summer_friday_close_is_covered(self):
        """Server runs UTC+3 in summer, so the week ends at 20:00 UTC. A 21:00
        boundary misclassified 530 of 12386 EURUSDm# H1 bars as missing."""
        assert is_fx_market_closed(datetime(2026, 10, 23, 20, 30, tzinfo=UTC))

    def test_winter_friday_close_is_covered(self):
        assert is_fx_market_closed(datetime(2026, 1, 9, 21, 30, tzinfo=UTC))

    def test_sunday_evening_before_open_is_closed(self):
        assert is_fx_market_closed(datetime(2026, 10, 25, 21, 30, tzinfo=UTC))

    def test_midweek_is_open(self):
        assert not is_fx_market_closed(datetime(2026, 10, 21, 12, 0, tzinfo=UTC))

    def test_friday_midday_is_open(self):
        assert not is_fx_market_closed(datetime(2026, 10, 23, 12, 0, tzinfo=UTC))


# --- defect 4: tick_updates is not volume ----------------------------------


class TestVolumeSemantics:
    def test_bar_exposes_tick_updates_not_volume(self):
        bar = make_bars(1, TRUE_UTC)[-1]
        assert bar.tick_updates == 4006
        assert not hasattr(bar, "volume")

    def test_broker_real_volume_stays_none_for_fx(self):
        """Measured 8-20 against thousands of ticks, with session_deals=0."""
        assert make_bars(1, TRUE_UTC)[-1].broker_real_volume is None


# --- anti-lookahead ---------------------------------------------------------


class TestLookahead:
    def test_a_bar_is_knowable_only_at_its_close(self):
        bar = Bar(
            event_time_utc=datetime(2026, 10, 23, 15, 0, tzinfo=UTC),
            timeframe_seconds=3600,
            open=1.12, high=1.13, low=1.11, close=1.125, tick_updates=10,
        )
        assert bar.info_available_at_utc == datetime(2026, 10, 23, 16, 0, tzinfo=UTC)

    def test_inconsistent_ohlc_is_refused(self):
        with pytest.raises(ValueError, match="inconsistent OHLC"):
            Bar(
                event_time_utc=TRUE_UTC,
                timeframe_seconds=3600,
                open=1.12, high=1.11, low=1.13, close=1.12, tick_updates=1,
            )

    def test_crossed_quote_is_refused(self):
        with pytest.raises(ValueError, match="crossed quote"):
            Quote(bid=1.12, ask=1.11, event_time_utc=TRUE_UTC)


# --- aggregate verdict ------------------------------------------------------


class TestEvaluate:
    def test_clean_snapshot_is_tradable(self):
        clock = ServerClock.measure(SERVER_EPOCH, TRUE_UTC)
        verdict = evaluate(make_snapshot(), clock, TRUE_UTC, expected_bars=50)
        assert verdict.tradable, verdict.reason

    def test_context_only_source_cannot_reach_a_decision(self):
        """TradingView and news are context; they must not drive a trade."""
        clock = ServerClock.measure(SERVER_EPOCH, TRUE_UTC)
        snapshot = make_snapshot(
            provenance=Provenance(
                source="tradingview:official",
                license="display-only",
                retrieved_at_utc=TRUE_UTC,
                latency_ms=None,
                completeness=1.0,
                approved_for_decisions=False,
            )
        )
        verdict = evaluate(snapshot, clock, TRUE_UTC, expected_bars=50)
        assert not verdict.tradable
        assert "context-only" in verdict.reason

    def test_a_single_failure_yields_no_trade(self):
        clock = ServerClock.measure(SERVER_EPOCH, TRUE_UTC)
        verdict = evaluate(make_snapshot(margin_required=None), clock, TRUE_UTC, expected_bars=50)
        assert not verdict.tradable
        assert "margin_known" in verdict.reason

    def test_unknown_market_state_yields_no_trade(self):
        clock = ServerClock.measure(SERVER_EPOCH, TRUE_UTC)
        verdict = evaluate(
            make_snapshot(market_state=MarketState.UNKNOWN), clock, TRUE_UTC, expected_bars=50
        )
        assert not verdict.tradable

    def test_verdict_reason_names_every_failure(self):
        verdict = evaluate(
            make_snapshot(margin_required=None, market_state=MarketState.UNKNOWN),
            clock=None,
            now_utc=TRUE_UTC,
            expected_bars=50,
        )
        assert not verdict.tradable
        for expected in ("clock_resolved", "margin_known", "market_state"):
            assert expected in verdict.reason

    def test_wide_spread_blocks_the_trade(self):
        clock = ServerClock.measure(SERVER_EPOCH, TRUE_UTC)
        snapshot = make_snapshot(
            quote=Quote(bid=1.1190, ask=1.1200, event_time_utc=TRUE_UTC)  # 10 pips
        )
        verdict = evaluate(snapshot, clock, TRUE_UTC, expected_bars=50, max_spread_pips=3.0)
        assert not verdict.tradable
        assert "spread" in verdict.reason

    def test_fingerprint_is_stable_and_sensitive(self):
        a, b = make_snapshot(), make_snapshot()
        assert a.fingerprint == b.fingerprint
        assert a.fingerprint != make_snapshot(margin_required=113.0).fingerprint
