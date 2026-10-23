"""Analysis tests: the read must be honest about agreement, conflict and limits."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fxcore.analysis import MAX_CONFIDENCE, Bias, analyse, atr, ema, read_timeframe
from fxcore.contracts import Bar

from test_quality import make_spec  # reuse the measured EURUSDm# spec

UTC = timezone.utc
START = datetime(2026, 1, 1, tzinfo=UTC)


def ramp(n: int, start: float, step: float, tf: int = 3600) -> tuple[Bar, ...]:
    """A clean trend: `step` per bar, with a small but real intrabar range."""
    bars = []
    for i in range(n):
        open_ = start + step * i
        close = open_ + step * 0.5
        bars.append(
            Bar(
                event_time_utc=START + timedelta(seconds=tf * i),
                timeframe_seconds=tf,
                open=open_,
                high=max(open_, close) + 0.0004,
                low=min(open_, close) - 0.0004,
                close=close,
                tick_updates=500,
            )
        )
    return tuple(bars)


class TestIndicators:
    def test_ema_of_a_constant_series_is_that_constant(self):
        assert ema([1.5] * 50, 20) == pytest.approx(1.5)

    def test_ema_tracks_a_rising_series(self):
        assert ema(list(range(50)), 20) > 30

    def test_ema_rejects_an_empty_series(self):
        with pytest.raises(ValueError):
            ema([], 20)

    def test_atr_is_positive_for_moving_bars(self):
        assert atr(ramp(30, 1.10, 0.0010)) > 0

    def test_atr_includes_the_gap_between_bars(self):
        gapped = ramp(5, 1.10, 0.0100)  # large steps between bars
        tight = ramp(5, 1.10, 0.0001)
        assert atr(gapped) > atr(tight)


class TestTimeframeRead:
    def test_a_rising_series_reads_up(self):
        read = read_timeframe("H1", ramp(100, 1.10, 0.0010), make_spec())
        assert read.bias is Bias.UP
        assert read.slope_pips_per_bar > 0

    def test_a_falling_series_reads_down(self):
        read = read_timeframe("H1", ramp(100, 1.20, -0.0010), make_spec())
        assert read.bias is Bias.DOWN
        assert read.slope_pips_per_bar < 0

    def test_a_flat_series_reads_flat(self):
        read = read_timeframe("H1", ramp(100, 1.10, 0.0), make_spec())
        assert read.bias is Bias.FLAT

    def test_tiny_drift_is_treated_as_noise_not_trend(self):
        """Slope below the floor must not become a bias."""
        read = read_timeframe("H1", ramp(100, 1.10, 0.0000005), make_spec())
        assert read.bias is Bias.FLAT

    def test_every_read_carries_its_evidence(self):
        read = read_timeframe("H1", ramp(100, 1.10, 0.0010), make_spec())
        assert len(read.evidence) >= 5
        assert any("EMA20" in e for e in read.evidence)

    def test_range_position_is_high_in_an_uptrend(self):
        read = read_timeframe("H1", ramp(100, 1.10, 0.0010), make_spec())
        assert read.range_position > 0.8

    def test_structure_is_named_for_a_clean_uptrend(self):
        read = read_timeframe("H1", ramp(100, 1.10, 0.0010), make_spec())
        assert read.structure == "higher highs and higher lows"

    def test_too_few_bars_is_refused(self):
        with pytest.raises(ValueError, match="need >=50 bars"):
            read_timeframe("H1", ramp(10, 1.10, 0.0010), make_spec())


class TestBlend:
    def test_full_agreement_gives_the_capped_confidence(self):
        bars = {tf: ramp(100, 1.10, 0.0010) for tf in ("M15", "H1", "H4", "D1")}
        a = analyse("EURUSD", "EURUSDm#", bars, make_spec())
        assert a.bias is Bias.UP
        assert a.confidence == pytest.approx(MAX_CONFIDENCE)
        assert not a.conflicts

    def test_confidence_never_exceeds_the_cap(self):
        bars = {tf: ramp(200, 1.10, 0.0020) for tf in ("M15", "H1", "H4", "D1")}
        a = analyse("EURUSD", "EURUSDm#", bars, make_spec())
        assert a.confidence <= MAX_CONFIDENCE

    def test_conflict_is_reported_and_costs_confidence(self):
        bars = {
            "M15": ramp(100, 1.10, 0.0010),  # up
            "H1": ramp(100, 1.10, 0.0010),  # up
            "H4": ramp(100, 1.20, -0.0010),  # down
            "D1": ramp(100, 1.20, -0.0010),  # down
        }
        a = analyse("EURUSD", "EURUSDm#", bars, make_spec())
        assert a.conflicts
        assert a.confidence < MAX_CONFIDENCE

    def test_a_tie_resolves_to_flat_not_to_a_side(self):
        """Equal weight up and down must not pick the convenient direction.

        up = D1 2.0 + M15 0.5 = 2.5;  down = H4 1.5 + H1 1.0 = 2.5
        """
        bars = {
            "D1": ramp(100, 1.10, 0.0010),  # up, weight 2.0
            "M15": ramp(100, 1.10, 0.0010),  # up, weight 0.5
            "H4": ramp(100, 1.20, -0.0010),  # down, weight 1.5
            "H1": ramp(100, 1.20, -0.0010),  # down, weight 1.0
        }
        a = analyse("EURUSD", "EURUSDm#", bars, make_spec())
        assert a.bias is Bias.FLAT
        assert a.conflicts

    def test_higher_timeframe_without_trend_is_flagged(self):
        bars = {
            "H1": ramp(100, 1.10, 0.0010),
            "H4": ramp(100, 1.10, 0.0),  # flat, high weight
        }
        a = analyse("EURUSD", "EURUSDm#", bars, make_spec())
        assert any("higher timeframe" in c for c in a.conflicts)

    def test_limits_are_always_stated(self):
        bars = {"H1": ramp(100, 1.10, 0.0010)}
        a = analyse("EURUSD", "EURUSDm#", bars, make_spec())
        assert any("not a forecast" in limit for limit in a.limits)
        assert any("sizing" in limit for limit in a.limits)
        assert any("spread" in limit for limit in a.limits)

    def test_short_timeframes_are_dropped_and_declared(self):
        bars = {"H1": ramp(100, 1.10, 0.0010), "D1": ramp(10, 1.10, 0.0010)}
        a = analyse("EURUSD", "EURUSDm#", bars, make_spec())
        assert {r.timeframe for r in a.reads} == {"H1"}
        assert any("dropped" in limit for limit in a.limits)

    def test_no_usable_timeframe_is_refused(self):
        with pytest.raises(ValueError, match="no timeframe"):
            analyse("EURUSD", "EURUSDm#", {"H1": ramp(10, 1.10, 0.001)}, make_spec())

    def test_analysis_never_implies_a_position_size(self):
        bars = {"H1": ramp(100, 1.10, 0.0010)}
        a = analyse("EURUSD", "EURUSDm#", bars, make_spec())
        assert not hasattr(a, "size")
        assert not hasattr(a, "lots")
        assert not hasattr(a, "entry")
