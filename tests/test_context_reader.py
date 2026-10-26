"""Tests for dashboard context-only views."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from dashboard import context_reader as reader
from dashboard.app import api_context


def _run(*, tradingview: dict | None = None, kronos: dict | None = None) -> dict:
    result = {
        "pair": "EURUSD",
        "broker_symbol": "EURUSDm#",
        "decision": "ANALYSED",
    }
    if tradingview is not None:
        result["tradingview"] = tradingview
    if kronos is not None:
        result["kronos"] = kronos
    return {
        "started_utc": "2026-10-25T12:00:00+00:00",
        "account": {"is_real_account": False},
        "results": [result],
    }


def _tradingview(**overrides: object) -> dict:
    context = {
        "status": "available",
        "source": "tradingview:official-mcp",
        "tool": "get_technicals_rating",
        "interval": "1h",
        "analysis_symbol": "EURUSD",
        "tradingview_symbol": "OANDA:EURUSD",
        "retrieved_at_utc": "2026-10-25T12:00:00+00:00",
        "summary": "BUY",
        "moving_averages": "BUY",
        "other_indicators": "NEUTRAL",
        "approved_for_decisions": False,
    }
    context.update(overrides)
    return context


def _kronos(**overrides: object) -> dict:
    forecast = {
        "status": "available",
        "analysis_symbol": "EURUSD",
        "last_close": 1.1,
        "forecast_close": 1.101,
        "move_pips": 10.0,
        "direction": "up",
        "issued_at_utc": "2026-10-25T12:00:00+00:00",
        "target_event_time_utc": "2026-10-25T12:00:00+00:00",
        "target_available_at_utc": "2026-10-25T13:00:00+00:00",
        "data_fingerprint": "ab12cd34",
        "model_revision": "model123",
        "tokenizer_revision": "token123",
        "weight": 0.0,
        "approved_for_decisions": False,
    }
    forecast.update(overrides)
    return forecast


def test_context_view_returns_a_sanitized_tradingview_embed(monkeypatch):
    monkeypatch.setattr(reader, "get_latest_run", lambda: _run(tradingview=_tradingview()))

    view = reader.get_context_view("EURUSD")

    assert view is not None
    assert view["analysis_symbol"] == "EURUSD"
    assert view["broker_symbol"] == "EURUSDm#"
    assert view["environment"] == "DEMO"
    assert view["tradingview"]["approved_for_decisions"] is False
    assert view["tradingview"]["provenance"]["completeness"] is None
    parsed = urlparse(view["tradingview"]["embed_url"])
    assert parsed.scheme == "https"
    assert parsed.netloc == "s.tradingview.com"
    assert parse_qs(parsed.query)["symbol"] == ["OANDA:EURUSD"]


def test_context_view_refuses_invalid_persisted_tradingview_data(monkeypatch):
    monkeypatch.setattr(
        reader,
        "get_latest_run",
        lambda: _run(tradingview=_tradingview(source="untrusted:feed")),
    )

    view = reader.get_context_view("EURUSD")

    assert view is not None
    assert view["tradingview"] == {
        "status": "unavailable",
        "reason": "MISSING_OR_INVALID_CONTEXT",
    }


def test_context_view_keeps_kronos_experimental_and_weight_zero(monkeypatch):
    monkeypatch.setattr(
        reader,
        "get_latest_run",
        lambda: _run(tradingview=_tradingview(), kronos=_kronos()),
    )

    view = reader.get_context_view("EURUSD")

    assert view is not None
    assert view["kronos"]["status"] == "available"
    assert view["kronos"]["weight"] == 0.0
    assert view["kronos"]["approved_for_decisions"] is False
    assert view["kronos"]["confidence_intervals_available"] is False


def test_context_view_refuses_kronos_with_decision_weight(monkeypatch):
    monkeypatch.setattr(
        reader,
        "get_latest_run",
        lambda: _run(kronos=_kronos(weight=0.25)),
    )

    view = reader.get_context_view("EURUSD")

    assert view is not None
    assert view["kronos"] == {
        "status": "unavailable",
        "reason": "MISSING_OR_INVALID_FORECAST",
    }


def test_context_endpoint_is_read_only_json(monkeypatch):
    monkeypatch.setattr(reader, "get_latest_run", lambda: _run(tradingview=_tradingview()))

    response = api_context("EURUSD")

    assert response.status_code == 200
    assert response.media_type == "application/json"
    assert b'"approved_for_decisions":false' in response.body


def test_context_view_does_not_resolve_unknown_pair(monkeypatch):
    monkeypatch.setattr(reader, "get_latest_run", lambda: _run(tradingview=_tradingview()))

    assert reader.get_context_view("GBPUSD") is None
    assert reader.get_context_view("../../secrets") is None
