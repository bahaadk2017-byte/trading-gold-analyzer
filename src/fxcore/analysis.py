"""Multi-timeframe reading of validated bars.

This is a transparent rule-based read, not a predictive model. Every conclusion
carries the evidence that produced it, a confidence number, and the limits on
that number. Confidence is capped well below 1.0 on purpose: agreement between
moving averages is weak evidence about the future, and the output must not imply
otherwise.

Bias is never a trade instruction. It is one input the risk guardian may reject.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .contracts import Bar, SymbolSpec

# Higher timeframes carry more weight in the blend, but none dominates outright.
TIMEFRAME_WEIGHTS = {"M15": 0.5, "H1": 1.0, "H4": 1.5, "D1": 2.0}

# A slope below this is noise, not a trend.
MIN_SLOPE_PIPS_PER_BAR = 0.05

# Confidence ceiling. Trend agreement across timeframes is suggestive, never
# decisive, so the system may not report more than this.
MAX_CONFIDENCE = 0.70


class Bias(Enum):
    UP = "up"
    DOWN = "down"
    FLAT = "flat"


@dataclass(frozen=True)
class TimeframeRead:
    timeframe: str
    bias: Bias
    ema_fast: float
    ema_slow: float
    slope_pips_per_bar: float
    atr_pips: float
    range_position: float  # 0.0 at the 50-bar low, 1.0 at the high
    structure: str
    evidence: tuple[str, ...]

    @property
    def weight(self) -> float:
        return TIMEFRAME_WEIGHTS.get(self.timeframe, 1.0)


@dataclass(frozen=True)
class PairAnalysis:
    analysis_symbol: str
    broker_symbol: str
    reads: tuple[TimeframeRead, ...]
    bias: Bias
    confidence: float
    conflicts: tuple[str, ...]
    limits: tuple[str, ...]

    @property
    def summary(self) -> str:
        return (
            f"{self.analysis_symbol} bias={self.bias.value} "
            f"confidence={self.confidence:.2f}"
        )


def ema(values: list[float], period: int) -> float:
    """Exponential moving average of the most recent `period` window."""
    if not values:
        raise ValueError("ema needs at least one value")
    k = 2.0 / (period + 1)
    out = values[0]
    for v in values[1:]:
        out = v * k + out * (1 - k)
    return out


def atr(bars: tuple[Bar, ...], period: int = 14) -> float:
    """Average true range in price units, including gaps between bars."""
    if len(bars) < 2:
        return 0.0
    window = bars[-(period + 1) :]
    ranges = []
    for prev, cur in zip(window, window[1:]):
        ranges.append(
            max(
                cur.high - cur.low,
                abs(cur.high - prev.close),
                abs(cur.low - prev.close),
            )
        )
    return sum(ranges) / len(ranges) if ranges else 0.0


def read_timeframe(
    timeframe: str, bars: tuple[Bar, ...], spec: SymbolSpec
) -> TimeframeRead:
    """Describe one timeframe. Requires at least 50 bars."""
    if len(bars) < 50:
        raise ValueError(f"{timeframe}: need >=50 bars to read, got {len(bars)}")

    closes = [b.close for b in bars]
    fast, slow = ema(closes[-20:], 20), ema(closes[-50:], 50)

    # Slope of the fast average over the last 10 bars, in pips per bar.
    prior_fast = ema(closes[-30:-10], 20)
    slope_pips = (fast - prior_fast) / spec.pip_size / 10

    atr_pips = atr(bars) / spec.pip_size

    recent = bars[-50:]
    high = max(b.high for b in recent)
    low = min(b.low for b in recent)
    span = high - low
    position = (closes[-1] - low) / span if span > 0 else 0.5

    structure = _structure(bars[-20:])

    evidence = [
        f"EMA20 {'above' if fast > slow else 'below'} EMA50 "
        f"({fast:.5f} vs {slow:.5f})",
        f"EMA20 slope {slope_pips:+.2f} pips/bar over last 10 bars",
        f"price at {position:.0%} of the 50-bar range",
        f"ATR(14) {atr_pips:.1f} pips",
        f"structure: {structure}",
    ]

    trending_up = fast > slow and slope_pips > MIN_SLOPE_PIPS_PER_BAR
    trending_down = fast < slow and slope_pips < -MIN_SLOPE_PIPS_PER_BAR
    bias = Bias.UP if trending_up else Bias.DOWN if trending_down else Bias.FLAT

    if bias is Bias.FLAT:
        evidence.append("no bias: averages and slope disagree, or slope is noise")

    return TimeframeRead(
        timeframe=timeframe,
        bias=bias,
        ema_fast=fast,
        ema_slow=slow,
        slope_pips_per_bar=slope_pips,
        atr_pips=atr_pips,
        range_position=position,
        structure=structure,
        evidence=tuple(evidence),
    )


def _structure(bars: tuple[Bar, ...]) -> str:
    """Swing structure over a short window, in plain terms."""
    mid = len(bars) // 2
    first, second = bars[:mid], bars[mid:]
    if not first or not second:
        return "indeterminate"
    hh = max(b.high for b in second) > max(b.high for b in first)
    hl = min(b.low for b in second) > min(b.low for b in first)
    if hh and hl:
        return "higher highs and higher lows"
    if not hh and not hl:
        return "lower highs and lower lows"
    return "mixed (no clean swing structure)"


def analyse(
    analysis_symbol: str,
    broker_symbol: str,
    bars_by_timeframe: dict[str, tuple[Bar, ...]],
    spec: SymbolSpec,
) -> PairAnalysis:
    """Blend timeframe reads into one bias, with conflicts stated not hidden."""
    reads = tuple(
        read_timeframe(tf, bars, spec)
        for tf, bars in bars_by_timeframe.items()
        if len(bars) >= 50
    )
    if not reads:
        raise ValueError(f"{analysis_symbol}: no timeframe had >=50 bars")

    up = sum(r.weight for r in reads if r.bias is Bias.UP)
    down = sum(r.weight for r in reads if r.bias is Bias.DOWN)
    flat = sum(r.weight for r in reads if r.bias is Bias.FLAT)
    total = up + down + flat

    # A tie resolves to FLAT, never to the more convenient side.
    if up > down:
        bias, aligned = Bias.UP, up
    elif down > up:
        bias, aligned = Bias.DOWN, down
    else:
        bias, aligned = Bias.FLAT, flat

    confidence = min(MAX_CONFIDENCE, aligned / total) if total else 0.0

    conflicts = []
    if up > 0 and down > 0:
        up_tfs = [r.timeframe for r in reads if r.bias is Bias.UP]
        down_tfs = [r.timeframe for r in reads if r.bias is Bias.DOWN]
        conflicts.append(f"{'/'.join(up_tfs)} read up while {'/'.join(down_tfs)} read down")
        confidence *= 0.6  # conflict is stated and it costs confidence
    if bias is not Bias.FLAT:
        against = [
            r.timeframe
            for r in reads
            if r.bias is Bias.FLAT and r.weight >= TIMEFRAME_WEIGHTS["H4"]
        ]
        if against:
            conflicts.append(f"higher timeframe {'/'.join(against)} shows no trend")

    limits = [
        "rule-based trend read, not a forecast; no predictive validation behind it",
        f"confidence is capped at {MAX_CONFIDENCE:.2f} by design",
        "cost of entry (spread, slippage, swap) is not reflected in this bias",
        "no position size implied; sizing belongs to the risk guardian",
    ]
    if len(reads) < len(bars_by_timeframe):
        missing = set(bars_by_timeframe) - {r.timeframe for r in reads}
        limits.append(f"timeframes dropped for insufficient bars: {sorted(missing)}")

    return PairAnalysis(
        analysis_symbol=analysis_symbol,
        broker_symbol=broker_symbol,
        reads=reads,
        bias=bias,
        confidence=round(confidence, 3),
        conflicts=tuple(conflicts),
        limits=tuple(limits),
    )
