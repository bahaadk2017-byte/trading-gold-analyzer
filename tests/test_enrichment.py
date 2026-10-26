"""Context enrichment cannot acquire decision authority."""

from __future__ import annotations

import json
import sys
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fxcore.analysis import Bias, PairAnalysis
from fxcore.contracts import Bar
from fxcore.enrichment import (
    CONTEXT_BARS,
    KronosForecast,
    TradingViewContext,
    complete_context_bars,
    context_alignment,
    load_tradingview_contexts,
)

UTC = timezone.utc
NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)


def tv_payload(**overrides: object) -> dict:
    context = {
        "source": "tradingview:official-mcp",
        "tool": "get_technicals_rating",
        "interval": "1h",
        "analysis_symbol": "EURUSD",
        "tradingview_symbol": "OANDA:EURUSD",
        "retrieved_at_utc": NOW.isoformat(),
        "summary": "BUY",
        "moving_averages": "STRONG_BUY",
        "other_indicators": "NEUTRAL",
    }
    context.update(overrides)
    return {"schema_version": "1", "contexts": [context]}


def write_payload(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "context.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def analysis(bias: Bias = Bias.UP) -> PairAnalysis:
    return PairAnalysis("EURUSD", "EURUSDm#", (), bias, 0.62, (), ())


def kronos(direction: str = "up") -> KronosForecast:
    return KronosForecast(
        analysis_symbol="EURUSD",
        last_close=1.10,
        forecast_close=1.11,
        move_pips=100.0,
        direction=direction,
        issued_at_utc=NOW,
        target_event_time_utc=NOW,
        target_available_at_utc=NOW + timedelta(hours=1),
        data_fingerprint="abc",
    )


class TestTradingViewBoundary:
    def test_valid_official_context_loads(self, tmp_path: Path):
        loaded = load_tradingview_contexts(
            write_payload(tmp_path, tv_payload()), {"EURUSD"}, now_utc=NOW
        )
        context = loaded["EURUSD"]
        assert context.summary == "BUY"
        assert context.approved_for_decisions is False
        assert context.latency_ms is None

    @pytest.mark.parametrize(
        ("field", "value", "message"),
        [
            ("source", "tradingview-mcp-independent", "official MCP"),
            ("tool", "get_ohlcv", "unsupported tool"),
            ("interval", "4h", "1h interval"),
            ("summary", "GO_LONG", "unknown TradingView"),
            ("tradingview_symbol", "OANDA:GBPUSD", "must match"),
            ("retrieved_at_utc", "2026-10-24T12:00:00", "UTC"),
        ],
    )
    def test_untrusted_shape_or_value_is_refused(
        self, tmp_path: Path, field: str, value: str, message: str
    ):
        with pytest.raises(ValueError, match=message):
            load_tradingview_contexts(
                write_payload(tmp_path, tv_payload(**{field: value})),
                {"EURUSD"},
                now_utc=NOW,
            )

    def test_unexpected_pair_is_refused(self, tmp_path: Path):
        with pytest.raises(ValueError, match="unexpected TradingView pair"):
            load_tradingview_contexts(
                write_payload(
                    tmp_path,
                    tv_payload(
                        analysis_symbol="GBPUSD", tradingview_symbol="OANDA:GBPUSD"
                    ),
                ),
                {"EURUSD"},
                now_utc=NOW,
            )

    def test_unknown_fields_are_refused(self, tmp_path: Path):
        payload = tv_payload(approved_for_decisions=True)
        with pytest.raises(ValueError, match="fields must be exactly"):
            load_tradingview_contexts(
                write_payload(tmp_path, payload), {"EURUSD"}, now_utc=NOW
            )

    def test_stale_context_is_refused(self, tmp_path: Path):
        with pytest.raises(ValueError, match="is .* old"):
            load_tradingview_contexts(
                write_payload(tmp_path, tv_payload()),
                {"EURUSD"},
                now_utc=NOW + timedelta(minutes=16),
            )

    def test_authority_fields_are_immutable(self):
        context = TradingViewContext(
            "EURUSD", "OANDA:EURUSD", NOW, "BUY", "BUY", "NEUTRAL"
        )
        with pytest.raises(FrozenInstanceError):
            context.approved_for_decisions = True  # type: ignore[misc]


class TestKronosBoundary:
    def test_weight_and_authority_are_fixed(self):
        forecast = kronos()
        assert forecast.weight == 0.0
        assert forecast.approved_for_decisions is False
        with pytest.raises(FrozenInstanceError):
            forecast.weight = 1.0  # type: ignore[misc]

    def test_only_complete_latest_512_bars_are_used(self):
        start = NOW - timedelta(hours=CONTEXT_BARS)
        bars = tuple(
            Bar(
                event_time_utc=start + timedelta(hours=i),
                timeframe_seconds=3600,
                open=1.1,
                high=1.2,
                low=1.0,
                close=1.1,
                tick_updates=10,
            )
            for i in range(CONTEXT_BARS + 1)
        )
        selected = complete_context_bars(bars, NOW)
        assert len(selected) == CONTEXT_BARS
        assert selected[-1].info_available_at_utc <= NOW
        assert bars[-1] not in selected

    def test_too_few_complete_bars_are_refused(self):
        bar = Bar(NOW, 3600, 1.1, 1.2, 1.0, 1.1, 10)
        with pytest.raises(ValueError, match="needs 512 complete bars"):
            complete_context_bars((bar,), NOW)


class TestDescriptiveAlignment:
    def test_context_does_not_mutate_analysis(self):
        original = analysis()
        before = (original.bias, original.confidence)
        tv = TradingViewContext(
            "EURUSD", "OANDA:EURUSD", NOW, "SELL", "SELL", "NEUTRAL"
        )
        assert context_alignment(original, kronos("down"), tv) == "disagreement"
        assert (original.bias, original.confidence) == before

    def test_missing_context_is_non_blocking(self):
        original = analysis()
        assert context_alignment(original, None, None) == "unavailable"
        assert original.bias is Bias.UP
        assert original.confidence == 0.62

    def test_split_context_is_reported_as_mixed(self):
        tv = TradingViewContext(
            "EURUSD", "OANDA:EURUSD", NOW, "SELL", "SELL", "NEUTRAL"
        )
        assert context_alignment(analysis(), kronos("up"), tv) == "mixed"
