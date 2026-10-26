"""Tests for dashboard backtest result readers."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dashboard import backtest_reader as reader


def _write_result(directory: Path, record_id: str, **overrides) -> None:
    payload = {
        "pair": "EURUSD",
        "split": "is",
        "trades": [
            {
                "entry_time": "2026-01-01T00:00:00+00:00",
                "exit_time": "2026-01-01T02:00:00+00:00",
                "net_pips": 4.5,
                "direction": "long",
                "exit_reason": "target",
            }
        ],
        **overrides,
    }
    (directory / f"{record_id}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_get_backtest_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(reader, "BT_DIR", tmp_path)
    assert reader.get_backtest_run("../analysis_secret") is None
    assert reader.get_backtest_run("bt_bad/name") is None


def test_get_backtest_returns_matching_record(tmp_path, monkeypatch):
    monkeypatch.setattr(reader, "BT_DIR", tmp_path)
    record_id = "bt_ema_trend_follow_1.0.0_is_20261025T104517"
    _write_result(tmp_path, record_id)

    result = reader.get_backtest_run(record_id)

    assert result is not None
    assert result["record_id"] == record_id
    assert result["pair"] == "EURUSD"


def test_equity_curve_and_pair_summary():
    curve = reader.equity_curve([
        {"entry_time": "2026-01-01T00:00:00+00:00", "net_pips": 5, "direction": "long"},
        {"exit_time": "2026-01-02T00:00:00+00:00", "net_pips": -2, "direction": "short", "exit_reason": "stop"},
    ])

    assert [point["equity"] for point in curve] == [5.0, 3.0]
    assert curve[-1]["exit_reason"] == "stop"
    summaries = reader.pair_summary([
        {"pair": "EURUSD", "split": "oos", "record_id": "oos"},
        {"pair": "EURUSD", "split": "is", "record_id": "latest-is"},
        {"pair": "EURUSD", "split": "is", "record_id": "older-is"},
        {"pair": "GBPUSD", "split": "is", "record_id": "gbp-is"},
    ])
    assert [summary["record_id"] for summary in summaries] == ["latest-is", "gbp-is"]
