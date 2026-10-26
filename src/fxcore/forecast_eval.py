"""Baselines and statistics for comparing price forecasts.

Used to judge whether a model earns any weight. The default answer is no, and
the burden of proof sits with the model.

Two design choices matter for honesty:

Forecast windows must not overlap. Overlapping windows make forecast errors
serially correlated, which inflates significance and manufactures a result from
nothing. `forecast_origins` enforces a stride of at least the horizon.

Random walk is the baseline that matters. On FX, "tomorrow's price is today's
price" is extremely hard to beat. A model that cannot beat it has shown nothing,
however good its charts look.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ForecastScore:
    """How one forecaster did over a set of non-overlapping windows."""

    name: str
    n: int
    mae_pips: float
    rmse_pips: float
    directional_accuracy: float  # fraction of correct up/down calls
    n_directional: int  # calls where the forecaster committed to a direction

    def __str__(self) -> str:
        return (
            f"{self.name:14} n={self.n:>5} MAE={self.mae_pips:>7.2f}p "
            f"RMSE={self.rmse_pips:>7.2f}p dir={self.directional_accuracy:>6.1%} "
            f"({self.n_directional} calls)"
        )


@dataclass(frozen=True)
class Comparison:
    """A model against one baseline, on paired absolute errors."""

    model: str
    baseline: str
    mae_difference_pips: float  # negative means the model is better
    t_statistic: float
    p_value: float
    n: int

    @property
    def model_is_better(self) -> bool:
        return self.mae_difference_pips < 0

    @property
    def significant(self) -> bool:
        return self.p_value < 0.05

    def verdict(self) -> str:
        if not self.model_is_better:
            return f"{self.model} is WORSE than {self.baseline}"
        if not self.significant:
            return f"{self.model} is better than {self.baseline} but NOT significant"
        return f"{self.model} beats {self.baseline} (p={self.p_value:.4f})"


def forecast_origins(n_bars: int, context: int, horizon: int, stride: int | None = None) -> list[int]:
    """Indices to forecast from, with non-overlapping outcome windows.

    `stride` defaults to the horizon so no two windows share a bar. Passing a
    smaller stride is refused: it would correlate the errors.
    """
    if stride is None:
        stride = horizon
    if stride < horizon:
        raise ValueError(
            f"stride {stride} is below horizon {horizon}; overlapping windows "
            "correlate forecast errors and inflate significance"
        )
    first = context
    last = n_bars - horizon
    return list(range(first, last + 1, stride)) if last >= first else []


# --- baselines --------------------------------------------------------------
# Each takes the context window of closes and returns the forecast close at
# `horizon` bars ahead.


def baseline_random_walk(context_closes: np.ndarray, horizon: int) -> float:
    """Tomorrow's price is today's price. The baseline that matters on FX."""
    return float(context_closes[-1])


def baseline_ar1(context_closes: np.ndarray, horizon: int) -> float:
    """AR(1) on log returns, extrapolated over the horizon.

    If the fit is degenerate, falls back to the random walk rather than
    inventing a number.
    """
    closes = np.asarray(context_closes, dtype=float)
    if len(closes) < 3 or np.any(closes <= 0):
        return float(closes[-1])
    returns = np.diff(np.log(closes))
    if len(returns) < 2:
        return float(closes[-1])

    x, y = returns[:-1], returns[1:]
    x_centred = x - x.mean()
    denominator = float(x_centred @ x_centred)
    if denominator <= 0:
        return float(closes[-1])

    phi = float((x_centred @ (y - y.mean())) / denominator)
    phi = max(-0.99, min(0.99, phi))  # keep it stationary
    intercept = float(y.mean() - phi * x.mean())

    # Iterate the AR(1) forward and accumulate the implied log return.
    r, total = float(returns[-1]), 0.0
    for _ in range(horizon):
        r = intercept + phi * r
        total += r
    return float(closes[-1] * math.exp(total))


def baseline_momentum(context_closes: np.ndarray, horizon: int, lookback: int = 24) -> float:
    """Recent average drift, carried forward over the horizon."""
    closes = np.asarray(context_closes, dtype=float)
    window = closes[-(lookback + 1) :]
    if len(window) < 2:
        return float(closes[-1])
    drift_per_bar = (window[-1] - window[0]) / (len(window) - 1)
    return float(closes[-1] + drift_per_bar * horizon)


BASELINES = {
    "random_walk": baseline_random_walk,
    "ar1": baseline_ar1,
    "momentum": baseline_momentum,
}


# --- scoring ----------------------------------------------------------------


def score(
    name: str,
    forecasts: np.ndarray,
    actuals: np.ndarray,
    anchors: np.ndarray,
    pip_size: float,
    direction_deadband_pips: float = 0.1,
) -> ForecastScore:
    """Score forecasts in pips.

    `anchors` is the last known close at each origin, needed to judge direction.
    A forecast within the deadband of the anchor is treated as no directional
    call rather than as a coin flip, so the random walk is not credited with
    predictions it never made.
    """
    forecasts = np.asarray(forecasts, dtype=float)
    actuals = np.asarray(actuals, dtype=float)
    anchors = np.asarray(anchors, dtype=float)
    if not (len(forecasts) == len(actuals) == len(anchors)):
        raise ValueError("forecasts, actuals and anchors must be the same length")
    if len(forecasts) == 0:
        raise ValueError("nothing to score")

    errors_pips = np.abs(forecasts - actuals) / pip_size

    predicted_move = (forecasts - anchors) / pip_size
    actual_move = (actuals - anchors) / pip_size
    committed = np.abs(predicted_move) > direction_deadband_pips
    n_directional = int(committed.sum())
    if n_directional:
        correct = np.sign(predicted_move[committed]) == np.sign(actual_move[committed])
        directional = float(correct.mean())
    else:
        directional = float("nan")

    return ForecastScore(
        name=name,
        n=len(forecasts),
        mae_pips=float(errors_pips.mean()),
        rmse_pips=float(np.sqrt((errors_pips**2).mean())),
        directional_accuracy=directional,
        n_directional=n_directional,
    )


def compare(
    model_name: str,
    model_forecasts: np.ndarray,
    baseline_name: str,
    baseline_forecasts: np.ndarray,
    actuals: np.ndarray,
    pip_size: float,
) -> Comparison:
    """Paired two-sided t-test on the difference in absolute error.

    Valid only on non-overlapping windows; `forecast_origins` enforces that.
    """
    model_errors = np.abs(np.asarray(model_forecasts, float) - actuals) / pip_size
    base_errors = np.abs(np.asarray(baseline_forecasts, float) - actuals) / pip_size
    differences = model_errors - base_errors

    n = len(differences)
    mean = float(differences.mean())
    sd = float(differences.std(ddof=1)) if n > 1 else 0.0

    if n < 2 or sd == 0:
        t_stat, p_value = 0.0, 1.0
    else:
        t_stat = mean / (sd / math.sqrt(n))
        p_value = _two_sided_p(t_stat, n - 1)

    return Comparison(
        model=model_name,
        baseline=baseline_name,
        mae_difference_pips=mean,
        t_statistic=t_stat,
        p_value=p_value,
        n=n,
    )


def directional_p_value(correct: int, total: int) -> float:
    """Two-sided binomial test of directional accuracy against a coin flip."""
    if total <= 0:
        return 1.0
    # Normal approximation with continuity correction; total is in the thousands.
    expected = total / 2
    sd = math.sqrt(total * 0.25)
    if sd == 0:
        return 1.0
    z = (abs(correct - expected) - 0.5) / sd
    return max(0.0, min(1.0, 2 * (1 - _standard_normal_cdf(z))))


def _standard_normal_cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _two_sided_p(t_stat: float, df: int) -> float:
    """Student-t two-sided p-value via the regularised incomplete beta function."""
    if df <= 0:
        return 1.0
    x = df / (df + t_stat * t_stat)
    return max(0.0, min(1.0, _betainc(df / 2, 0.5, x)))


def _betainc(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta I_x(a, b), by continued fraction."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    log_beta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(log_beta + a * math.log(x) + b * math.log(1 - x))
    if x < (a + 1) / (a + b + 2):
        return front * _beta_cf(a, b, x) / a
    return 1 - math.exp(
        log_beta + b * math.log(1 - x) + a * math.log(x)
    ) * _beta_cf(b, a, 1 - x) / b


def _beta_cf(a: float, b: float, x: float, iterations: int = 200) -> float:
    tiny = 1e-30
    c, d = 1.0, 1 - (a + b) * x / (a + 1)
    d = 1 / (tiny if abs(d) < tiny else d)
    result = d
    for m in range(1, iterations + 1):
        numerator = m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m))
        d = 1 + numerator * d
        c = 1 + numerator / (tiny if abs(c) < tiny else c)
        d = 1 / (tiny if abs(d) < tiny else d)
        result *= d * c

        numerator = -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1))
        d = 1 + numerator * d
        c = 1 + numerator / (tiny if abs(c) < tiny else c)
        d = 1 / (tiny if abs(d) < tiny else d)
        step = d * c
        result *= step
        if abs(step - 1) < 1e-12:
            break
    return result
