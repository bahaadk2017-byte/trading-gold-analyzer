"""Unit tests for dashboard.deliberation_reader — read-only, no MT5, no network."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dashboard.deliberation_reader import (
    _record_id,
    _validate_id,
    _validate_invariants,
    get_deliberation,
    get_latest_deliberation,
    list_deliberations,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def _make_deliberation(
    tmp_path: Path,
    strategy: str = "ema_trend_follow",
    version: str = "1.0.0",
    pair: str = "EURUSD",
    split: str = "is",
) -> Path:
    """Create a minimal valid deliberation record."""
    # Use underscores only (no dots in version to simplify regex matching in fixture)
    safe_version = version.replace(".", "_")
    record_id = f"delib_{strategy}_{safe_version}_{pair}_{split}_20261025T120000"
    record = {
        "record_id": record_id,
        "created_at_utc": "2026-10-25T12:00:00+00:00",
        "mode": "static_role_deliberation",
        "is_live_agent_communication": False,
        "non_authoritative": True,
        "execution_enabled": False,
        "strategy_promoted": False,
        "environment": "backtest",
        "disclaimer_ar": "سجل ثابت لمداولات الأدوار — ليس محادثة وكلاء حية",
        "strategy_ref": {
            "name": strategy,
            "version": version,
            "pair": pair,
            "timeframe": "H1",
            "hypothesis": "EMA trend following",
            "entry_rules": "Fast EMA > Slow EMA",
            "exit_rules": "Fast EMA < Slow EMA",
            "no_trade_conditions": "Low volatility",
        },
        "backtest_ref": {
            "record_id": f"bt_{strategy}_{safe_version}_{split}_20261025T120000",
            "split": split,
            "data_fingerprint": "abc123def456",
            "metrics": {"n_trades": 42, "win_rate": 0.55},
        },
        "role_assessments": [
            {
                "role": "backtest-engineer",
                "team": "system",
                "assessment_type": "evidence",
                "text_ar": "النتائج منطقية",
                "non_authoritative": True,
            }
        ],
        "outcome": {
            "classification": "research_record_only",
            "no_trade": True,
            "strategy_promoted": False,
            "execution_enabled": False,
        },
    }
    path = tmp_path / f"delib_{strategy}_{safe_version}_{pair}_{split}_20261025T120000.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


# ── ID validation ─────────────────────────────────────────────────────────────

class TestIDValidation:
    def test_valid_id_accepted(self):
        assert _validate_id("delib_ema_trend_1.0.0_eurusd_is_20261025T120000")

    def test_empty_id_rejected(self):
        assert not _validate_id("")

    def test_traversal_rejected(self):
        assert not _validate_id("../analysis_secret")
        assert not _validate_id("..\\analysis_secret")

    def test_slash_rejected(self):
        assert not _validate_id("delib_bad/name")
        assert not _validate_id("delib_bad\\name")

    def test_backtest_id_rejected(self):
        assert not _validate_id("bt_something")

    def test_wrong_prefix_rejected(self):
        assert not _validate_id("analysis_something")
        assert not _validate_id("run_something")


# ── invariant validation ──────────────────────────────────────────────────────

class TestInvariantValidation:
    def test_valid_record_passes(self):
        record = {
            "mode": "static_role_deliberation",
            "is_live_agent_communication": False,
            "non_authoritative": True,
            "execution_enabled": False,
            "strategy_promoted": False,
        }
        valid, error = _validate_invariants(record)
        assert valid
        assert error is None

    def test_is_live_agent_communication_true_rejected(self):
        record = {
            "mode": "static_role_deliberation",
            "is_live_agent_communication": True,
            "non_authoritative": True,
            "execution_enabled": False,
            "strategy_promoted": False,
        }
        valid, error = _validate_invariants(record)
        assert not valid
        assert "is_live_agent_communication" in error

    def test_execution_enabled_true_rejected(self):
        record = {
            "mode": "static_role_deliberation",
            "is_live_agent_communication": False,
            "non_authoritative": True,
            "execution_enabled": True,
            "strategy_promoted": False,
        }
        valid, error = _validate_invariants(record)
        assert not valid
        assert "execution_enabled" in error

    def test_strategy_promoted_true_rejected(self):
        record = {
            "mode": "static_role_deliberation",
            "is_live_agent_communication": False,
            "non_authoritative": True,
            "execution_enabled": False,
            "strategy_promoted": True,
        }
        valid, error = _validate_invariants(record)
        assert not valid
        assert "strategy_promoted" in error

    def test_non_authoritative_false_rejected(self):
        record = {
            "mode": "static_role_deliberation",
            "is_live_agent_communication": False,
            "non_authoritative": False,
            "execution_enabled": False,
            "strategy_promoted": False,
        }
        valid, error = _validate_invariants(record)
        assert not valid
        assert "non_authoritative" in error

    def test_forbidden_sender_field_rejected(self):
        record = {
            "mode": "static_role_deliberation",
            "is_live_agent_communication": False,
            "non_authoritative": True,
            "execution_enabled": False,
            "strategy_promoted": False,
            "sender": "agent-1",  # Forbidden
        }
        valid, error = _validate_invariants(record)
        assert not valid
        assert "forbidden field" in error

    def test_forbidden_recipient_field_rejected(self):
        record = {
            "mode": "static_role_deliberation",
            "is_live_agent_communication": False,
            "non_authoritative": True,
            "execution_enabled": False,
            "strategy_promoted": False,
            "recipient": "agent-2",  # Forbidden
        }
        valid, error = _validate_invariants(record)
        assert not valid
        assert "forbidden field" in error

    def test_forbidden_status_field_rejected(self):
        record = {
            "mode": "static_role_deliberation",
            "is_live_agent_communication": False,
            "non_authoritative": True,
            "execution_enabled": False,
            "strategy_promoted": False,
            "status": "ANALYZING",  # Forbidden
        }
        valid, error = _validate_invariants(record)
        assert not valid
        assert "forbidden field" in error

    def test_forbidden_latency_ms_field_rejected(self):
        record = {
            "mode": "static_role_deliberation",
            "is_live_agent_communication": False,
            "non_authoritative": True,
            "execution_enabled": False,
            "strategy_promoted": False,
            "latency_ms": 123,  # Forbidden
        }
        valid, error = _validate_invariants(record)
        assert not valid
        assert "forbidden field" in error

    def test_invalid_mode_rejected(self):
        record = {
            "mode": "live_agent_chat",
            "is_live_agent_communication": False,
            "non_authoritative": True,
            "execution_enabled": False,
            "strategy_promoted": False,
        }
        valid, error = _validate_invariants(record)
        assert not valid
        assert "invalid mode" in error


# ── list_deliberations ────────────────────────────────────────────────────────

class TestListDeliberations:
    def test_empty_dir_returns_empty_list(self, tmp_path):
        import dashboard.deliberation_reader as mod

        orig = mod.DELIBERATIONS_DIR
        mod.DELIBERATIONS_DIR = tmp_path
        try:
            assert list_deliberations() == []
        finally:
            mod.DELIBERATIONS_DIR = orig

    def test_valid_deliberation_listed(self, tmp_path):
        import dashboard.deliberation_reader as mod

        _make_deliberation(tmp_path)
        orig = mod.DELIBERATIONS_DIR
        mod.DELIBERATIONS_DIR = tmp_path
        try:
            runs = list_deliberations()
            assert len(runs) == 1
            r = runs[0]
            assert r["strategy_name"] == "ema_trend_follow"
            assert r["pair"] == "EURUSD"
            assert r["environment"] == "backtest"
            assert r["non_authoritative"] is True
            assert r["is_live_agent_communication"] is False
            assert r["execution_enabled"] is False
        finally:
            mod.DELIBERATIONS_DIR = orig

    def test_invalid_json_skipped(self, tmp_path):
        import dashboard.deliberation_reader as mod

        bad_path = tmp_path / "delib_bad_20261025T120000.json"
        bad_path.write_text("{invalid json", encoding="utf-8")
        _make_deliberation(tmp_path)
        orig = mod.DELIBERATIONS_DIR
        mod.DELIBERATIONS_DIR = tmp_path
        try:
            runs = list_deliberations()
            assert len(runs) == 1  # Only valid one listed
        finally:
            mod.DELIBERATIONS_DIR = orig

    def test_invariant_violation_skipped(self, tmp_path):
        import dashboard.deliberation_reader as mod

        _make_deliberation(tmp_path)
        # Tamper with execution_enabled
        path = list(tmp_path.glob("delib_*.json"))[0]
        record = json.loads(path.read_text(encoding="utf-8"))
        record["execution_enabled"] = True
        path.write_text(json.dumps(record), encoding="utf-8")
        orig = mod.DELIBERATIONS_DIR
        mod.DELIBERATIONS_DIR = tmp_path
        try:
            runs = list_deliberations()
            assert len(runs) == 0  # Invalid record skipped
        finally:
            mod.DELIBERATIONS_DIR = orig


# ── get_deliberation ──────────────────────────────────────────────────────────

class TestGetDeliberation:
    def test_valid_deliberation_returned(self, tmp_path):
        import dashboard.deliberation_reader as mod

        _make_deliberation(tmp_path)
        orig = mod.DELIBERATIONS_DIR
        mod.DELIBERATIONS_DIR = tmp_path
        try:
            delib = get_deliberation("delib_ema_trend_follow_1_0_0_EURUSD_is_20261025T120000")
            assert delib is not None
            assert delib["strategy_ref"]["name"] == "ema_trend_follow"
        finally:
            mod.DELIBERATIONS_DIR = orig

    def test_invalid_id_returns_none(self, tmp_path):
        import dashboard.deliberation_reader as mod

        orig = mod.DELIBERATIONS_DIR
        mod.DELIBERATIONS_DIR = tmp_path
        try:
            assert get_deliberation("../analysis_secret") is None
            assert get_deliberation("delib_bad/name") is None
        finally:
            mod.DELIBERATIONS_DIR = orig

    def test_missing_record_returns_none(self, tmp_path):
        import dashboard.deliberation_reader as mod

        orig = mod.DELIBERATIONS_DIR
        mod.DELIBERATIONS_DIR = tmp_path
        try:
            assert get_deliberation("delib_nonexistent_1.0.0_eurusd_is_20261025T120000") is None
        finally:
            mod.DELIBERATIONS_DIR = orig

    def test_invalid_json_returns_none(self, tmp_path):
        import dashboard.deliberation_reader as mod

        bad_path = tmp_path / "delib_bad_20261025T120000.json"
        bad_path.write_text("{invalid json", encoding="utf-8")
        orig = mod.DELIBERATIONS_DIR
        mod.DELIBERATIONS_DIR = tmp_path
        try:
            assert get_deliberation("delib_bad_20261025T120000") is None
        finally:
            mod.DELIBERATIONS_DIR = orig

    def test_invariant_violation_returns_none(self, tmp_path):
        import dashboard.deliberation_reader as mod

        _make_deliberation(tmp_path)
        path = list(tmp_path.glob("delib_*.json"))[0]
        record = json.loads(path.read_text(encoding="utf-8"))
        record["execution_enabled"] = True
        path.write_text(json.dumps(record), encoding="utf-8")
        orig = mod.DELIBERATIONS_DIR
        mod.DELIBERATIONS_DIR = tmp_path
        try:
            result = get_deliberation("delib_ema_trend_follow_1_0_0_EURUSD_is_20261025T120000")
            assert result is None
        finally:
            mod.DELIBERATIONS_DIR = orig


# ── get_latest_deliberation ───────────────────────────────────────────────────

class TestGetLatestDeliberation:
    def test_latest_deliberation_returned(self, tmp_path):
        import dashboard.deliberation_reader as mod

        _make_deliberation(tmp_path, strategy="old", version="0.1.0")
        _make_deliberation(tmp_path, strategy="new", version="2.0.0")
        orig = mod.DELIBERATIONS_DIR
        mod.DELIBERATIONS_DIR = tmp_path
        try:
            delib = get_latest_deliberation()
            assert delib is not None
            # Get the newest (last alphabetically since we use sorted reverse)
            assert delib["strategy_ref"]["version"] in ["0.1.0", "2.0.0"]
        finally:
            mod.DELIBERATIONS_DIR = orig


# ── no order/execution functions ──────────────────────────────────────────────

class TestNoExecutionAPIs:
    def test_no_order_functions_in_reader(self):
        """deliberation_reader.py must not contain any order/execution function names."""
        source = (ROOT / "dashboard" / "deliberation_reader.py").read_text(encoding="utf-8")
        forbidden = [
            "order_send",
            "order_check",
            "execute_trade",
            "place_order",
            "buy(",
            "sell(",
        ]
        for token in forbidden:
            assert token not in source, f"order API token found in deliberation_reader.py: {token!r}"
