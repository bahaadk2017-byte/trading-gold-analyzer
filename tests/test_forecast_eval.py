"""Tests for the forecast comparison harness.

The harness decides whether a model earns weight, so its own correctness matters
more than the model's. Statistics are checked against known closed forms.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fxcore.forecast_eval import (
    BASELINES,
    baseline_ar1,
    baseline_momentum,
    baseline_random_walk,
    compare,
    directional_p_value,
    forecast_origins,
    score,
    _two_sided_p,
)

PIP = 1e-04


class TestOrigins:
    def test_windows_do_not_overlap_by_default(self):
        origins = forecast_origins(n_bars=1000, context=512, horizon=12)
        gaps = np.diff(origins)
        assert all(g >= 12 for g in gaps)

    def test_first_origin_leaves_room_for_context(self):
        assert forecast_origins(1000, 512, 12)[0] == 512

    def test_last_origin_leaves_room_for_the_outcome(self):
        origins = forecast_origins(1000, 512, 12)
        assert origins[-1] + 12 <= 1000

    def test_exactly_one_window_is_kept(self):
        assert forecast_origins(524, 512, 12) == [512]

    def test_overlapping_stride_is_refused(self):
        """Overlapping windows correlate errors and manufacture significance."""
        with pytest.raises(ValueError, match="overlapping windows"):
            forecast_origins(1000, 512, 12, stride=6)

    def test_too_little_data_yields_no_origins(self):
        assert forecast_origins(n_bars=520, context=512, horizon=12) == []


class TestBaselines:
    def test_random_walk_returns_the_last_close(self):
        closes = np.array([1.10, 1.11, 1.12])
        assert baseline_random_walk(closes, 12) == 1.12

    def test_momentum_extrapolates_a_steady_climb(self):
        closes = np.linspace(1.10, 1.20, 101)  # +0.001 per bar
        forecast = baseline_momentum(closes, horizon=10, lookback=24)
        assert forecast == pytest.approx(1.20 + 0.001 * 10, rel=1e-3)

    def test_momentum_on_a_flat_series_returns_the_last_close(self):
        closes = np.full(100, 1.15)
        assert baseline_momentum(closes, 10) == pytest.approx(1.15)

    def test_ar1_on_a_flat_series_returns_the_last_close(self):
        closes = np.full(100, 1.15)
        assert baseline_ar1(closes, 10) == pytest.approx(1.15, rel=1e-6)

    def test_ar1_falls_back_rather_than_inventing_a_number(self):
        assert baseline_ar1(np.array([1.10, 1.11]), 10) == 1.11

    def test_ar1_refuses_non_positive_prices(self):
        closes = np.array([1.0, 0.0, -1.0, 1.0])
        assert baseline_ar1(closes, 5) == 1.0

    def test_ar1_stays_finite_on_a_strong_trend(self):
        closes = np.linspace(1.10, 1.40, 200)
        assert np.isfinite(baseline_ar1(closes, 12))

    def test_all_baselines_are_registered(self):
        assert set(BASELINES) == {"random_walk", "ar1", "momentum"}


class TestScoring:
    def test_perfect_forecast_scores_zero_error(self):
        actuals = np.array([1.1050, 1.1100, 1.0950])
        anchors = np.array([1.1000, 1.1000, 1.1000])
        result = score("perfect", actuals, actuals, anchors, PIP)
        assert result.mae_pips == pytest.approx(0.0)
        assert result.directional_accuracy == pytest.approx(1.0)

    def test_mae_is_reported_in_pips(self):
        actuals = np.array([1.1010])
        forecasts = np.array([1.1000])  # 10 pips out
        result = score("m", forecasts, actuals, np.array([1.1000]), PIP)
        assert result.mae_pips == pytest.approx(10.0)

    def test_always_wrong_direction_scores_zero(self):
        anchors = np.array([1.1000, 1.1000])
        forecasts = np.array([1.1050, 1.0950])  # up, down
        actuals = np.array([1.0950, 1.1050])  # down, up
        result = score("inverted", forecasts, actuals, anchors, PIP)
        assert result.directional_accuracy == pytest.approx(0.0)

    def test_random_walk_is_not_credited_with_directional_calls(self):
        """A flat forecast makes no directional call; it must not score 50%."""
        anchors = np.array([1.1000, 1.1000, 1.1000])
        forecasts = anchors.copy()
        actuals = np.array([1.1050, 1.0950, 1.1010])
        result = score("random_walk", forecasts, actuals, anchors, PIP)
        assert result.n_directional == 0
        assert np.isnan(result.directional_accuracy)

    def test_mismatched_lengths_are_refused(self):
        with pytest.raises(ValueError, match="same length"):
            score("m", np.array([1.0]), np.array([1.0, 2.0]), np.array([1.0]), PIP)

    def test_empty_input_is_refused(self):
        with pytest.raises(ValueError, match="nothing to score"):
            score("m", np.array([]), np.array([]), np.array([]), PIP)


class TestComparison:
    def test_a_clearly_better_model_is_detected(self):
        rng = np.random.default_rng(7)
        actuals = 1.10 + rng.normal(0, 0.0010, 400)
        good = actuals + rng.normal(0, 0.0002, 400)
        poor = actuals + rng.normal(0, 0.0020, 400)
        result = compare("good", good, "poor", poor, actuals, PIP)
        assert result.model_is_better
        assert result.significant
        assert "beats" in result.verdict()

    def test_a_worse_model_is_called_worse(self):
        rng = np.random.default_rng(11)
        actuals = 1.10 + rng.normal(0, 0.0010, 400)
        good = actuals + rng.normal(0, 0.0002, 400)
        poor = actuals + rng.normal(0, 0.0020, 400)
        result = compare("poor", poor, "good", good, actuals, PIP)
        assert not result.model_is_better
        assert "WORSE" in result.verdict()

    def test_identical_forecasters_are_not_significant(self):
        rng = np.random.default_rng(3)
        actuals = 1.10 + rng.normal(0, 0.001, 300)
        same = actuals + rng.normal(0, 0.0005, 300)
        result = compare("a", same, "b", same.copy(), actuals, PIP)
        assert not result.significant
        assert result.p_value == pytest.approx(1.0)

    def test_a_marginal_edge_is_not_called_significant(self):
        rng = np.random.default_rng(5)
        actuals = 1.10 + rng.normal(0, 0.0010, 60)
        a = actuals + rng.normal(0, 0.00100, 60)
        b = actuals + rng.normal(0, 0.00102, 60)
        result = compare("a", a, "b", b, actuals, PIP)
        assert not result.significant, "a tiny edge on 60 windows must not pass"


class TestStatistics:
    def test_t_distribution_matches_known_values(self):
        # Two-sided p for |t|=2.0 at df=10 is about 0.0734
        assert _two_sided_p(2.0, 10) == pytest.approx(0.0734, abs=5e-4)
        # |t|=1.96 at large df approaches 0.05
        assert _two_sided_p(1.96, 10_000) == pytest.approx(0.05, abs=2e-3)

    def test_zero_t_statistic_gives_p_of_one(self):
        assert _two_sided_p(0.0, 50) == pytest.approx(1.0)

    def test_coin_flip_directional_accuracy_is_not_significant(self):
        assert directional_p_value(correct=500, total=1000) > 0.05

    def test_a_strong_directional_edge_is_significant(self):
        assert directional_p_value(correct=600, total=1000) < 0.001

    def test_empty_sample_is_not_significant(self):
        assert directional_p_value(0, 0) == 1.0
