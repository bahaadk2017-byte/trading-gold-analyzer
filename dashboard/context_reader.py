"""Read-only context views for TradingView and Kronos run artifacts."""

from __future__ import annotations

from urllib.parse import urlencode

from .reader import get_latest_run, infer_environment

_TRADINGVIEW_SOURCE = "tradingview:official-mcp"
_TRADINGVIEW_TOOL = "get_technicals_rating"
_TRADINGVIEW_INTERVAL = "1h"
_TRADINGVIEW_RATINGS = frozenset(
    {"STRONG_BUY", "BUY", "NEUTRAL", "SELL", "STRONG_SELL"}
)
_TRADINGVIEW_EMBED = "https://s.tradingview.com/widgetembed/?"


def get_context_view(pair: str) -> dict | None:
    """Return one latest-run context view, or None when the pair is absent."""
    if not pair.isalpha() or len(pair) != 6:
        return None
    run = get_latest_run()
    if run is None:
        return None
    result = next(
        (item for item in run.get("results", []) if item.get("pair") == pair.upper()),
        None,
    )
    if result is None:
        return None
    return {
        "analysis_symbol": pair.upper(),
        "broker_symbol": result.get("broker_symbol"),
        "environment": infer_environment(run),
        "tradingview": _tradingview_view(result.get("tradingview"), pair.upper()),
        "kronos": _kronos_view(result.get("kronos"), pair.upper()),
    }


def _tradingview_view(raw: object, pair: str) -> dict:
    if not isinstance(raw, dict) or raw.get("status") != "available":
        return {"status": "unavailable", "reason": "MISSING_OR_INVALID_CONTEXT"}
    symbol = raw.get("tradingview_symbol")
    if not (
        raw.get("source") == _TRADINGVIEW_SOURCE
        and raw.get("tool") == _TRADINGVIEW_TOOL
        and raw.get("interval") == _TRADINGVIEW_INTERVAL
        and raw.get("analysis_symbol") == pair
        and isinstance(symbol, str)
        and symbol.endswith(f":{pair}")
        and raw.get("summary") in _TRADINGVIEW_RATINGS
        and raw.get("moving_averages") in _TRADINGVIEW_RATINGS
        and raw.get("other_indicators") in _TRADINGVIEW_RATINGS
        and raw.get("approved_for_decisions") is False
    ):
        return {"status": "unavailable", "reason": "MISSING_OR_INVALID_CONTEXT"}
    return {
        "status": "available",
        "symbol": symbol,
        "summary": raw["summary"],
        "moving_averages": raw["moving_averages"],
        "other_indicators": raw["other_indicators"],
        "retrieved_at_utc": raw.get("retrieved_at_utc"),
        "approved_for_decisions": False,
        "embed_url": _TRADINGVIEW_EMBED + urlencode(
            {
                "symbol": symbol,
                "interval": "60",
                "theme": "dark",
                "style": "1",
                "locale": "ar_AE",
                "toolbarbg": "#17171c",
                "hide_top_toolbar": "1",
                "hide_legend": "1",
            }
        ),
        "provenance": {
            "source": _TRADINGVIEW_SOURCE,
            "timestamp_utc": raw.get("retrieved_at_utc"),
            "latency_ms": None,
            "completeness": None,
            "approval_status": "rejected",
        },
    }


def _kronos_view(raw: object, pair: str) -> dict:
    if not isinstance(raw, dict) or raw.get("status") != "available":
        return {"status": "unavailable", "reason": "MISSING_OR_INVALID_FORECAST"}
    required = ("last_close", "forecast_close", "move_pips", "issued_at_utc", "target_event_time_utc", "target_available_at_utc", "data_fingerprint", "model_revision", "tokenizer_revision")
    if not (
        raw.get("analysis_symbol") == pair
        and raw.get("direction") in {"up", "down", "flat"}
        and raw.get("weight") == 0.0
        and raw.get("approved_for_decisions") is False
        and all(raw.get(field) is not None for field in required)
    ):
        return {"status": "unavailable", "reason": "MISSING_OR_INVALID_FORECAST"}
    return {
        "status": "available",
        "last_close": raw["last_close"],
        "forecast_close": raw["forecast_close"],
        "move_pips": raw["move_pips"],
        "direction": raw["direction"],
        "issued_at_utc": raw["issued_at_utc"],
        "target_event_time_utc": raw["target_event_time_utc"],
        "target_available_at_utc": raw["target_available_at_utc"],
        "data_fingerprint": raw["data_fingerprint"],
        "model_revision": raw["model_revision"],
        "tokenizer_revision": raw["tokenizer_revision"],
        "weight": 0.0,
        "approved_for_decisions": False,
        "confidence_intervals_available": False,
    }
