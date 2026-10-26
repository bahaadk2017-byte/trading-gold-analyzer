"""Context-only TradingView and Kronos enrichment for MT5 analysis.

Neither component may change the broker-derived bias or confidence. TradingView
responses are normalized and validated at this boundary; Kronos remains weight zero
until its separate evaluation passes.
"""

from __future__ import annotations

import json
import math
import random
import re
import sys
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .analysis import Bias, PairAnalysis
from .contracts import Bar, MarketSnapshot

UTC = timezone.utc
TRADINGVIEW_SOURCE = "tradingview:official-mcp"
TRADINGVIEW_TOOL = "get_technicals_rating"
TRADINGVIEW_INTERVAL = "1h"
TRADINGVIEW_SCHEMA_VERSION = "1"
TRADINGVIEW_RATINGS = frozenset(
    {"STRONG_BUY", "BUY", "NEUTRAL", "SELL", "STRONG_SELL"}
)
MODEL_REVISION = "901c26c1332695a2a8f243eb2f37243a37bea320"
TOKENIZER_REVISION = "0e0117387f39004a9016484a186a908917e22426"
CONTEXT_BARS = 512


@dataclass(frozen=True)
class TradingViewContext:
    """A small normalized subset of an official MCP technicals response."""

    analysis_symbol: str
    tradingview_symbol: str
    retrieved_at_utc: datetime
    summary: str
    moving_averages: str
    other_indicators: str
    source: str = field(default=TRADINGVIEW_SOURCE, init=False)
    tool: str = field(default=TRADINGVIEW_TOOL, init=False)
    interval: str = field(default=TRADINGVIEW_INTERVAL, init=False)
    latency_ms: None = field(default=None, init=False)
    approved_for_decisions: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        _require_utc(self.retrieved_at_utc, "retrieved_at_utc")
        if re.fullmatch(r"[A-Z]{6}", self.analysis_symbol) is None:
            raise ValueError("analysis_symbol must be a six-letter uppercase FX pair")
        if re.fullmatch(r"[A-Z0-9_]+:[A-Z0-9_]+", self.tradingview_symbol) is None:
            raise ValueError("tradingview_symbol must use EXCHANGE:TICKER form")
        ticker = self.tradingview_symbol.split(":", 1)[1]
        if ticker != self.analysis_symbol:
            raise ValueError("TradingView ticker must match analysis_symbol")
        for name in ("summary", "moving_averages", "other_indicators"):
            value = getattr(self, name)
            if value not in TRADINGVIEW_RATINGS:
                raise ValueError(f"unknown TradingView {name} rating: {value!r}")


@dataclass(frozen=True)
class KronosForecast:
    """One experimental next-bar forecast derived only from broker H1 bars."""

    analysis_symbol: str
    last_close: float
    forecast_close: float
    move_pips: float
    direction: str
    issued_at_utc: datetime
    target_event_time_utc: datetime
    target_available_at_utc: datetime
    data_fingerprint: str
    model_revision: str = field(default=MODEL_REVISION, init=False)
    tokenizer_revision: str = field(default=TOKENIZER_REVISION, init=False)
    weight: float = field(default=0.0, init=False)
    approved_for_decisions: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        for name in (
            "issued_at_utc",
            "target_event_time_utc",
            "target_available_at_utc",
        ):
            _require_utc(getattr(self, name), name)
        if not all(
            math.isfinite(value)
            for value in (self.last_close, self.forecast_close, self.move_pips)
        ):
            raise ValueError("Kronos prices and move must be finite")
        if self.last_close <= 0 or self.forecast_close <= 0:
            raise ValueError("Kronos prices must be positive")
        if self.direction not in {"up", "down", "flat"}:
            raise ValueError(f"unknown Kronos direction: {self.direction!r}")
        if self.target_available_at_utc <= self.target_event_time_utc:
            raise ValueError("target availability must be after target bar open")
        if self.issued_at_utc > self.target_event_time_utc:
            raise ValueError("forecast was issued after the target bar opened")


def load_tradingview_contexts(
    path: str | Path,
    expected_pairs: set[str] | None = None,
    *,
    now_utc: datetime | None = None,
    max_age: timedelta = timedelta(minutes=15),
) -> dict[str, TradingViewContext]:
    """Load recent normalized MCP context, rejecting unknown fields and values."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "contexts"}:
        raise ValueError("TradingView context needs schema_version and contexts only")
    if payload["schema_version"] != TRADINGVIEW_SCHEMA_VERSION:
        raise ValueError(f"unsupported TradingView context schema: {payload['schema_version']!r}")
    if not isinstance(payload["contexts"], list):
        raise ValueError("TradingView contexts must be a list")

    checked_at = now_utc or datetime.now(UTC)
    _require_utc(checked_at, "now_utc")
    contexts: dict[str, TradingViewContext] = {}
    for raw in payload["contexts"]:
        context = _parse_tradingview_context(raw)
        age = checked_at - context.retrieved_at_utc
        if age < timedelta(0) or age > max_age:
            raise ValueError(
                f"TradingView context for {context.analysis_symbol} is {age} old; "
                f"limit is {max_age}"
            )
        if expected_pairs is not None and context.analysis_symbol not in expected_pairs:
            raise ValueError(
                f"unexpected TradingView pair {context.analysis_symbol!r}; "
                f"expected one of {sorted(expected_pairs)}"
            )
        if context.analysis_symbol in contexts:
            raise ValueError(f"duplicate TradingView pair {context.analysis_symbol!r}")
        contexts[context.analysis_symbol] = context
    return contexts


def _parse_tradingview_context(raw: object) -> TradingViewContext:
    fields = {
        "source",
        "tool",
        "interval",
        "analysis_symbol",
        "tradingview_symbol",
        "retrieved_at_utc",
        "summary",
        "moving_averages",
        "other_indicators",
    }
    if not isinstance(raw, dict) or set(raw) != fields:
        raise ValueError(f"TradingView context fields must be exactly {sorted(fields)}")
    if raw["source"] != TRADINGVIEW_SOURCE:
        raise ValueError("TradingView context source is not the official MCP")
    if raw["tool"] != TRADINGVIEW_TOOL:
        raise ValueError("TradingView context used an unsupported tool")
    if raw["interval"] != TRADINGVIEW_INTERVAL:
        raise ValueError("TradingView context must use the 1h interval")

    text_fields = fields - {"retrieved_at_utc"}
    if any(not isinstance(raw[name], str) for name in text_fields):
        raise ValueError("TradingView context text fields must be strings")
    try:
        retrieved = datetime.fromisoformat(str(raw["retrieved_at_utc"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("retrieved_at_utc must be an ISO-8601 timestamp") from exc

    return TradingViewContext(
        analysis_symbol=raw["analysis_symbol"],
        tradingview_symbol=raw["tradingview_symbol"],
        retrieved_at_utc=retrieved,
        summary=raw["summary"],
        moving_averages=raw["moving_averages"],
        other_indicators=raw["other_indicators"],
    )


def complete_context_bars(
    bars: tuple[Bar, ...], now_utc: datetime, context: int = CONTEXT_BARS
) -> tuple[Bar, ...]:
    """Return the latest complete bars; a forming bar is never model input."""
    _require_utc(now_utc, "now_utc")
    complete = tuple(bar for bar in bars if bar.info_available_at_utc <= now_utc)
    if len(complete) < context:
        raise ValueError(f"Kronos needs {context} complete bars, got {len(complete)}")
    return complete[-context:]


class KronosRunner:
    """Load pinned Kronos weights once and produce deterministic forecasts."""

    def __init__(self, root: Path, device: str = "cuda:0") -> None:
        import numpy as np
        import pandas as pd
        import torch

        kronos = root / "external" / "Kronos"
        if not kronos.is_dir():
            raise FileNotFoundError(f"Kronos checkout not found: {kronos}")
        sys.path.insert(0, str(kronos))
        from model import Kronos, KronosPredictor, KronosTokenizer

        self._np = np
        self._pd = pd
        self._torch = torch
        tokenizer = KronosTokenizer.from_pretrained(
            "NeoQuasar/Kronos-Tokenizer-base", revision=TOKENIZER_REVISION
        ).eval()
        model = Kronos.from_pretrained(
            "NeoQuasar/Kronos-small", revision=MODEL_REVISION
        ).eval()
        self._predictor = KronosPredictor(
            model, tokenizer, device=device, max_context=CONTEXT_BARS
        )

    def predict_close(self, context: tuple[Bar, ...]) -> float:
        """Predict the close of the bar immediately following this context."""
        if len(context) != CONTEXT_BARS:
            raise ValueError(f"Kronos context must contain exactly {CONTEXT_BARS} bars")
        timeframe = context[0].timeframe_seconds
        if any(bar.timeframe_seconds != timeframe for bar in context):
            raise ValueError("Kronos context contains mixed timeframes")

        random.seed(123)
        self._np.random.seed(123)
        self._torch.manual_seed(123)
        frame = self._pd.DataFrame(
            {
                "open": [bar.open for bar in context],
                "high": [bar.high for bar in context],
                "low": [bar.low for bar in context],
                "close": [bar.close for bar in context],
            }
        )
        timestamps = self._pd.Series([bar.event_time_utc for bar in context])
        target = context[-1].event_time_utc + timedelta(seconds=timeframe)
        with self._torch.no_grad():
            forecast = self._predictor.predict(
                frame,
                timestamps,
                self._pd.Series([target]),
                pred_len=1,
                T=1.0,
                top_k=1,
                top_p=1.0,
                sample_count=1,
                verbose=False,
            )
        return float(forecast.iloc[0]["close"])

    def forecast(self, snapshot: MarketSnapshot, issued_at_utc: datetime) -> KronosForecast:
        context = complete_context_bars(snapshot.bars, issued_at_utc)
        predicted = self.predict_close(context)
        last = context[-1]
        move_pips = snapshot.spec.price_to_pips(predicted - last.close)
        direction = "flat" if abs(move_pips) <= 0.1 else "up" if move_pips > 0 else "down"
        target_event = last.info_available_at_utc
        context_snapshot = replace(snapshot, bars=context)
        return KronosForecast(
            analysis_symbol=snapshot.spec.analysis_symbol,
            last_close=last.close,
            forecast_close=predicted,
            move_pips=move_pips,
            direction=direction,
            issued_at_utc=issued_at_utc,
            target_event_time_utc=target_event,
            target_available_at_utc=target_event
            + timedelta(seconds=last.timeframe_seconds),
            data_fingerprint=context_snapshot.fingerprint,
        )


def context_alignment(
    analysis: PairAnalysis,
    kronos: KronosForecast | None,
    tradingview: TradingViewContext | None,
) -> str:
    """Describe context agreement without altering the decision-grade analysis."""
    directions = []
    if kronos is not None:
        directions.append(kronos.direction)
    if tradingview is not None:
        directions.append(_rating_direction(tradingview.summary))
    if not directions:
        return "unavailable"
    if analysis.bias is Bias.FLAT or "flat" in directions:
        return "mixed"
    if all(direction == analysis.bias.value for direction in directions):
        return "agreement"
    opposite = "down" if analysis.bias is Bias.UP else "up"
    if all(direction == opposite for direction in directions):
        return "disagreement"
    return "mixed"


def _rating_direction(rating: str) -> str:
    if rating.endswith("BUY"):
        return "up"
    if rating.endswith("SELL"):
        return "down"
    return "flat"


def _require_utc(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be timezone-aware UTC")
